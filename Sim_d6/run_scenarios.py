#!/usr/bin/env python3
"""Run the baseline + what-if scenarios through run_montecarlo_and_plot.py (same seeds in every scenario).

    python run_scenarios.py --iterations 30 --sim-days 60 --seed 42
    python run_scenarios.py --only baseline,no_float          # subset
    python run_scenarios.py --force                           # rerun even if the folder already has results

Each scenario -> results_experiments/scn_<name>/  (resumable: finished folders are skipped).
Finishes by printing the make_manuscript_figures_micro.py command that uses all of them.
Define scenarios in scenarios_def.py (helpers: volume_x, volume_add, volume_all, staff_add, staff_set, instrument, param,
sweep_volume, combine) or ad hoc with --quick.
"""
import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenarios_def as sd
SCENARIOS = sd.SCENARIOS


def parse_quick(spec):
    """--quick "name=op;op"   ops: volume_x:BCx:2 | volume_add:BCx:2000 | volume_all:1.5 | staff_add:tech_routine:1[:Evening]
    | staff_set:tech_float_accession:0[:shift] | media_x:1.5[:Blood_Agar] | instrument:bc_instrument:864 | param:name:value"""
    name, ops = spec.split("=", 1)
    parts = []
    for op in ops.split(";"):
        k, *v = [x.strip() for x in op.split(":")]
        if k == "param":
            parts.append(sd.param(**{v[0]: float(v[1]) if v[1].replace(".", "", 1).lstrip("-").isdigit() else v[1]}))
        elif k in ("volume_x", "volume_add"):
            parts.append(getattr(sd, k)(v[0], float(v[1])))
        elif k == "volume_all":
            parts.append(sd.volume_all(float(v[0])))
        elif k in ("staff_add", "staff_set"):
            parts.append(getattr(sd, k)(v[0], int(v[1]), v[2] if len(v) > 2 else None))
        elif k == "media_x":
            parts.append(sd.media_x(float(v[0]), v[1] if len(v) > 1 and v[1] else None))
        elif k == "instrument":
            parts.append(sd.instrument(v[0], int(v[1])))
        else:
            raise SystemExit(f"unknown quick op '{k}'")
    return name.strip(), sd.combine(*parts)


ap = argparse.ArgumentParser()
ap.add_argument("--iterations", type=int, default=30)
ap.add_argument("--sim-days", type=float, default=60)
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--workers", type=int, default=None)
ap.add_argument("--quick", action="append", default=[], help='one-off scenario, e.g. --quick "bcx_plus2000=volume_add:BCx:2000;instrument:bc_instrument:864"')
ap.add_argument("--only", default=None, help="comma-separated scenario names")
ap.add_argument("--force", action="store_true")
ap.add_argument("--results-dir", default="results_experiments")
ap.add_argument("--mc-script", default="run_montecarlo_and_plot.py")
ap.add_argument("--mc-args", default="", help='extra args passed through, e.g. "--initial-conditions none"')
a = ap.parse_args()

for q in a.quick:
    n_, c_ = parse_quick(q)
    SCENARIOS[n_] = c_

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
    v = cfg.get("volume", {})
    if v.get("global", 1.0) != 1.0 or v.get("multipliers") or v.get("add_per_day"):
        ov["scenario_volume_json"] = json.dumps(v)
    m = cfg.get("media", {})
    if m.get("global", 1.0) != 1.0 or m.get("per_media") or "lead_time_days" in m:
        ov["scenario_media_json"] = json.dumps(m)
    if cfg.get("instruments"):
        ov["scenario_instrument_json"] = json.dumps(cfg["instruments"])
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
