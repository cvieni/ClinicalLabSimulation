"""Shortage forecast + response recommender, constrained by the Monte Carlo simulation.

How the simulation constrains the model
  * Every training example is a simulated supply disruption (scenario) plus a candidate response (staffing,
    expedite, reserve, sparing), run through the real simulator with common random numbers.
  * The surrogate models only learn simulator behaviour; the recommender may only pick responses whose PREDICTED
    outcome is inside the limits (per-group p95 TAT vs the no-disruption baseline, specimens aborted for media),
    and the finalists are RE-RUN in the simulator before anything is reported as feasible.

Commands (see run_ml_pipeline.py):  gen | train | forecast | recommend | validate
"""
import argparse
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------------------------------------
# Editable assumptions (review these!)
# ----------------------------------------------------------------------------------------------------------
PRIORITY_TYPES = ["BCx", "BodyFluid", "Bone_Cx", "Tissue", "Urine_Invasive", "Resp_CystFibrosis"]   # protected by 'reserve'
SPARE_DROP = {"CNA_Agar": ["Wound", "Wound_Genital", "Respiratory", "Tissue", "Bone_Cx"],           # optional media that may be
              "ChromeAgar": ["Urine_NonInvasive"]}                                                   # skipped when sparing
STAFF_BENCHES = {"accession": "tech_accession", "plating": "tech_plating", "new": "tech_new", "routine": "tech_routine"}
STAFF_SHIFTS = {"day": "Day", "eve": "Evening"}
STAFF_COST_PER_TECH_SHIFT = 450.0      # $ per added tech per 8 h shift (placeholder: put your loaded rate)
EXPEDITE_FEE_PER_ORDER = 150.0         # $ fixed fee per emergency order
VOLUME_GRID = [1.0, 1.1, 1.2]
MIN_GROUP_N = 30                       # a specimen group needs >= this many completions per replication to be constrained
MIN_N = 10
DEFAULT_MEDIA = ["Blood_Agar", "MacConkey", "CNA_Agar", "Chocolate_Agar", "ThayerMartin", "ChromeAgar"]

# (name, low, high, integer?)
SCENARIO_NUM = [("start_day", 15, 30, True), ("duration_days", 3, 21, True), ("severity", 0.3, 1.0, False)]
RESPONSE_NUM = ([(f"staff_{b}_{s}", 0, 2, True) for b in STAFF_BENCHES for s in STAFF_SHIFTS] +
                [("exp_on", 0, 1, True), ("exp_lead_days", 0.5, 2.0, False), ("exp_trigger_days", 1, 5, False), ("exp_qty_days", 2, 10, False),
                 ("res_days", 0, 4, False), ("res_trigger_days", 2, 6, False),
                 ("spare_on", 0, 1, True), ("spare_trigger_days", 1, 5, False)])
RESPONSE_NAMES = [n for n, *_ in RESPONSE_NUM]
NO_RESPONSE = {n: 0 for n in RESPONSE_NAMES} | {"exp_lead_days": 1.0, "exp_trigger_days": 3, "exp_qty_days": 5, "res_trigger_days": 4, "spare_trigger_days": 3}


# ----------------------------------------------------------------------------------------------------------
# point <-> overrides
# ----------------------------------------------------------------------------------------------------------
def staffing_cost(pt):
    n = sum(pt[f"staff_{b}_{s}"] for b in STAFF_BENCHES for s in STAFF_SHIFTS)
    return float(n * STAFF_COST_PER_TECH_SHIFT * pt["duration_days"])


def to_overrides(pt, disrupt=True):
    ops = []
    for b, key in STAFF_BENCHES.items():
        for s, shift in STAFF_SHIFTS.items():
            k = int(round(pt.get(f"staff_{b}_{s}", 0)))
            if k > 0:
                ops.append({"bench": key, "add": k, "shift_contains": shift})
    resp = {}
    if pt.get("exp_on", 0) >= 0.5:
        resp["expedite"] = dict(trigger_cover_days=pt["exp_trigger_days"], lead_days=pt["exp_lead_days"], qty_days=pt["exp_qty_days"],
                                cooldown_days=3, premium=1.5)
    if pt.get("res_days", 0) >= 0.25:
        resp["reserve"] = dict(trigger_cover_days=pt["res_trigger_days"], reserve_days=pt["res_days"], types=PRIORITY_TYPES)
    if pt.get("spare_on", 0) >= 0.5:
        resp["spare"] = dict(trigger_cover_days=pt["spare_trigger_days"], drop=SPARE_DROP)
    ov = {}
    if disrupt:
        ov["scenario_shortage_json"] = json.dumps({"disruptions": [dict(media=pt["media"], start_day=pt["start_day"],
                                                                         duration_days=pt["duration_days"], severity=pt["severity"])],
                                                   "response": resp})
    if ops:
        ov["scenario_staffing_json"] = json.dumps(ops)
    if abs(pt.get("volume", 1.0) - 1.0) > 1e-9:
        ov["scenario_volume_json"] = json.dumps({"global": float(pt["volume"])})
    return ov


