"""Load, summarise and compare finished simulation results (no Dash in here, so it can be tested and reused in scripts).

Two kinds of source are understood
  "scenario" : a run_montecarlo_and_plot.py / run_scenarios.py folder   <root>/scn_<name>/{run_table.csv, replications/specimens_###.csv.gz,
               replications/state_###.csv.gz, scenario_overrides.json}
  "mc_csv"   : a Monte Carlo tab file                                    <dir>/sim_<time>_<label>.csv (+ .json settings sidecar)

Both are reduced to the same small objects (per replication x specimen type p50 / p95 / counts, per replication run metrics,
bench utilisation by shift, a capped sample of individual TATs) and cached next to the data, so re-opening a source is instant.
"""
from __future__ import annotations

import glob
import hashlib
import json
import pickle
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

CACHE_NAME = ".explorer_cache.pkl"
CACHE_VERSION = 3
SAMPLE_PER_TYPE = 4000
SHIFTS = ["Day", "Evening", "Night"]
SHIFT_HOURS = {"Day": (7, 15), "Evening": (15, 23)}
BENCH_LABELS = {
    "tech_accession": "Accessioning", "tech_float_accession": "Float (accession/plating)", "tech_plating": "Plating",
    "tech_blood": "Blood culture bench", "tech_urine": "Urine bench", "tech_stool": "Stool bench",
    "tech_new": "New-plate bench", "tech_float_newroutine": "Float (new/routine)", "tech_routine": "Routine bench",
    "tech_supervisor": "Supervisor",
}
_SHIFT_WORDS = ("day", "evening", "night", "shift")
RUN_METRICS = ["n_in_window", "n_rejected", "n_aborted", "n_incomplete_in_window", "total_delays", "plating_delays", "total_specimens"]


# ----------------------------------------------------------------------------------------------------------------------
# discovery
# ----------------------------------------------------------------------------------------------------------------------
def discover(roots, max_depth=3):
    """Find every result set under the given folders. Returns a list of dicts sorted newest first."""
    found, seen = [], set()
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        base_depth = len(root.parts)
        for rt in list(root.rglob("run_table.csv")):
            d = rt.parent
            if len(d.parts) - base_depth > max_depth or d in seen:
                continue
            seen.add(d)
            reps = len(glob.glob(str(d / "replications" / "specimens_*.csv.gz")))
            label = d.name[4:] if d.name.startswith("scn_") else d.name
            found.append(dict(id="scenario|" + str(d), kind="scenario", label=label, path=str(d), mtime=rt.stat().st_mtime,
                              n_reps=reps, has_specimens=reps > 0))
        for f in root.glob("sim_*.csv"):
            try:
                n = sum(1 for _ in open(f, "rb")) - 1
            except OSError:
                n = 0
            found.append(dict(id="mc_csv|" + str(f), kind="mc_csv", label=re.sub(r"^sim_", "", f.stem), path=str(f),
                              mtime=f.stat().st_mtime, n_reps=max(n, 0), has_specimens=False))
    found.sort(key=lambda r: -r["mtime"])
    return found


def option_label(src):
    kind = "scenario" if src["kind"] == "scenario" else "MC tab"
    return f"[{kind}] {src['label']}  ({src['n_reps']} reps)"


def _signature(src):
    p = Path(src["path"])
    files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file() and not f.name.startswith(".explorer")]
    sig = [(f.name, f.stat().st_size, int(f.stat().st_mtime)) for f in sorted(files)]
    return hashlib.md5((str(CACHE_VERSION) + repr(sig)).encode()).hexdigest()


def _cache_path(src):
    p = Path(src["path"])
    return (p / CACHE_NAME) if p.is_dir() else p.with_name("." + p.stem + ".explorer.pkl")


# ----------------------------------------------------------------------------------------------------------------------
# reduction helpers
# ----------------------------------------------------------------------------------------------------------------------
def _shift_of_hour(h):
    h = np.asarray(h)
    return np.where((h >= SHIFT_HOURS["Day"][0]) & (h < SHIFT_HOURS["Day"][1]), "Day",
                    np.where((h >= SHIFT_HOURS["Evening"][0]) & (h < SHIFT_HOURS["Evening"][1]), "Evening", "Night"))


