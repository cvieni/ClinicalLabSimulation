#!/usr/bin/env python3
"""Policy optimizer constrained by the Monte Carlo simulation.

  python run_policy_opt.py estimate  --mock|(real)         time one replication, project the cost of a full run
  python run_policy_opt.py design    --n-design 120 --reps 3
  python run_policy_opt.py fit
  python run_policy_opt.py optimize  [--pareto]
  python run_policy_opt.py verify    --verify-reps 30
  python run_policy_opt.py all       --rounds 2          design -> fit -> optimize -> verify (-> refit ...) -> report

Add --mock to dry-run everything in seconds on a stand-in simulator (numbers are meaningless; it tests the machinery).
Edit policy_config.py first: levers, costs, targets.
"""
import argparse
import importlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import qmc

sys.path.insert(0, str(Path(__file__).resolve().parent))
import policy_config as cfg
from policy_opt.space import PolicySpace
from policy_opt.evaluate import Evaluator
from policy_opt.surrogate import Surrogate
from policy_opt import optimize as opt, report as rep


def load_baseline(mock):
    if mock:
        from policy_opt.mock_sim import MOCK_BASELINE
        return MOCK_BASELINE
    import params_config.params_d3 as p
    from params_config.staffing_config import SHIFT_STAFFING_PROFILE
    from params_config.config_d2 import Instrument_resources
    from params_config.media_config import MEDIA_CONFIG
    params = {d["name"]: getattr(p, d["name"]) for d in cfg.LEVERS if d["kind"] == "param"}
    return {"profile": SHIFT_STAFFING_PROFILE, "instruments": dict(Instrument_resources), "media": MEDIA_CONFIG, "params": params}


class Ctx:
    def __init__(self, a):
        self.a = a
        self.out = Path(a.out); self.out.mkdir(parents=True, exist_ok=True)
        self.space = PolicySpace(cfg, load_baseline(a.mock))
        self.ev = Evaluator(self.space, self.out, mock=a.mock, sim_days=a.sim_days, base_seed=a.seed, workers=a.workers,
                            initial_conditions=a.initial_conditions)
        self.xcols = [l.name for l in self.space.levers]
        self.contexts = cfg.CONTEXTS

    def baseline_policies(self):
        return [self.space.baseline_policy(c) for c in self.contexts]

    def baseline_row(self, tab):
        k = self.space.key(self.space.baseline_policy(self.contexts[0]))
        r = tab[tab["_key"] == k]
        if r.empty:
            sys.exit("baseline has not been simulated yet: run `design` first")
        return r.iloc[0]

    def targets(self, tab, tol):
        b = self.baseline_row(tab)
        tg = {}
        for c in tab.columns:
            if c.startswith("p95__") and not c.endswith("__se") and np.isfinite(b[c]):
                t = c[5:]
                tg[t] = cfg.TAT_TARGETS_HOURS.get(t, float(b[c]) * (1 + tol))
        return tg, max(1.0, float(b["unfinished_pct"]) + cfg.UNFINISHED_ABS_MARGIN)


def cmd_estimate(c):
    t0 = time.time()
    c.ev.workers = 1
    c.ev.run([c.space.baseline_policy(c.contexts[0])], 1, "timing one baseline replication")
    s = c.ev.seconds_per_run()
    w = c.a.workers or max(1, (__import__("os").cpu_count() or 2) - 1)
    d = c.a.n_design * c.a.reps + len(c.contexts) * c.a.baseline_reps
    v = (c.a.top_k + 1) * len(c.contexts) * c.a.verify_reps
    print(f"\none replication = {s:.1f} s. With {w} workers:")
    print(f"  design   {d:5d} runs  ~ {d * s / w / 60:7.1f} min")
    print(f"  verify   {v:5d} runs  ~ {v * s / w / 60:7.1f} min per round")
    print(f"  full `all --rounds {c.a.rounds}` ~ {(d + c.a.rounds * v) * s / w / 60:.0f} min")


def make_design(c, n, local_frac=0.4, seed=0):
    sp = c.space
    d = len(sp.levers)
    u = qmc.Sobol(d, scramble=True, seed=seed).random(n)
    for j, l in enumerate(sp.levers):
        if l.is_context:
            continue
        bu = (l.base - l.lo) / (l.hi - l.lo)
        k = int(n * local_frac)
        u[:k, j] = np.clip(bu + (u[:k, j] - 0.5) * 0.4, 0, 1)      # a share of points concentrated around today's policy
    pols = []
    for row in u:
        p = {}
        for j, l in enumerate(sp.levers):
            p[l.name] = float(l.snap(l.lo + row[j] * (l.hi - l.lo)))
        pols.append(p)
    return pols


