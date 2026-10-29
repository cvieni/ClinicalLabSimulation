"""Where does the accession backlog come from? Three independent checks.

  python accession_diagnostics.py capacity
      Config only (no simulation). Offered load vs staffed capacity at accession, by hour of day,
      using the touch times, daily volumes, hourly arrival weights and staffing profile in your files.
      If daily utilisation (rho) is > 1 the queue grows forever no matter what else is right.

  python accession_diagnostics.py run --sim-days 10 --seed 1 [--initial-conditions PATH]
      Runs ONE short replication and prints (a) the stage funnel (how many specimens reached each
      stage and where they stop), (b) accession-store wait by day, (c) arrivals/day per type vs
      daily_volume_mean, (d) how many specimens were pre-loaded at t=0.
      Run it twice, with and without --initial-conditions, to see whether a pre-loaded backlog is the cause.

  In code:  from accession_diagnostics import run_check;  run_check(df_pivot, SPECIMEN_TYPES)
"""
from __future__ import annotations

import argparse
import re

import numpy as np
import pandas as pd

IN_STORE = "1c. Waiting in Accession Store"
TOUCH_START = "1d. Accessioning Started (Tech Touch)"
TOUCH_DONE = "1d. Accessioning Completed"


# ==================================================================================
# 1. Offered load vs capacity (config only)
# ==================================================================================
def _weights(w) -> np.ndarray:
    if isinstance(w, dict):
        w = [w[k] for k in sorted(w, key=lambda x: int(x))]
    w = np.asarray(w, dtype=float)
    if w.size != 24:
        raise ValueError(f"hourly_arrival_weights must have 24 entries, got {w.size}")
    return w / w.sum()


def capacity_check(spec_types: dict, staffing_profile: dict, get_shift_cfg, sim_start_weekday: int = 0,
                   target_rho: float = 0.85) -> pd.DataFrame:
    """Hourly offered accession load (tech-minutes) vs staffed capacity, weekday and weekend.

    Demand per type = daily_volume_mean x mean(accession_touch_time_min, _max) minutes (STAT
    variants and pre-accession hold timing ignored; the hold only delays arrival at the store).
    Capacity = techs on shift x 60 min. Accession workers do not use the tech_accession resource, they
    are gated by `worker_id <= tech_accession` of the current shift, so this is the true ceiling.
    """
    rows = []
    for t, cfg in spec_types.items():
        vol = cfg.get("daily_volume_mean")
        lo, hi = cfg.get("accession_touch_time_min"), cfg.get("accession_touch_time_max")
        if vol is None or lo is None or hi is None:
            print(f"  skipping {t}: missing daily_volume_mean / accession_touch_time_*")
            continue
        rows.append((t, float(vol), (float(lo) + float(hi)) / 2.0, cfg["hourly_arrival_weights"]))

    print(f"{'type':<20}{'vol/day':>10}{'mean touch (min)':>18}{'tech-min/day':>14}")
    for t, vol, mt, _ in rows:
        print(f"{t:<20}{vol:>10,.0f}{mt:>18.2f}{vol * mt:>14,.0f}")
    total_vol = sum(r[1] for r in rows)
    print(f"{'TOTAL':<20}{total_vol:>10,.0f}{'':>18}{sum(r[1] * r[2] for r in rows):>14,.0f}\n")

    out = []
    weekend_day = (5 - sim_start_weekday) % 7
    for label, day_idx, key in (("weekday", 0, "weekday"), ("weekend", weekend_day, "weekend")):
        for h in range(24):
            demand = sum(vol * _weights(w[key])[h] * mt for _, vol, mt, w in rows)
            cfg = get_shift_cfg(day_idx * 1440.0 + h * 60.0, staffing_profile) or {}
            techs = int(cfg.get("tech_accession", 0))
            out.append(dict(daytype=label, hour=h, demand_tech_min=demand, techs=techs,
                            rho=(demand / (techs * 60.0)) if techs else np.inf))
    df = pd.DataFrame(out)

    for label, g in df.groupby("daytype"):
        cap = g["techs"].sum() * 60.0
        dem = g["demand_tech_min"].sum()
        print(f"[{label}] demand {dem:,.0f} tech-min/day vs staffed capacity {cap:,.0f}  -> daily rho = "
              f"{dem / cap if cap else np.inf:.2f}   (peak-hour rho = {g['rho'].replace(np.inf, np.nan).max():.2f})")
        over = g[g["rho"] > target_rho]
        if len(over):
            print(f"   hours above rho {target_rho}: " + ", ".join(
                f"{int(r.hour):02d}h ({'no techs' if r.techs == 0 else f'{r.rho:.2f}'})" for r in over.itertuples()))
    print("\nRule of thumb: daily rho >= 1 => backlog grows without bound (your 40-day symptom). "
          "rho ~0.6-0.85 => queues form at peaks but drain.")
    return df


# ==================================================================================
# 2. What a run actually did
# ==================================================================================
def _stage_cols(df_pivot: pd.DataFrame):
    meta = {"Specimen_ID", "Type", "Arrival_Minute", "Completed_Minute", "Total_TAT_Hours", "Wait_For_Plating_Mins",
            "Incubation_Hours", "Arrival_Shift", "Outcome", "In_Window"}
    return [c for c in df_pivot.columns if c not in meta and df_pivot[c].dtype.kind in "fi"]