def _rep_id(path, fallback):
    m = re.findall(r"(\d+)", Path(path).name)
    return int(m[0]) if m else fallback


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_scenario(src, progress=None):
    d = Path(src["path"])
    rt = pd.read_csv(d / "run_table.csv")
    w0 = float(rt["window_start_min"].iloc[0]) if "window_start_min" in rt else 0.0
    w1 = float(rt["window_end_min"].iloc[0]) if "window_end_min" in rt else np.inf
    rng = np.random.default_rng(0)
    rows, samples, runrows = [], [], []
    spec_files = sorted(glob.glob(str(d / "replications" / "specimens_*.csv.gz")))
    for i, f in enumerate(spec_files):
        if progress:
            progress(f"{src['label']}: specimens {i + 1}/{len(spec_files)}")
        df = pd.read_csv(f, low_memory=False)
        rep = int(df["rep"].iloc[0]) if "rep" in df.columns and len(df) else _rep_id(f, i)
        inw = df["In_Window"].astype(bool) if "In_Window" in df else pd.Series(True, index=df.index)
        tat = pd.to_numeric(df["Total_TAT_Hours"], errors="coerce") if "Total_TAT_Hours" in df else pd.Series(np.nan, index=df.index)
        out = df["Outcome"].astype(str).str.lower() if "Outcome" in df else pd.Series("", index=df.index)
        win = df[inw].copy()
        win["tat"] = tat[inw]
        win["is_aborted"] = out[inw].str.contains("abort")
        win["is_rejected"] = out[inw].str.contains("reject")
        runrows.append(dict(rep=rep, n_in_window=int(inw.sum()), n_aborted=int(win["is_aborted"].sum()),
                            n_rejected=int(win["is_rejected"].sum()),
                            n_incomplete_in_window=int((win["tat"].isna() & ~win["is_aborted"] & ~win["is_rejected"]).sum())))
        done = win.dropna(subset=["tat"])
        for typ, g in done.groupby("Type"):
            v = g["tat"].to_numpy(float)
            row = dict(rep=rep, type=typ, p50=float(np.percentile(v, 50)), p95=float(np.percentile(v, 95)), mean=float(v.mean()), n=len(v))
            for sh in SHIFTS:
                vs = g.loc[g["Arrival_Shift"] == sh, "tat"].to_numpy(float) if "Arrival_Shift" in g else np.array([])
                row[f"p95_{sh}"] = float(np.percentile(vs, 95)) if len(vs) >= 5 else np.nan
            rows.append(row)
            if rep == (samples[0]["rep"] if samples else rep) or True:
                k = min(len(v), max(50, SAMPLE_PER_TYPE // max(len(spec_files), 1)))
                samples.append(dict(rep=rep, type=typ, tat=rng.choice(v, size=k, replace=False)))
    summary = pd.DataFrame(rows)
    runs = pd.DataFrame(runrows)
    # merge numeric columns of run_table (stockout delays etc.) by row order = replication order
    if len(rt) and len(runs):
        extra = rt.select_dtypes("number").drop(columns=[c for c in ("window_start_min", "window_end_min") if c in rt], errors="ignore")
        if "rep" in extra or "run_id" in extra:
            key = "rep" if "rep" in extra else "run_id"
            extra = extra.rename(columns={key: "rep"})
            runs = runs.merge(extra, on="rep", how="left", suffixes=("", "_rt"))
        elif len(extra) == len(runs):
            for c in extra.columns:
                if c not in runs:
                    runs[c] = extra[c].to_numpy()
    sample = (pd.concat([pd.DataFrame({"rep": s["rep"], "type": s["type"], "tat_h": s["tat"]}) for s in samples], ignore_index=True)
              if samples else pd.DataFrame(columns=["rep", "type", "tat_h"]))
    # utilisation from state files
    util_rows = []
    st_files = sorted(glob.glob(str(d / "replications" / "state_*.csv.gz")))
    for i, f in enumerate(st_files):
        if progress:
            progress(f"{src['label']}: state {i + 1}/{len(st_files)}")
        st = pd.read_csv(f, low_memory=False)
        rep = _rep_id(f, i)
        if "Day" in st:
            st = st[(st["Day"] >= w0 / 1440) & (st["Day"] < w1 / 1440)]
        if "Hour" not in st:
            continue
        st = st.assign(shift=_shift_of_hour((st["Hour"] % 24).astype(int)))
        for b, lab in BENCH_LABELS.items():
            ci, cc = f"Res_{b}_in_use", f"Res_{b}_capacity"
            if ci in st and cc in st:
                x = st[st[cc] > 0]
                for sh in SHIFTS:
                    xs = x[x["shift"] == sh]
                    if len(xs):
                        util_rows.append(dict(rep=rep, bench=lab, shift=sh, util_pct=float((100 * xs[ci] / xs[cc]).mean()),
                                              staff=float(xs[cc].mean())))
    settings = _read_json(d / "scenario_overrides.json")
    return dict(summary=summary, runs=runs, util=pd.DataFrame(util_rows), sample=sample, settings=settings, n_days=None)


def _load_mc_csv(src, progress=None):
    f = Path(src["path"])
    df = pd.read_csv(f)
    rep = df["run_id"].to_numpy() if "run_id" in df else np.arange(len(df))
    rows = []
    for metric in ("p50", "p95"):
        pre = f"tat_{metric}_"
        for c in df.columns:
            if c.startswith(pre) and not any(w in c[len(pre):].lower() for w in _SHIFT_WORDS) and c[len(pre):] != "overall":
                for r, v in zip(rep, pd.to_numeric(df[c], errors="coerce")):
                    rows.append(dict(rep=int(r), type=c[len(pre):], metric=metric, v=v))
    long = pd.DataFrame(rows)
    if long.empty:
        summary = pd.DataFrame(columns=["rep", "type", "p50", "p95"])
    else:
        summary = long.pivot_table(index=["rep", "type"], columns="metric", values="v").reset_index()
        summary.columns.name = None
    runs = pd.DataFrame({"rep": rep})
    for c in RUN_METRICS + ["seed"]:
        if c in df:
            runs[c] = df[c].to_numpy()
    for c in df.columns:
        if c.startswith(("consumed_", "stockout_")) and pd.api.types.is_numeric_dtype(df[c]):
            runs[c] = df[c].to_numpy()
    s = _read_json(f.with_suffix(".json"))
    settings = dict(s.get("parameter_overrides", {}) or {})
    for k in ("iterations", "sim_days", "seed_base"):
        if k in s:
            settings[f"[run] {k}"] = s[k]
    return dict(summary=summary, runs=runs, util=pd.DataFrame(), sample=pd.DataFrame(columns=["rep", "type", "tat_h"]), settings=settings,
                full_settings=s, n_days=None)


def load_source(src, use_cache=True, progress=None):
    cp = _cache_path(src)
    sig = _signature(src)
    if use_cache and cp.exists():
        try:
            obj = pickle.loads(cp.read_bytes())
            if obj.get("sig") == sig:
                return obj["data"]
        except Exception:
            pass
    data = _load_scenario(src, progress) if src["kind"] == "scenario" else _load_mc_csv(src, progress)
    data["src"] = {k: src[k] for k in ("id", "kind", "label", "path")}
    try:
        cp.write_bytes(pickle.dumps(dict(sig=sig, data=data)))
    except OSError:
        pass
    return data


# ----------------------------------------------------------------------------------------------------------------------
# comparison
# ----------------------------------------------------------------------------------------------------------------------
def mean_ci(x):
    x = np.asarray([v for v in x if np.isfinite(v)], float)
    if len(x) == 0:
        return np.nan, np.nan, 0
    if len(x) == 1:
        return float(x[0]), np.nan, 1
    return float(x.mean()), float(stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))), len(x)