def pt_key(pt):
    return json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in sorted(pt.items())})


def clean_point(pt):
    out = dict(pt)
    for n, lo, hi, isint in SCENARIO_NUM + RESPONSE_NUM:
        if n in out:
            out[n] = int(round(out[n])) if isint else float(round(out[n], 3))
    return out


def sobol_points(n, media, seed=0, volumes=VOLUME_GRID):
    from scipy.stats import qmc
    names = [x[0] for x in SCENARIO_NUM] + RESPONSE_NAMES
    u = qmc.Sobol(d=len(names) + 2, scramble=True, seed=seed).random(n)
    pts = []
    spec = {x[0]: x for x in SCENARIO_NUM + RESPONSE_NUM}
    for row in u:
        pt = {}
        for i, nm in enumerate(names):
            _, lo, hi, isint = spec[nm]
            pt[nm] = lo + row[i] * (hi - lo + (1 if isint else 0))
            if isint:
                pt[nm] = min(hi, int(np.floor(pt[nm])))
        pt["media"] = media[int(row[-2] * len(media)) % len(media)]
        pt["volume"] = volumes[int(row[-1] * len(volumes)) % len(volumes)]
        pts.append(clean_point(pt))
    return pts


# ----------------------------------------------------------------------------------------------------------
# running the simulator (real or mock) with a resumable cache
# ----------------------------------------------------------------------------------------------------------
def sim_metrics(df_pivot):
    from params_config import event_name as EV
    out = {}
    if df_pivot is None or df_pivot.empty:
        return {"unfinished_pct": float("nan"), "n_in_window": 0}
    d = df_pivot[df_pivot["In_Window"]]
    rej = [c for c in d.columns if str(c).startswith(EV.REJECTED_PREFIX)]
    rejm = d[rej].notna().any(axis=1) if rej else pd.Series(False, index=d.index)
    ok = d[~rejm]
    out["unfinished_pct"] = float(100 * ok["Completed_Minute"].isna().sum() / max(1, len(ok)))
    out["n_in_window"] = int(len(ok))
    ab = [c for c in ok.columns if str(c) in (EV.ABORTED, EV.MEDIA_ALLOCATION_FAILED) or str(c).startswith(EV.ABORTED)
          or "Media Allocation Failed" in str(c)]
    so = [c for c in ok.columns if "Stockout Delay Started" in str(c)]
    out["n_aborted_media"] = int(ok[ab].notna().any(axis=1).sum()) if ab else 0
    out["n_stockout_delayed"] = int(ok[so].notna().any(axis=1).sum()) if so else 0
    done = ok.dropna(subset=["Total_TAT_Hours"])
    for t, g in done.groupby("Type"):
        v = g["Total_TAT_Hours"].values
        out[f"n__{t}"] = int(len(v))
        if len(v) >= MIN_N:
            out[f"p95__{t}"] = float(np.percentile(v, 95))
    return out


def mock_run(ov, seed, sim_days=60):
    """Stand-in simulator for tests. Smooth, CRN-seeded, meaningless numbers."""
    import zlib
    sh = json.loads(ov.get("scenario_shortage_json") or "{}")
    ops = json.loads(ov.get("scenario_staffing_json") or "[]")
    vol = json.loads(ov.get("scenario_volume_json") or '{"global":1}')["global"]
    d = (sh.get("disruptions") or [None])[0]
    r = sh.get("response", {})
    rng = np.random.default_rng(zlib.crc32(str(seed).encode()))
    staff = sum(o["add"] for o in ops)
    m = {"n_in_window": int(9000 * vol)}
    sev = 0.0
    if d:
        sev = d["severity"] * min(1.0, d["duration_days"] / 10) * (1.3 if d["media"] == "Blood_Agar" else 0.8)
        if "expedite" in r:
            sev *= 0.35 + 0.1 * r["expedite"]["lead_days"] + 0.04 * max(0, 5 - r["expedite"]["qty_days"]) + 0.03 * (5 - r["expedite"]["trigger_cover_days"]) ** 2 / 4
        if "reserve" in r:
            sev *= 0.8
        if "spare" in r:
            sev *= 0.85
    base = 1 + 0.12 * (vol - 1) * 10
    m["n_aborted_media"] = int(max(0, 40 * sev ** 2 * (1 + rng.normal(0, .05))))
    m["n_stockout_delayed"] = int(max(0, 150 * sev * (1 + rng.normal(0, .05))))
    m["unfinished_pct"] = 0.3 * base + 2 * sev - 0.15 * staff * sev
    for t, b in {"BCx": 125, "Urine_Invasive": 60, "Wound": 215, "Respiratory": 120, "Stool": 80}.items():
        slow = base * (1 + 0.5 * sev * (1.5 if t in PRIORITY_TYPES and "reserve" not in r else 1) / (1 + 0.25 * staff))
        m[f"p95__{t}"] = b * slow * float(np.exp(np.random.default_rng(zlib.crc32(f"{seed}{t}".encode())).normal(0, 0.02)))
        m[f"n__{t}"] = 400
    ex = "expedite" in r and sev > 0
    m.update(n_spared=int(30 * sev) if "spare" in r else 0, n_emergency_orders=int(3 * sev) if ex else 0,
             emergency_units=300.0 * sev if ex else 0.0, emergency_cost=120.0 * sev if ex else 0.0, held_units=500.0 * sev)
    return m


