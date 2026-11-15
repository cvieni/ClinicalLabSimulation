#!/usr/bin/env python
"""Run the one-at-a-time sensitivity study (every run through run_montecarlo_and_plot.py, same seeds everywhere).

    python run_sensitivity.py --dry-run                      # list runs, check every override against params_d3, estimate time
    python run_sensitivity.py --tier 1 --iterations 10 --workers 8
    python run_sensitivity.py --only positive_specimen_rate,phoenix_run_time_hours
    python run_sensitivity.py --baseline-dir results_experiments/scn_baseline   # reuse a baseline made with the SAME code and seed

Output: results_experiments/sens/<param>__lo|hi/  (same layout as a scenario folder), sens/_baseline/, sens/manifest.csv
Resumable: finished folders are skipped; a folder whose settings changed is reported as STALE (rerun with --force).
Then:  python analyze_sensitivity.py
"""
import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import pandas as pd

from sensitivity_params import PARAMS


def jsonable(v):
    return list(v) if isinstance(v, tuple) else v


def same(a, b):
    try:
        return json.loads(json.dumps(jsonable(a))) == json.loads(json.dumps(jsonable(b)))
    except TypeError:
        return a == b


def clean(x, base):
    """Round a derived value to something readable and keep integers integers."""
    if isinstance(base, bool) or not isinstance(base, (int, float)):
        return x
    if isinstance(base, int):
        return int(round(x))
    return round(float(x), 4)


def levels(entry, p):
    """-> list of (level, {override: value}, display_value). Skips a level equal to the baseline."""
    name = entry["name"]
    base = getattr(p, name)
    out = []
    for lev in ("lo", "hi"):
        if "rel" in entry:
            f = entry["rel"]
            v = base * (1 - f) if lev == "lo" else base * (1 + f)
            if entry.get("prob"):
                v = min(max(v, 0.0), 1.0)
            v = clean(v, base)
            ov = {name: v}
        else:
            v = entry.get(lev)
            if v is None:
                continue
            ov = dict(v) if isinstance(v, dict) else {name: v}
            v = ov[name]
        if all(same(val, getattr(p, k, None)) for k, val in ov.items()):
            continue                                   # identical to baseline (e.g. a probability already at its cap)
        out.append((lev, {k: jsonable(val) for k, val in ov.items()}, jsonable(v)))
    return out


