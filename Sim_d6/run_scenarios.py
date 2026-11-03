#!/usr/bin/env python3
"""Run the baseline + what-if scenarios through run_montecarlo_and_plot.py (same seeds in every scenario).

    python run_scenarios.py --iterations 30 --sim-days 60 --seed 42
    python run_scenarios.py --only baseline,no_float          # subset
    python run_scenarios.py --force                           # rerun even if the folder already has results

Each scenario -> results_experiments/scn_<name>/  (resumable: finished folders are skipped).
Finishes by printing the make_manuscript_figures_micro.py command that uses all of them.
Edit SCENARIOS below to add more; staffing ops are described in modules/scenario_staffing.py.
"""
import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

SCENARIOS = {
    "baseline": {},
    # remove BOTH float techs (accession/plating float and new/routine float) in every shift
    "no_float": {"staffing": [{"bench": "tech_float_accession", "set": 0},
                              {"bench": "tech_float_newroutine", "set": 0}]},
    # one extra routine-bench tech on the evening shift (weekday and weekend)
    "evening_routine_plus1": {"staffing": [{"bench": "tech_routine", "add": 1, "shift_contains": "Evening"}]},
    # new stool biochemical test: stool biochemical time doubled
    "stool_biochem_x2": {"overrides": {"stool_biochem_time_multiplier": 2.0}},
}

ap = argparse.ArgumentParser()
ap.add_argument("--iterations", type=int, default=30)
ap.add_argument("--sim-days", type=float, default=60)
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--workers", type=int, default=None)
ap.add_argument("--only", default=None, help="comma-separated scenario names")
ap.add_argument("--force", action="store_true")
ap.add_argument("--results-dir", default="results_experiments")
ap.add_argument("--mc-script", default="run_montecarlo_and_plot.py")
ap.add_argument("--mc-args", default="", help='extra args passed through, e.g. "--initial-conditions none"')
a = ap.parse_args()

names = [n.strip() for n in a.only.split(",")] if a.only else list(SCENARIOS)
unknown = [n for n in names if n not in SCENARIOS]
if unknown:
    sys.exit(f"unknown scenario(s): {unknown}; available: {list(SCENARIOS)}")

done = {}
for n in names:
    cfg = SCENARIOS[n]
    out = Path(a.results_dir) / f"scn_{n}"
    done[n] = out
    if (out / "run_table.csv").exists() and not a.force:
        print(f"[{n}] already finished -> skipping ({out})")
        continue
    ov = dict(cfg.get("overrides", {}))
    if cfg.get("staffing"):
        ov["scenario_staffing_json"] = json.dumps(cfg["staffing"])
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, a.mc_script, "--iterations", str(a.iterations), "--sim-days", str(a.sim_days),
           "--seed", str(a.seed), "--out", str(out)]
    if a.workers:
        cmd += ["--workers", str(a.workers)]
    if ov:
        f = out / "scenario_overrides.json"
        f.write_text(json.dumps(ov, indent=2), encoding="utf-8")
        cmd += ["--overrides-file", str(f)]
    cmd += shlex.split(a.mc_args)
    print(f"\n[{n}] {' '.join(cmd)}")
    t0 = time.time()
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(f"[{n}] FAILED (exit {r.returncode}); fix and rerun - finished scenarios are skipped")
    print(f"[{n}] done in {(time.time() - t0) / 60:.1f} min")

(Path(a.results_dir) / "scenarios_manifest.json").write_text(
    json.dumps({n: {"folder": str(p), **SCENARIOS[n]} for n, p in done.items()}, indent=2), encoding="utf-8")
print("\nAll scenarios finished. Figures:\n")
print("python make_manuscript_figures_micro.py --mc-dir " + str(done.get("baseline", next(iter(done.values())))) +
      " --obs-2025 <LIS 2025 files> " + " ".join(f"--scenario {n}={p}" for n, p in done.items()))