def _worker(task):
    root = task["root"]
    for pth in (root, os.getcwd()):
        if pth not in sys.path:
            sys.path.insert(0, pth)
    t0 = time.time()
    try:
        if task["mock"]:
            m = mock_run(task["overrides"], task["seed"], task["sim_days"])
        else:
            from modules.simulation_d4 import run_simulation
            from modules import shortage_policy
            df, *_ = run_simulation(sim_days=task["sim_days"], seed=task["seed"], initial_conditions_json=task["ic"],
                                    parameter_overrides=task["overrides"] or None, set_progress=None, save_plots=False,
                                    export_diagnostics=False,
                                    log_filename=os.path.join(tempfile.gettempdir(), f"ml_pipe_{os.getpid()}.log"))
            m = sim_metrics(df)
            st = dict(shortage_policy.LAST_STATS)
            mc = st.pop("min_cover_days", {})
            m.update({k: float(v) for k, v in st.items()})
            m["min_cover_days"] = float(min(mc.values())) if mc else float("nan")
        m["_sec"] = time.time() - t0
        return {"id": task["id"], "ok": True, "metrics": m}
    except Exception as e:
        return {"id": task["id"], "ok": False, "error": f"{type(e).__name__}: {e}"}


class Runner:
    """Resumable runner. Cache key = (point key, seed); same seeds for every point (common random numbers)."""

    def __init__(self, out_dir, mock=False, sim_days=60, base_seed=1000, workers=None, ic=None, root="."):
        self.mock, self.sim_days, self.base_seed, self.ic = mock, sim_days, base_seed, ic
        self.root = str(Path(root).resolve())
        self.workers = workers or max(1, (os.cpu_count() or 2) - 1)
        self.path = Path(out_dir) / "runs.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.tag = f"{'mock' if mock else 'real'}:{sim_days:g}:{ic or 'none'}"
        self.cache = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                r = json.loads(line)
                if r["tag"] == self.tag:
                    self.cache[(r["key"], r["seed"])] = r["metrics"]

    def run(self, items, reps, label="runs"):
        """items: list of (point, disrupt_flag). Returns nothing; read results with frame()."""
        tasks = []
        for pt, dis in items:
            k = pt_key(pt) + ("" if dis else "|nodisrupt")
            for r in range(reps):
                seed = self.base_seed + r
                if (k, seed) not in self.cache:
                    tasks.append(dict(id=(k, seed), root=self.root, overrides=to_overrides(pt, dis), seed=seed, sim_days=self.sim_days,
                                      ic=self.ic, mock=self.mock))
        if not tasks:
            return
        print(f"  {label}: {len(tasks)} simulation runs on {self.workers} worker(s)", flush=True)
        t0, done, fails = time.time(), 0, []
        with open(self.path, "a") as fh:
            ex = ProcessPoolExecutor(max_workers=self.workers) if self.workers > 1 else None
            it = as_completed([ex.submit(_worker, t) for t in tasks]) if ex else (_worker(t) for t in tasks)
            for fut in it:
                r = fut.result() if ex else fut
                if not r["ok"]:
                    fails.append(r)
                    continue
                k, seed = r["id"]
                fh.write(json.dumps({"tag": self.tag, "key": k, "seed": seed, "metrics": r["metrics"]}) + "\n")
                fh.flush()
                self.cache[(k, seed)] = r["metrics"]
                done += 1
                if done % max(1, len(tasks) // 10) == 0 or done == len(tasks):
                    el = time.time() - t0
                    print(f"    {done}/{len(tasks)}  {el / 60:.1f} min elapsed, eta {el / done * (len(tasks) - done) / 60:.1f} min", flush=True)
            if ex:
                ex.shutdown()
        if fails:
            print(f"  WARNING: {len(fails)} runs failed; first: {fails[0]['error']}")

    def mean_metrics(self, pt, dis, reps):
        k = pt_key(pt) + ("" if dis else "|nodisrupt")
        ms = [self.cache[(k, self.base_seed + r)] for r in range(reps) if (k, self.base_seed + r) in self.cache]
        if not ms:
            return None
        df = pd.DataFrame(ms).drop(columns=["_sec"], errors="ignore")
        return df.mean(numeric_only=True).to_dict() | {"_n_reps": len(ms)}


def baseline_point(volume):
    return {"media": "none", "start_day": 20, "duration_days": 1, "severity": 0.0, "volume": volume, **NO_RESPONSE}


def baselines(runner, reps, volumes=VOLUME_GRID):
    runner.run([(baseline_point(v), False) for v in volumes], reps, "baselines (no disruption, no response)")
    return {v: runner.mean_metrics(baseline_point(v), False, reps) for v in volumes}


# ----------------------------------------------------------------------------------------------------------
# dataset + models
# ----------------------------------------------------------------------------------------------------------
def outcome_row(m, base):
    """Turn metrics of one point into model targets: counts, unfinished delta, % p95 change per specimen group."""
    out = {"n_aborted_media": m.get("n_aborted_media", 0), "n_stockout_delayed": m.get("n_stockout_delayed", 0),
           "d_unfinished_pct": m.get("unfinished_pct", np.nan) - base.get("unfinished_pct", np.nan),
           "emergency_cost": m.get("emergency_cost", 0.0) + EXPEDITE_FEE_PER_ORDER * m.get("n_emergency_orders", 0.0),
           "n_spared": m.get("n_spared", 0.0)}
    for k, v in base.items():
        if k.startswith("p95__") and base.get("n__" + k[5:], 0) >= MIN_GROUP_N and k in m:
            out["d95__" + k[5:]] = 100.0 * (m[k] - v) / v
    return out


def build_dataset(runner, points, reps, base):
    rows = []
    for pt in points:
        m = runner.mean_metrics(pt, True, reps)
        if m is None or m["_n_reps"] < reps:
            continue
        rows.append({**pt, **outcome_row(m, base[pt["volume"]]), "_staff_cost": staffing_cost(pt)})
    return pd.DataFrame(rows)


def feature_matrix(df, media_list):
    X = pd.DataFrame({n: df[n].astype(float) for n, *_ in SCENARIO_NUM + RESPONSE_NUM})
    X["volume"] = df["volume"].astype(float)
    for m in media_list:
        X["media=" + m] = (df["media"] == m).astype(float)
    X["staff_total"] = sum(df[f"staff_{b}_{s}"] for b in STAFF_BENCHES for s in STAFF_SHIFTS)
    return X


def train(df, out_dir, media_list, min_r2=0.5):
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import KFold, cross_val_predict
    X = feature_matrix(df, media_list)
    targets = [c for c in df.columns if c in ("n_aborted_media", "n_stockout_delayed", "d_unfinished_pct", "emergency_cost", "n_spared")
               or c.startswith("d95__")]
    Y = df[targets].astype(float).fillna(df[targets].astype(float).median())
    rf = RandomForestRegressor(n_estimators=400, min_samples_leaf=2, max_features=0.6, n_jobs=-1, random_state=0)
    cv = cross_val_predict(rf, X, Y, cv=KFold(5, shuffle=True, random_state=0))
    rep = []
    for i, t in enumerate(targets):
        y, yh = Y[t].values, cv[:, i]
        ss = ((y - y.mean()) ** 2).sum()
        r2 = 1 - ((y - yh) ** 2).sum() / ss if ss > 1e-12 else float("nan")
        rep.append(dict(target=t, cv_r2=r2, cv_mae=float(np.abs(y - yh).mean()), y_sd=float(y.std()), reliable=bool(r2 >= min_r2)))
    rf.fit(X, Y)
    import joblib
    out = Path(out_dir)
    joblib.dump({"model": rf, "targets": targets, "features": list(X.columns), "media": media_list, "cv": rep}, out / "shortage_model.joblib")
    pd.DataFrame(rep).to_csv(out / "model_cv.csv", index=False)
    return rf, targets, rep


def load_model(out_dir):
    import joblib
    return joblib.load(Path(out_dir) / "shortage_model.joblib")


def predict(bundle, df):
    """mean and per-tree sd for every target"""
    X = feature_matrix(df, bundle["media"])[bundle["features"]]
    trees = np.stack([t.predict(X.values) for t in bundle["model"].estimators_])
    return trees.mean(0), trees.std(0), trees


# ----------------------------------------------------------------------------------------------------------
# forecast / recommend
# ----------------------------------------------------------------------------------------------------------
def scenario_from_args(a):
    return {"media": a.media, "start_day": a.start_day, "duration_days": a.duration, "severity": a.severity, "volume": a.volume}


def cmd_forecast(a):
    b = load_model(a.out_dir)
    pt = {**scenario_from_args(a), **NO_RESPONSE}
    df = pd.DataFrame([clean_point(pt)])
    mu, sd, trees = predict(b, df)
    T = b["targets"]
    rel = {r["target"]: r["reliable"] for r in b["cv"]}
    print(f"\nForecast with NO response: {a.media} supply cut {a.severity:.0%} for {a.duration} days from day {a.start_day}, volume x{a.volume}")
    print(f"{'outcome':<26}{'predicted':>10}{'  +/-':>8}   reliable")
    for i, t in enumerate(T):
        if t in ("emergency_cost", "n_spared"):
            continue
        print(f"{t:<26}{mu[0, i]:>10.1f}{sd[0, i]:>8.1f}   {'yes' if rel[t] else 'NO (low CV R2)'}")
    if "n_aborted_media" in T:
        j = T.index("n_aborted_media")
        print(f"\nP(aborted > cap {a.abort_cap}) ~ {float((trees[:, 0, j] > a.abort_cap).mean()):.0%}  (share of trees above the cap; a rough risk indicator)")


def feasible_mask(mu, sd, T, args, groups):
    ok = np.ones(len(mu), bool)
    for g in groups:
        j = T.index("d95__" + g)
        ok &= (mu[:, j] + args.margin * sd[:, j]) <= args.tol_pct
    j = T.index("n_aborted_media")
    ok &= (mu[:, j] + args.margin * sd[:, j]) <= args.abort_cap
    return ok


def candidate_responses(n, seed):
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n):
        r = {}
        for nm, lo, hi, isint in RESPONSE_NUM:
            r[nm] = int(rng.integers(lo, hi + 1)) if isint else float(rng.uniform(lo, hi))
        if rng.random() < 0.3:                     # make 'off' common so cheap solutions get sampled
            for b in STAFF_BENCHES:
                for s in STAFF_SHIFTS:
                    if rng.random() < 0.6:
                        r[f"staff_{b}_{s}"] = 0
        rows.append(r)
    rows.append(dict(NO_RESPONSE))
    return rows