def run_check(df_pivot: pd.DataFrame, spec_types: dict | None = None) -> None:
    df = df_pivot
    n = len(df)
    print(f"\n=== Stage funnel ({n:,} specimens) - where do they stop? ===")
    def order(c):
        # "1.", "1b.", "1c.", "1d.", "2A.", "10." sort by their numeric/alpha prefix, not by median
        # time (stuck specimens skew medians). Unnumbered stages go last, by median time.
        m = re.match(r"(\d+)([A-Za-z]*)", str(c))
        return (0, int(m.group(1)), m.group(2).lower(), str(c)) if m else (1, 0, "", str(c))

    rows = []
    for c in _stage_cols(df):
        v = df[c].dropna()
        if len(v):
            rows.append((order(c), c, len(v)))
    prev = None
    for _, c, k in sorted(rows, key=lambda r: r[0]):
        flag = ""
        if prev and k < 0.5 * prev:
            flag = "   <-- count drops by >50% here"
        print(f"  {k:>8,}  {c}{flag}")
        prev = k
    if not any("10. Completed" in c for c in df.columns):
        print("  NOTE: no '10. Completed' stage was ever logged.")
    comp = df["Completed_Minute"].notna().sum() if "Completed_Minute" in df else 0
    print(f"  completed specimens: {comp:,} of {n:,}")

    print("\n=== Accession store wait (enter store -> tech starts), by day of entry ===")
    if IN_STORE in df and TOUCH_START in df:
        d = df.dropna(subset=[IN_STORE]).copy()
        d["wait_min"] = d[TOUCH_START] - d[IN_STORE]
        d["day"] = (d[IN_STORE] // 1440).astype(int)
        g = d.groupby("day")
        tab = pd.DataFrame({
            "entered": g.size(),
            "started": g["wait_min"].count(),
            "median_wait_min": g["wait_min"].median(),
            "p95_wait_min": g["wait_min"].quantile(0.95),
        })
        tab["never_started"] = tab["entered"] - tab["started"]
        print(tab.round(1).to_string())
        print("  A healthy lab: wait is minutes and 'never_started' ~ 0. Wait climbing day over day = capacity < load.")
    else:
        print("  stage columns not found; expected", IN_STORE, "/", TOUCH_START)

    print("\n=== Pre-loaded at t=0 (initial conditions) ===")
    init_cols = [c for c in df.columns if "initial" in str(c).lower()]
    pre = int((df["Arrival_Minute"] <= 0).sum()) if "Arrival_Minute" in df else 0
    print(f"  columns mentioning 'initial': {init_cols}; specimens with arrival <= minute 0: {pre:,}")

    if spec_types and "Arrival_Minute" in df:
        print("\n=== Arrivals per day vs daily_volume_mean (excluding minute-0 pre-loads) ===")
        d = df[df["Arrival_Minute"] > 0].copy()
        d["day"] = (d["Arrival_Minute"] // 1440).astype(int)
        days = max(d["day"].nunique() - 1, 1)             # drop the partial last day
        per_day = d[d["day"] < d["day"].max()].groupby("Type").size() / days
        print(f"  {'type':<20}{'sim arrivals/day':>18}{'config daily_volume_mean':>26}{'ratio':>8}")
        for t, cfg in spec_types.items():
            vol = cfg.get("daily_volume_mean")
            sim = float(per_day.get(t, 0.0))
            print(f"  {t:<20}{sim:>18,.0f}{(vol if vol is not None else float('nan')):>26,.0f}"
                  f"{(sim / vol if vol else float('nan')):>8.2f}")
        print("  ratio far from 1 => the generator is not producing what daily_volume_mean says "
              "(units / weights normalisation in specimen_generator).")


# ==================================================================================
# CLI
# ==================================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("capacity")
    r = sub.add_parser("run")
    r.add_argument("--sim-days", type=float, default=10)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--initial-conditions", type=str, default=None)
    r.add_argument("--overrides", type=str, default=None, help="JSON dict of parameter overrides")
    a = ap.parse_args()

    from params_config.specimen_config_d2 import SPECIMEN_TYPES

    if a.cmd == "capacity":
        import params_config.params_d3 as p
        from params_config.staffing_config import SHIFT_STAFFING_PROFILE
        from modules.shift_manager_d2 import get_current_shift_config
        capacity_check(SPECIMEN_TYPES, SHIFT_STAFFING_PROFILE, get_current_shift_config,
                       sim_start_weekday=int(getattr(p, "sim_start_weekday", 0)))
    else:
        import json
        from modules.simulation_d4 import run_simulation
        df_pivot, *_ = run_simulation(
            sim_days=a.sim_days, seed=a.seed, initial_conditions_json=a.initial_conditions,
            parameter_overrides=json.loads(a.overrides) if a.overrides else None,
            save_plots=False, log_filename="accession_diag_run.log", export_diagnostics=False)
        run_check(df_pivot, SPECIMEN_TYPES)


if __name__ == "__main__":
    main()