def cmd_design(c):
    print(f"cost model (PLACEHOLDERS unless you edited policy_config.py): baseline daily cost = ${c.space.cost(c.space.baseline_policy()):,.0f}")
    c.ev.run(c.baseline_policies(), c.a.baseline_reps, "baseline")
    c.ev.run(make_design(c, c.a.n_design, seed=c.a.seed), c.a.reps, "design points")


def cmd_fit(c, quiet=False):
    tab = c.ev.table()
    sur = Surrogate(c.space.dnames, c.space.bounds + [(l.lo, l.hi) for l in c.space.context], kind=c.a.surrogate)
    sur.n_jobs = c.a.workers or -1
    print(f"fitting {c.a.surrogate} surrogate on {len(tab)} policies ...")
    sur.fit(tab, c.xcols)
    b = c.baseline_row(tab)
    cv = sur.cross_validate(5, refit=c.a.cv_refit, ref={t: float(b[t]) for t in sur.targets if t.startswith('p95__')})
    cv.to_csv(c.out / "surrogate_cv.csv", index=False, float_format="%.3f")
    print(cv.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    p95 = cv[cv.target.str.startswith("p95__")]
    worst = p95.mape_roi_pct.max()
    sur.save(c.out / "surrogate.joblib", {"n": len(tab)})
    if worst > c.a.gate_mape and not c.a.force:
        sys.exit(f"\nGATE: worst P95 cross-validated MAPE (policies within 1.5x baseline) is {worst:.1f}% (> {c.a.gate_mape}%). The surrogate is not trustworthy yet: "
                 f"add design points (`design --n-design N` again) or drop levers. Use --force to continue anyway.")
    return sur


def cmd_optimize(c, sur=None, extra_safety=0.0):
    tab = c.ev.table()
    sur = sur or Surrogate.load(c.out / "surrogate.joblib")
    tg, ul = c.targets(tab, c.a.tol)
    safety = c.a.safety + extra_safety
    print(f"constraints: P95 <= target x {1 - safety:.2f} for the search ({1.0:.2f} for verification), unfinished <= {ul:.2f}%, "
          f"contexts={c.contexts}")
    allres, pr0 = [], None
    for dz in (0.0, 1.0, 2.0):                       # lean / balanced / robust: more surrogate-uncertainty headroom each time
        pr = opt.Problem(c.space, sur, tg, ul, c.contexts, c.a.z + dz, cfg.EXCLUDE_TYPES, safety)
        pr0 = pr0 or pr
        r = opt.search(pr, n_runs=max(2, c.a.search_runs // 2), seed=c.a.seed + int(10 * dz))
        r["z_used"] = c.a.z + dz
        allres.append(r)
    res = pd.concat(allres, ignore_index=True)
    res["_k"] = [tuple(round(v, 6) for l, v in zip(c.space.decision, x) if l.kind != "param") for x in res["x"]]
    res = res.sort_values(["feasible", "cost"], ascending=[False, True]).drop_duplicates("_k").reset_index(drop=True)
    rows = []
    for _, r in res.head(c.a.top_k).iterrows():
        pol = c.space.policy_from_vec(r.x)
        rows.append(dict(cost=r.cost, saving_pct=100 * (1 - r.cost / pr0.base_cost), feasible=r.feasible, worst_pred_ratio=r.worst_ratio,
                         z_used=r.z_used, changes="; ".join(c.space.describe_changes(pol)), **pol))
    cand = pd.DataFrame(rows)
    cand.to_csv(c.out / "candidates.csv", index=False)
    print(cand[["cost", "saving_pct", "feasible", "z_used", "changes"]].to_string(index=False, max_colwidth=140))
    if not cand.feasible.any():
        print("WARNING: no candidate is predicted feasible - targets may be unreachable with these levers.")
    if c.a.pareto:
        tg0, _ = c.targets(tab, 0.0)          # Pareto tolerances are relative to today's simulated P95, not to --tol
        par = opt.pareto(c.space, sur, tg0, ul, c.contexts, [-0.10, -0.05, 0.0, 0.05, 0.10, 0.25], c.a.z, cfg.EXCLUDE_TYPES, c.a.seed, safety)
        par.to_csv(c.out / "pareto.csv", index=False)
        print("\nPareto (surrogate):\n" + par[["tol", "cost_ratio", "feasible", "worst_ratio"]].to_string(index=False))
    return cand, tg, ul


def cmd_verify(c, cand, tg, ul):
    tab0 = c.ev.table()
    pols = [{l.name: float(r[l.name]) for l in c.space.levers} for _, r in cand.iterrows()]
    allp = []
    for p0 in [c.space.baseline_policy()] + pols:
        for ctx in c.contexts:
            allp.append({**p0, **{k: v for k, v in ctx.items()}})
    c.ev.run(allp, c.a.verify_reps, f"verifying {len(pols)} candidate(s) + baseline x {len(c.contexts)} context(s)")
    tz = stats.t.ppf(0.975, c.a.verify_reps - 1)
    rows = []
    cons = [t for t in tg if t not in cfg.EXCLUDE_TYPES]
    for ci, pol in enumerate(pols):
        for ctx in c.contexts:
            pb = c.ev.replicate_frame({**c.space.baseline_policy(), **ctx})
            pn = c.ev.replicate_frame({**pol, **ctx})
            n = min(len(pb), len(pn))
            row = dict(candidate=ci, context=json.dumps(ctx), cost=c.space.cost(pol), n_reps=n)
            ok = True
            for t in cons:
                b, m = pb[f"p95__{t}"].values[:n], pn[f"p95__{t}"].values[:n]
                se = m.std(ddof=1) / np.sqrt(n)
                row[f"p95__{t}"] = m.mean(); row[f"p95__{t}__ci"] = tz * se
                row[f"d95__{t}"] = (m - b).mean()
                ok &= (m.mean() + tz * se) <= tg[t] * 1.0000001
            u = pn["unfinished_pct"].values[:n]
            row["unfinished_pct"] = u.mean(); row["unfinished_ok"] = u.mean() <= ul
            row["passes_all"] = bool(ok and row["unfinished_ok"])
            rows.append(row)
    ver = pd.DataFrame(rows)
    ver.to_csv(c.out / "verification.csv", index=False)
    summ = ver.groupby("candidate").agg(cost=("cost", "first"), passes=("passes_all", "all"))
    print("\nverified in the full simulator (95% CI upper bound vs target, all contexts):")
    print(summ.to_string())
    return ver, summ


def cmd_report(c, cand, ver, summ, tg, ul):
    sp = c.space
    ok = summ[summ.passes]
    best_i = int(ok.cost.idxmin()) if len(ok) else None
    base_cost = sp.cost(sp.baseline_policy())
    lines = ["# Policy recommendation", "", f"Source run: `{c.out}`  |  simulator: {'MOCK (not your lab)' if c.a.mock else 'real'}", ""]
    if best_i is None:
        lines += ["**No candidate passed verification at every context.** See `verification.csv`; relax targets "
                  "(`TARGET_TOLERANCE`), add levers, or rerun with more design points.", ""]
        (c.out / "recommendation.md").write_text("\n".join(lines))
        print("\nNo verified candidate. See recommendation.md"); return
    row = cand.iloc[best_i]
    pol = {l.name: float(row[l.name]) for l in sp.levers}
    st, other = rep.write_policy_files(sp, pol, c.out, base_cost, sp.cost(pol))
    v0 = ver[(ver.candidate == best_i) & (ver.context == json.dumps(c.contexts[0]))].iloc[0]
    vt = []
    for t in [t for t in tg if t not in cfg.EXCLUDE_TYPES]:
        b = c.ev.replicate_frame({**sp.baseline_policy(), **c.contexts[0]})[f"p95__{t}"]
        vt.append(dict(type=t, base_p95=b.mean(), base_ci=stats.t.ppf(.975, len(b) - 1) * b.std(ddof=1) / np.sqrt(len(b)),
                       new_p95=v0[f"p95__{t}"], new_ci=v0[f"p95__{t}__ci"], target=tg[t]))
    vt = pd.DataFrame(vt); vt.to_csv(c.out / "recommended_policy_verified_tat.csv", index=False, float_format="%.2f")
    rep.fig_verification(vt.rename(columns={}), {r.type: r.target for r in vt.itertuples()}, c.out)
    if (c.out / "pareto.csv").exists():
        rep.fig_pareto(pd.read_csv(c.out / "pareto.csv"), c.out)
    changed = st[st.change != 0]
    lines += [f"## Recommended policy (verified, {c.a.verify_reps} replications, contexts {c.contexts})", "",
              f"Daily cost {row.cost:,.0f} vs {base_cost:,.0f} today ({row.saving_pct:+.1f}% saving; cost model in `policy_config.py` - "
              f"check it is YOUR numbers).", "", "### Staffing changes (applied to weekday and weekend)", "",
              changed.to_markdown(index=False) if len(changed) else "_no staffing changes_", "", "### Other levers", "",
              other[other.recommended != other.baseline].to_markdown(index=False) if (other.recommended != other.baseline).any() else "_none_", "",
              "### Verified P95 (today's volume)", "", vt.round(1).to_markdown(index=False), "",
              "Replay it yourself: `python run_montecarlo_and_plot.py --overrides-file " + str(c.out / "best_policy_overrides.json") + " ...`", "",
              "## How far to trust this", "",
              "- Targets are 'baseline P95 x (1 + tolerance)' unless you set explicit hours; the baseline is the *simulated* current lab, "
              "so it is only as good as the 2025 calibration.",
              "- Every number above for the recommended policy comes from the full Monte Carlo, not the surrogate.",
              "- Changes are tested only inside the ranges listed in `policy_config.py`; the sim does not model hiring/training lag, "
              "sick calls, or skill mix, so treat the staffing table as a pilot proposal."]
    (c.out / "recommendation.md").write_text("\n".join(lines))
    print(f"\nRECOMMENDED (candidate {best_i}): saving {row.saving_pct:.1f}%  ->  {c.out / 'recommendation.md'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["estimate", "design", "fit", "optimize", "verify", "all"])
    ap.add_argument("--out", default="policy_opt_runs/run1")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--sim-days", type=float, default=60)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--initial-conditions", default=None)
    ap.add_argument("--n-design", type=int, default=120)
    ap.add_argument("--reps", type=int, default=3, help="replications per design point")
    ap.add_argument("--baseline-reps", type=int, default=10)
    ap.add_argument("--verify-reps", type=int, default=30)
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--surrogate", choices=["gp", "gp-shared", "rf"], default="gp")
    ap.add_argument("--cv-refit", action="store_true")
    ap.add_argument("--gate-mape", type=float, default=15.0, help="refuse to optimize if cross-validated P95 MAPE (near-baseline policies) exceeds this (%%)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--levers", default=None, help="comma-separated lever kinds to optimise, e.g. media  (kinds: staff, media, instrument, param); volume context is always kept")
    ap.add_argument("--tol", type=float, default=cfg.TARGET_TOLERANCE)
    ap.add_argument("--z", type=float, default=1.0, help="optimism guard: constraints use prediction + z x surrogate std")
    ap.add_argument("--safety", type=float, default=0.03, help="search aims this fraction inside each P95 target (verification uses the real target)")
    ap.add_argument("--search-runs", type=int, default=6)
    ap.add_argument("--pareto", action="store_true")
    a = ap.parse_args()
    if a.levers:
        keep = set(a.levers.split(",")) | {"context"}
        cfg.LEVERS = [d for d in cfg.LEVERS if d["kind"] in keep]
        print(f"levers: {sorted(keep - {'context'})}  ({len(cfg.LEVERS)} decision variables incl. context)")
    c = Ctx(a)
    if a.cmd == "estimate":
        return cmd_estimate(c)
    if a.cmd == "design":
        return cmd_design(c)
    if a.cmd == "fit":
        return cmd_fit(c)
    if a.cmd == "optimize":
        return cmd_optimize(c)
    if a.cmd == "verify":
        cand, tg, ul = cmd_optimize(c)
        return cmd_verify(c, cand, tg, ul)
    cmd_design(c)
    for r in range(a.rounds):
        print(f"\n===== round {r + 1}/{a.rounds} =====")
        sur = cmd_fit(c)
        cand, tg, ul = cmd_optimize(c, sur, extra_safety=0.03 * r)     # each failed round aims further inside the targets
        ver, summ = cmd_verify(c, cand, tg, ul)
        if summ.passes.any() and r > 0:
            break
    cmd_report(c, cand, ver, summ, tg, ul)


if __name__ == "__main__":
    main()