def tat_table(datasets, metric="p95", types=None):
    """Long table: label, type, mean, ci, n_reps."""
    rows = []
    for lab, d in datasets.items():
        s = d["summary"]
        if s.empty or metric not in s:
            continue
        for typ, g in s.groupby("type"):
            if types and typ not in types:
                continue
            m, ci, n = mean_ci(g[metric])
            rows.append(dict(source=lab, type=typ, mean=m, ci=ci, n_reps=n))
    return pd.DataFrame(rows)


def paired_delta(datasets, baseline, metric="p95", types=None, pct=True):
    """% (or absolute) change of every source vs the baseline, paired by replication id (same seeds = common random numbers).
    Falls back to unpaired mean difference when the replication ids do not match."""
    base = datasets[baseline]["summary"]
    rows = []
    for lab, d in datasets.items():
        if lab == baseline or d["summary"].empty or metric not in d["summary"]:
            continue
        s = d["summary"]
        for typ in sorted(set(s["type"]) & set(base["type"])):
            if types and typ not in types:
                continue
            a = s[s["type"] == typ].set_index("rep")[metric]
            b = base[base["type"] == typ].set_index("rep")[metric]
            common = a.index.intersection(b.index)
            if len(common) >= 3:
                diff = (a[common] - b[common]) / (b[common] if pct else 1.0) * (100.0 if pct else 1.0)
                m, ci, n = mean_ci(diff)
                paired = True
            else:
                bm = b.mean()
                diff = (a - bm) / (bm if pct else 1.0) * (100.0 if pct else 1.0)
                m, ci, n = mean_ci(diff)
                paired = False
            rows.append(dict(source=lab, type=typ, delta=m, ci=ci, n_reps=n, paired=paired,
                             significant=bool(np.isfinite(ci) and abs(m) > ci)))
    return pd.DataFrame(rows)