def cmd_recommend(a):
    b = load_model(a.out_dir)
    sc = scenario_from_args(a)
    cands = [clean_point({**sc, **r}) for r in candidate_responses(a.n_candidates, a.seed)]
    df = pd.DataFrame(cands)
    mu, sd, _ = predict(b, df)
    T = b["targets"]
    groups = [t[5:] for t in T if t.startswith("d95__")]
    groups = [g for g in groups if g not in a.exclude_groups]
    unreliable = [r["target"] for r in b["cv"] if not r["reliable"] and (r["target"].startswith("d95__") or r["target"] == "n_aborted_media")]
    if unreliable:
        print("WARNING: constraints use low-CV-R2 models (treat predictions as rough):", ", ".join(unreliable))
    ok = feasible_mask(mu, sd, T, a, groups)
    cost = df.apply(staffing_cost, axis=1).values + np.maximum(mu[:, T.index("emergency_cost")], 0)
    print(f"{ok.sum()} of {len(df)} candidate responses are predicted feasible (tol {a.tol_pct}% p95, abort cap {a.abort_cap}, margin {a.margin} sd)")
    if not ok.any():
        j = T.index("n_aborted_media")
        print("No candidate meets the limits within the lever ranges. Loosen --tol-pct/--abort-cap or widen the lever ranges.")
        order = np.argsort(mu[:, j])[:a.top]
    else:
        idx = np.where(ok)[0]
        order = idx[np.argsort(cost[idx])][:a.top]
    out_rows = []
    for i in order:
        r = {k: cands[i][k] for k in RESPONSE_NAMES}
        out_rows.append({**r, "pred_cost": cost[i], "pred_aborted": mu[i, T.index("n_aborted_media")],
                         **{f"pred_d95_{g}": mu[i, T.index('d95__' + g)] for g in groups}, "feasible_pred": bool(ok[i])})
    rec = pd.DataFrame(out_rows)
    rec.to_csv(Path(a.out_dir) / "recommendations_predicted.csv", index=False)
    if a.verify > 0:
        verify(a, sc, rec, groups)
    else:
        print(rec.to_string(index=False))