def preflight(plan, p):
    """Names must exist in params_d3 and keep their type; then the project's own validate_overrides."""
    problems = []
    for name, lev, ov, _ in plan:
        for k, v in ov.items():
            if not hasattr(p, k):
                problems.append(f"{name}/{lev}: '{k}' is not an attribute of params_d3"); continue
            b = getattr(p, k)
            if isinstance(b, (tuple, list)):
                if not isinstance(v, (tuple, list)):
                    problems.append(f"{name}/{lev}: baseline {b!r} is a sequence, override is {v!r}")
            elif isinstance(b, bool):
                if not isinstance(v, (bool, int)):
                    problems.append(f"{name}/{lev}: baseline is bool, override {v!r}")
            elif isinstance(b, (int, float)):
                if isinstance(v, (str, list, tuple)):
                    problems.append(f"{name}/{lev}: baseline {b!r} is numeric, override {v!r}")
            elif isinstance(b, str) and not isinstance(v, str):
                problems.append(f"{name}/{lev}: baseline is str, override {v!r}")
    try:
        from modules.param_overrides import validate_overrides
        for name, lev, ov, _ in plan:
            try:
                validate_overrides(ov)
            except Exception as e:
                problems.append(f"{name}/{lev}: project validate_overrides rejected {ov}: {e}")
    except Exception as e:
        print(f"  (could not import modules.param_overrides.validate_overrides: {type(e).__name__}; name/type checks only)")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iterations", type=int, default=10)
    ap.add_argument("--sim-days", type=float, default=60)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--tier", type=int, default=2, help="1 = core parameters only, 2 = everything (default)")
    ap.add_argument("--only", default=None, help="comma-separated parameter names")
    ap.add_argument("--out-dir", default="results_experiments/sens")
    ap.add_argument("--baseline-dir", default=None, help="reuse an existing baseline folder (same code, seed, sim-days; at least --iterations reps)")
    ap.add_argument("--mc-script", default="run_montecarlo_and_plot.py")
    ap.add_argument("--mc-args", default="", help='extra args for every run, e.g. "--initial-conditions none"')
    ap.add_argument("--minutes-per-rep", type=float, default=2.0, help="for the time estimate only")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    import params_config.params_d3 as p
    only = {x.strip() for x in a.only.split(",")} if a.only else None
    plan = []
    for e in PARAMS:
        if e["tier"] > a.tier or (only and e["name"] not in only):
            continue
        if not hasattr(p, e["name"]):
            print(f"  WARNING: {e['name']} is not in params_d3.py: skipped")
            continue
        for lev, ov, disp in levels(e, p):
            plan.append((e["name"], lev, ov, disp))
    if only and not plan:
        sys.exit(f"nothing matches --only {sorted(only)}")

    out = Path(a.out_dir)
    base_dir = Path(a.baseline_dir) if a.baseline_dir else out / "_baseline"
    n_runs = len(plan) + (0 if a.baseline_dir else 1)
    workers = a.workers or 4
    est_h = n_runs * math.ceil(a.iterations / workers) * a.minutes_per_rep / 60
    print(f"{len(plan)} sensitivity runs + baseline, {a.iterations} replications x {a.sim_days:g} days, seed {a.seed}; "
          f"about {est_h:.1f} h on {workers} workers at {a.minutes_per_rep:g} min per replication")
    bad = preflight(plan, p)
    if bad:
        print("\nPROBLEMS (fix sensitivity_params.py or params_d3.py):")
        for b in bad:
            print("  -", b)
        if not a.dry_run:
            sys.exit(1)
    for name, lev, ov, disp in plan:
        print(f"  {name:<42s} {lev}  baseline={jsonable(getattr(p, name))!r:<16} -> {ov}")
    if a.dry_run:
        return

    jobs = [("_baseline", "base", {}, None)] if not a.baseline_dir else []
    jobs += [(f"{n}__{lev}", lev, ov, n) for n, lev, ov, _ in plan]
    manifest, t_all = [], time.time()
    for k, (folder_name, lev, ov, pname) in enumerate(jobs, 1):
        folder = out / folder_name
        ovf = folder / "scenario_overrides.json"
        if (folder / "run_table.csv").exists() and not a.force:
            old = json.loads(ovf.read_text()) if ovf.exists() else {}
            if old != ov:
                print(f"[{k}/{len(jobs)}] {folder_name}: STALE (settings differ from the finished run); use --force to rerun")
            else:
                print(f"[{k}/{len(jobs)}] {folder_name}: finished, skipping")
        else:
            folder.mkdir(parents=True, exist_ok=True)
            cmd = [sys.executable, a.mc_script, "--iterations", str(a.iterations), "--sim-days", str(a.sim_days), "--seed", str(a.seed), "--out", str(folder)]
            if a.workers:
                cmd += ["--workers", str(a.workers)]
            if ov:
                ovf.write_text(json.dumps(ov, indent=2), encoding="utf-8")
                cmd += ["--overrides-file", str(ovf)]
            else:
                ovf.write_text("{}", encoding="utf-8")
            if a.mc_args:
                import shlex
                cmd += shlex.split(a.mc_args)
            print(f"\n[{k}/{len(jobs)}] {folder_name}  ({(time.time() - t_all) / 60:.0f} min elapsed)")
            r = subprocess.run(cmd)
            if r.returncode != 0:
                sys.exit(f"{folder_name} FAILED (exit {r.returncode}); fix and rerun: finished folders are skipped")
        manifest.append(dict(param=pname or "baseline", level=lev, overrides=json.dumps(ov), folder=str(folder)))
    if a.baseline_dir:
        manifest.append(dict(param="baseline", level="base", overrides="{}", folder=str(base_dir)))
    pd.DataFrame(manifest).to_csv(out / "manifest.csv", index=False)
    print(f"\nAll runs finished ({(time.time() - t_all) / 60:.0f} min). Next: python analyze_sensitivity.py --dir {out}")


if __name__ == "__main__":
    main()