def run_metric_table(datasets):
    rows = []
    for lab, d in datasets.items():
        r = d["runs"]
        row = dict(source=lab, n_reps=len(r))
        s = d["summary"]
        if not s.empty:
            for m in ("p50", "p95"):
                if m in s:
                    per_rep = s.groupby("rep")[m].mean()
                    row[f"mean_of_types_{m}_h"] = per_rep.mean()
        for c in ("n_in_window", "n_aborted", "n_rejected", "n_incomplete_in_window", "total_delays"):
            if c in r:
                row[c + "_mean"] = float(pd.to_numeric(r[c], errors="coerce").mean())
        if "n_incomplete_in_window" in r and "n_in_window" in r and r["n_in_window"].sum():
            row["unfinished_pct"] = 100.0 * r["n_incomplete_in_window"].sum() / r["n_in_window"].sum()
        if "total_delays" in r:
            row["stockout_risk_pct"] = 100.0 * (pd.to_numeric(r["total_delays"], errors="coerce") > 0).mean()
        rows.append(row)
    return pd.DataFrame(rows)


def util_delta(datasets, baseline):
    """Per scenario: scenario - baseline mean utilisation (percentage points), bench x shift, paired by replication when possible."""
    base = datasets[baseline]["util"]
    out = {}
    if base.empty:
        return out
    for lab, d in datasets.items():
        u = d["util"]
        if lab == baseline or u.empty:
            continue
        m = u.merge(base, on=["rep", "bench", "shift"], suffixes=("", "_b"))
        if m.empty:
            continue
        m["d"] = m["util_pct"] - m["util_pct_b"]
        out[lab] = m.groupby(["bench", "shift"])["d"].mean().unstack("shift")[[s for s in SHIFTS if s in m["shift"].unique()]]
    return out


def settings_diff(datasets, baseline):
    """Overrides that differ from the baseline, one column per source."""
    keys = []
    for d in datasets.values():
        for k in d["settings"]:
            if k not in keys:
                keys.append(k)
    rows = []
    for k in keys:
        row = {"setting": k}
        for lab, d in datasets.items():
            v = d["settings"].get(k, "-")
            row[lab] = v if isinstance(v, (str, int, float)) else json.dumps(v)
        rows.append(row)
    return pd.DataFrame(rows)