def describe(r):
    parts = []
    for b in STAFF_BENCHES:
        for s in STAFF_SHIFTS:
            if r[f"staff_{b}_{s}"] > 0:
                parts.append(f"+{int(r[f'staff_{b}_{s}'])} {b} {s}")
    if r["exp_on"] >= 0.5:
        parts.append(f"expedite (cover<{r['exp_trigger_days']:.1f}d, {r['exp_qty_days']:.1f}d of use, lead {r['exp_lead_days']:.1f}d)")
    if r["res_days"] >= 0.25:
        parts.append(f"reserve {r['res_days']:.1f}d of stock for invasive types (when cover<{r['res_trigger_days']:.1f}d)")
    if r["spare_on"] >= 0.5:
        parts.append(f"spare optional media (cover<{r['spare_trigger_days']:.1f}d)")
    return "; ".join(parts) or "no response"


def verify(a, sc, rec, groups):
    runner = Runner(a.out_dir, a.mock, a.sim_days, a.base_seed, a.workers, a.initial_conditions, a.root)
    base = baselines(runner, a.verify_reps)
    items = [({**sc, **{k: r[k] for k in RESPONSE_NAMES}}, True) for _, r in rec.head(a.verify).iterrows()]
    items = [(clean_point(p), d) for p, d in items]
    nores = clean_point({**sc, **NO_RESPONSE})
    runner.run([(nores, True)] + items, a.verify_reps, "verification runs")
    res = []
    for label, pt in [("NO RESPONSE", nores)] + [(f"option {i + 1}", p) for i, (p, _) in enumerate(items)]:
        m = runner.mean_metrics(pt, True, a.verify_reps)
        if m is None:
            continue
        o = outcome_row(m, base[pt["volume"]])
        worst = max([o.get("d95__" + g, 0) for g in groups] or [0])
        feas = worst <= a.tol_pct and o["n_aborted_media"] <= a.abort_cap
        res.append(dict(option=label, worst_group_p95_pct=worst, aborted=o["n_aborted_media"], stockout_delayed=o["n_stockout_delayed"],
                        cost=staffing_cost(pt) + o["emergency_cost"], verified_feasible=feas, plan=describe(pt)))
    r = pd.DataFrame(res)
    r.to_csv(Path(a.out_dir) / "recommendations_verified.csv", index=False)
    with pd.option_context("display.max_colwidth", 120, "display.width", 250):
        print(f"\nVerified in the simulator ({a.verify_reps} reps, same seeds as baseline):")
        print(r.to_string(index=False))
    f = r[(r.verified_feasible) & (r.option != "NO RESPONSE")]
    if len(f):
        best = f.sort_values("cost").iloc[0]
        print(f"\nRECOMMENDED: {best['option']} -> {best['plan']}\n  cost ~${best['cost']:,.0f}, worst-group p95 +{best['worst_group_p95_pct']:.1f}%, aborted {best['aborted']:.1f}")
    else:
        print("\nNo verified-feasible option. Increase --verify, loosen limits, or retrain with more data.")


def cmd_gen(a):
    runner = Runner(a.out_dir, a.mock, a.sim_days, a.base_seed, a.workers, a.initial_conditions, a.root)
    media = a.media_list or DEFAULT_MEDIA
    pts = sobol_points(a.n, media, a.seed)
    json.dump({"media": media, "n": a.n, "reps": a.reps}, open(Path(a.out_dir) / "doe.json", "w"))
    baselines(runner, a.reps)
    runner.run([(p, True) for p in pts], a.reps, f"training DOE ({a.n} points x {a.reps} reps)")
    print("done. next: train")


def cmd_train(a):
    meta = json.load(open(Path(a.out_dir) / "doe.json"))
    runner = Runner(a.out_dir, a.mock, a.sim_days, a.base_seed, a.workers, a.initial_conditions, a.root)
    base = baselines(runner, meta["reps"])
    pts = sobol_points(meta["n"], meta["media"], a.seed)
    df = build_dataset(runner, pts, meta["reps"], base)
    if len(df) < 30:
        sys.exit(f"only {len(df)} complete training points; run gen first")
    df.to_csv(Path(a.out_dir) / "training_table.csv", index=False)
    _, T, rep = train(df, a.out_dir, meta["media"], a.min_r2)
    print(f"trained on {len(df)} points; CV (5-fold) per target:")
    print(pd.DataFrame(rep).to_string(index=False))


def cmd_validate(a):
    """Fresh random points (different Sobol seed) the model never saw: predicted vs simulated."""
    meta = json.load(open(Path(a.out_dir) / "doe.json"))
    b = load_model(a.out_dir)
    runner = Runner(a.out_dir, a.mock, a.sim_days, a.base_seed, a.workers, a.initial_conditions, a.root)
    base = baselines(runner, meta["reps"])
    pts = sobol_points(a.n, meta["media"], seed=a.seed + 777)
    runner.run([(p, True) for p in pts], meta["reps"], "hold-out runs")
    df = build_dataset(runner, pts, meta["reps"], base)
    mu, _, _ = predict(b, df)
    rows = []
    for i, t in enumerate(b["targets"]):
        y = df[t].astype(float).values
        ss = ((y - y.mean()) ** 2).sum()
        rows.append(dict(target=t, holdout_r2=1 - ((y - mu[:, i]) ** 2).sum() / ss if ss > 1e-12 else np.nan, mae=float(np.abs(y - mu[:, i]).mean())))
    r = pd.DataFrame(rows)
    r.to_csv(Path(a.out_dir) / "holdout_validation.csv", index=False)
    print(r.to_string(index=False))


# ----------------------------------------------------------------------------------------------------------
# functions the dashboard calls in-process (no argparse)
# ----------------------------------------------------------------------------------------------------------
def train_from_dir(out_dir, sim_days=60, base_seed=1000, seed=0, min_r2=0.5, mock=False, ic=None, root=".", workers=1):
    meta = json.load(open(Path(out_dir) / "doe.json"))
    runner = Runner(out_dir, mock, sim_days, base_seed, workers, ic, root)
    base = baselines(runner, meta["reps"])
    pts = sobol_points(meta["n"], meta["media"], seed)
    df = build_dataset(runner, pts, meta["reps"], base)
    if len(df) < 30:
        raise ValueError(f"only {len(df)} complete training points in {out_dir}; run 'gen' first")
    df.to_csv(Path(out_dir) / "training_table.csv", index=False)
    _, T, rep = train(df, out_dir, meta["media"], min_r2)
    return len(df), pd.DataFrame(rep)


def forecast_df(bundle, sc, abort_cap=5.0):
    """No-response forecast for a scenario dict (media,start_day,duration_days,severity,volume)."""
    pt = clean_point({**sc, **NO_RESPONSE})
    mu, sd, trees = predict(bundle, pd.DataFrame([pt]))
    T, rel = bundle["targets"], {r["target"]: r["reliable"] for r in bundle["cv"]}
    rows = [dict(outcome=t, predicted=float(mu[0, i]), sd=float(sd[0, i]), reliable=bool(rel[t])) for i, t in enumerate(T)
            if t not in ("emergency_cost", "n_spared")]
    risk = float((trees[:, 0, T.index("n_aborted_media")] > abort_cap).mean()) if "n_aborted_media" in T else float("nan")
    return pd.DataFrame(rows), risk


def recommend_df(bundle, sc, tol_pct=10.0, abort_cap=5.0, margin=1.0, top=8, n_candidates=30000, seed=0, exclude_groups=()):
    """Predicted-only recommendation (cheapest predicted-feasible responses). Verification needs the simulator (CLI 'recommend')."""
    from types import SimpleNamespace
    cands = [clean_point({**sc, **r}) for r in candidate_responses(n_candidates, seed)]
    df = pd.DataFrame(cands)
    mu, sd, _ = predict(bundle, df)
    T = bundle["targets"]
    groups = [t[5:] for t in T if t.startswith("d95__") and t[5:] not in exclude_groups]
    ns = SimpleNamespace(tol_pct=tol_pct, abort_cap=abort_cap, margin=margin)
    ok = feasible_mask(mu, sd, T, ns, groups)
    cost = df.apply(staffing_cost, axis=1).values + np.maximum(mu[:, T.index("emergency_cost")], 0)
    if ok.any():
        idx = np.where(ok)[0]
        order = idx[np.argsort(cost[idx])][:top]
    else:
        order = np.argsort(mu[:, T.index("n_aborted_media")])[:top]
    rows = []
    for i in order:
        r = {k: cands[i][k] for k in RESPONSE_NAMES}
        rows.append({"plan": describe(r), "pred_cost": float(cost[i]), "pred_aborted": float(mu[i, T.index("n_aborted_media")]),
                     "pred_worst_p95_pct": float(max([mu[i, T.index("d95__" + g)] for g in groups] or [0])),
                     "feasible_pred": bool(ok[i]), "overrides_json": json.dumps(to_overrides(cands[i])), **r})
    return pd.DataFrame(rows), int(ok.sum()), len(df)


# ----------------------------------------------------------------------------------------------------------
# programmatic API (used by the dashboard; no printing, never starts simulations)
# ----------------------------------------------------------------------------------------------------------
_BUNDLE_CACHE = {}


def load_model_cached(out_dir):
    f = Path(out_dir) / "shortage_model.joblib"
    if not f.exists():
        raise FileNotFoundError(f"no trained model at {f}")
    key = (str(f.resolve()), f.stat().st_mtime)
    if key not in _BUNDLE_CACHE:
        _BUNDLE_CACHE.clear()
        _BUNDLE_CACHE[key] = load_model(out_dir)
    return _BUNDLE_CACHE[key]


def train_from_cache(out_dir, mock=False, sim_days=60, base_seed=1000, ic=None, root=".", min_r2=0.5, seed=0):
    """Train from runs already on disk (written by `gen`). Raises if baseline or training runs are missing; never runs the simulator."""
    meta = json.load(open(Path(out_dir) / "doe.json"))
    runner = Runner(out_dir, mock, sim_days, base_seed, 1, ic, root)
    base = {}
    for v in VOLUME_GRID:
        m = runner.mean_metrics(baseline_point(v), False, meta["reps"])
        if m is None or m["_n_reps"] < meta["reps"]:
            raise RuntimeError(f"baseline runs for volume x{v} are missing from {out_dir}/runs.jsonl: run  python run_ml_pipeline.py gen  first "
                               f"(or the sim-days / mock setting does not match how the data was generated)")
        base[v] = m
    pts = sobol_points(meta["n"], meta["media"], seed)
    df = build_dataset(runner, pts, meta["reps"], base)
    if len(df) < 30:
        raise RuntimeError(f"only {len(df)} complete training points in {out_dir}/runs.jsonl (need >= 30); run  gen  first")
    df.to_csv(Path(out_dir) / "training_table.csv", index=False)
    _, T, rep = train(df, out_dir, meta["media"], min_r2)
    _BUNDLE_CACHE.clear()
    return len(df), rep


def forecast_point(bundle, scenario, abort_cap=5.0):
    """No-response forecast for one scenario -> DataFrame(target, predicted, sd, reliable) and P(aborted > cap) from the tree spread."""
    pt = clean_point({**scenario, **NO_RESPONSE})
    mu, sd, trees = predict(bundle, pd.DataFrame([pt]))
    rel = {r["target"]: r["reliable"] for r in bundle["cv"]}
    T = bundle["targets"]
    out = pd.DataFrame({"target": T, "predicted": mu[0], "sd": sd[0], "reliable": [rel[t] for t in T]})
    p_exceed = float((trees[:, 0, T.index("n_aborted_media")] > abort_cap).mean()) if "n_aborted_media" in T else float("nan")
    return out, p_exceed


def recommend_predicted(bundle, scenario, tol_pct=10.0, abort_cap=5.0, margin=1.0, n_candidates=30000, top=8, exclude_groups=(), seed=0):
    """Cheapest responses whose PREDICTED outcome is inside the limits. Not verified in the simulator (use the CLI for that)."""
    from types import SimpleNamespace
    cands = [clean_point({**scenario, **r}) for r in candidate_responses(n_candidates, seed)]
    df = pd.DataFrame(cands)
    mu, sd, _ = predict(bundle, df)
    T = bundle["targets"]
    groups = [t[5:] for t in T if t.startswith("d95__") and t[5:] not in exclude_groups]
    ns = SimpleNamespace(tol_pct=tol_pct, abort_cap=abort_cap, margin=margin)
    ok = feasible_mask(mu, sd, T, ns, groups)
    cost = df.apply(staffing_cost, axis=1).values + np.maximum(mu[:, T.index("emergency_cost")], 0)
    if ok.any():
        idx = np.where(ok)[0]
        order = idx[np.argsort(cost[idx])][:top]
    else:
        order = np.argsort(mu[:, T.index("n_aborted_media")])[:top]
    rows = []
    for i in order:
        r = {k: cands[i][k] for k in RESPONSE_NAMES}
        rows.append({"plan": describe(r), "pred_cost": float(cost[i]), "pred_aborted": float(mu[i, T.index("n_aborted_media")]),
                     "pred_worst_p95_pct": float(max(mu[i, T.index("d95__" + g)] for g in groups)) if groups else float("nan"),
                     "feasible_pred": bool(ok[i]), "overrides_json": json.dumps(to_overrides(cands[i])), **r})
    unreliable = [r["target"] for r in bundle["cv"] if not r["reliable"] and (r["target"].startswith("d95__") or r["target"] == "n_aborted_media")]
    return pd.DataFrame(rows), int(ok.sum()), len(df), unreliable


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["gen", "train", "forecast", "recommend", "validate"])
    ap.add_argument("--out-dir", default="ml_out")
    ap.add_argument("--mock", action="store_true", help="use the stand-in simulator (pipeline test only)")
    ap.add_argument("--sim-days", type=float, default=60)
    ap.add_argument("--base-seed", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--initial-conditions", default=None)
    ap.add_argument("--root", default=".")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n", type=int, default=256, help="gen: Sobol points; validate: hold-out points")
    ap.add_argument("--reps", type=int, default=2, help="gen: replications per point")
    ap.add_argument("--media-list", nargs="*", default=None, help="gen: media that can be disrupted")
    ap.add_argument("--min-r2", type=float, default=0.5)
    ap.add_argument("--media", default="Blood_Agar")
    ap.add_argument("--start-day", type=int, default=20)
    ap.add_argument("--duration", type=int, default=10)
    ap.add_argument("--severity", type=float, default=0.8)
    ap.add_argument("--volume", type=float, default=1.0)
    ap.add_argument("--tol-pct", type=float, default=10.0, help="max p95 TAT increase vs no-disruption baseline, per group (%%)")
    ap.add_argument("--abort-cap", type=float, default=5.0, help="max specimens aborted for media per 60-day run")
    ap.add_argument("--margin", type=float, default=1.0, help="safety margin in model sd")
    ap.add_argument("--exclude-groups", nargs="*", default=[], help="specimen groups not constrained")
    ap.add_argument("--n-candidates", type=int, default=30000)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--verify", type=int, default=4, help="recommend: re-run this many finalists in the simulator (0 = skip)")
    ap.add_argument("--verify-reps", type=int, default=5)
    a = ap.parse_args(argv)
    Path(a.out_dir).mkdir(parents=True, exist_ok=True)
    {"gen": cmd_gen, "train": cmd_train, "forecast": cmd_forecast, "recommend": cmd_recommend, "validate": cmd_validate}[a.cmd](a)


if __name__ == "__main__":
    main()
