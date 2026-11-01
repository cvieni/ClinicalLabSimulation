"""Where does the accession backlog come from? Three independent checks.

  python accession_diagnostics.py capacity
      Config only (no simulation). Offered load vs staffed capacity at accession, by hour of day,
      using the touch times, daily volumes, hourly arrival weights and staffing profile in your files.
      If daily utilisation (rho) is > 1 the queue grows forever no matter what else is right.

  python accession_diagnostics.py media
      Config only. Media names missing from MEDIA_CONFIG, and demand vs the reorder policy per medium.

  python accession_diagnostics.py run --sim-days 10 --seed 1 [--initial-conditions PATH]
      Runs ONE short replication and prints (a) the stage funnel (how many specimens reached each
      stage and where they stop), (b) accession-store wait by day, (c) arrivals/day per type vs
      daily_volume_mean, (d) how many specimens were pre-loaded at t=0, (e) simulated accession time vs the JSON histogram, (f) STAT vs routine waits.
      Run it twice, with and without --initial-conditions, to see whether a pre-loaded backlog is the cause.

  In code:  from accession_diagnostics import run_check;  run_check(df_pivot, SPECIMEN_TYPES)
"""
from __future__ import annotations

import argparse
import re

import numpy as np
import pandas as pd

from params_config import event_name as EV
IN_STORE, TOUCH_START, TOUCH_DONE = EV.ACCESSION_STORE_WAIT, EV.ACCESSION_START, EV.ACCESSION_DONE


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
    if not any(EV.COMPLETED in c for c in df.columns):
        print(f"  NOTE: no '{EV.COMPLETED}' stage was ever logged.")
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
# 3. Histogram vs simulation, and STAT vs routine
# ==================================================================================
def accession_time_check(df_pivot: pd.DataFrame, spec_types: dict) -> pd.DataFrame:
    """Compare, per type, the simulated arrival -> accessioned time with the JSON accession histogram.

    The JSON histogram is a real elapsed time between two LIS timestamps. The simulation's equivalent is
    hold + queue + touch = (1d. Completed) - (1c. Arrived at Pre-Accession Hold). If sim >> histogram the queue
    is too long (capacity or double counting: try p.accession_hold_mode = 'histogram_minus_touch'); if the
    sim is ~ histogram + queue, the histogram is being used as a pure delay on top of the queue.
    """
    rows = []
    for t, g in df_pivot.groupby("Type"):
        if EV.ACCESSION_DONE not in g or EV.PRE_ACCESSION_HOLD not in g:
            continue
        sim = (g[EV.ACCESSION_DONE] - g[EV.PRE_ACCESSION_HOLD]).dropna()
        hold = (g[EV.ACCESSION_STORE_WAIT] - g[EV.PRE_ACCESSION_HOLD]).dropna()
        q = (g[EV.ACCESSION_START] - g[EV.ACCESSION_STORE_WAIT]).dropna()
        cfg = (spec_types or {}).get(t, {}).get("accession_time_config")
        if cfg:
            e, pr = np.asarray(cfg["bin_edges"], float), np.asarray(cfg["bin_probabilities"], float)
            mids, pr = (e[:-1] + e[1:]) / 2, pr / pr.sum()
            hist_mean = float((mids * pr).sum())
            cdf = np.cumsum(pr)
            hist_p50 = float(np.interp(0.5, cdf, e[1:]))
            hist_p95 = float(np.interp(0.95, cdf, e[1:]))
        else:
            hist_mean = hist_p50 = hist_p95 = np.nan
        rows.append(dict(type=t, n=len(sim), hold_mean=hold.mean(), queue_mean=q.mean(),
                         sim_total_p50=sim.median(), sim_total_p95=sim.quantile(.95), sim_total_mean=sim.mean(),
                         hist_p50=hist_p50, hist_p95=hist_p95, hist_mean=hist_mean))
    out = pd.DataFrame(rows).round(1)
    print("\n=== Simulated arrival->accessioned (minutes) vs JSON histogram ===")
    print(out.to_string(index=False))
    print("  sim_total = hold + queue + touch. Histogram approx p50/p95 are read from bin edges (coarse).")
    return out


def priority_check(df_pivot: pd.DataFrame) -> pd.DataFrame:
    """STAT vs routine: queue wait (store entry -> tech starts) and total accession time, by priority tier."""
    cols = [EV.PRIORITY_STAT, EV.PRIORITY_ROUTINE, EV.ACCESSION_STORE_WAIT, EV.ACCESSION_START, EV.ACCESSION_DONE]
    if any(c not in df_pivot for c in (EV.ACCESSION_STORE_WAIT, EV.ACCESSION_START)):
        print("priority_check: accession stages missing")
        return pd.DataFrame()
    df = df_pivot.copy()
    stat = df[EV.PRIORITY_STAT].notna() if EV.PRIORITY_STAT in df else pd.Series(False, index=df.index)
    df["tier"] = np.where(stat, "STAT", "routine")
    df["queue_wait"] = df[EV.ACCESSION_START] - df[EV.ACCESSION_STORE_WAIT]
    df["accession_total"] = df[EV.ACCESSION_DONE] - df[EV.PRE_ACCESSION_HOLD] if EV.PRE_ACCESSION_HOLD in df else np.nan
    g = df.groupby("tier")
    out = pd.DataFrame({"n": g.size(), "queue_wait_p50": g["queue_wait"].median(),
                        "queue_wait_p95": g["queue_wait"].quantile(.95),
                        "accession_total_p50": g["accession_total"].median(),
                        "accession_total_p95": g["accession_total"].quantile(.95)}).round(1)
    print("\n=== STAT vs routine at accession (minutes) ===")
    print(out.to_string())
    return out


def review_check(df_pivot: pd.DataFrame) -> pd.DataFrame:
    """Plate incubation start -> tech review start, by day and by type. A backlog shows as wait climbing day over day
    and a growing 'never_reviewed' count. Specimens that start incubating in the last 2 days are expected to be
    unreviewed (right-censored), so look at earlier days."""
    start = next((c for c in df_pivot.columns if c in (EV.PRIMARY_INCUBATION,)), None)
    if start is None or EV.TECH_REVIEW not in df_pivot:
        print("\nreview_check: stages missing (need", EV.PRIMARY_INCUBATION, "and", EV.TECH_REVIEW, ")")
        return pd.DataFrame()
    d = df_pivot.dropna(subset=[start]).copy()
    d["wait_h"] = (d[EV.TECH_REVIEW] - d[start]) / 60.0
    d["day"] = (d[start] // 1440).astype(int)
    def tab(key):
        g = d.groupby(key)
        t = pd.DataFrame({"incubating": g.size(), "reviewed": g["wait_h"].count(),
                          "median_h_to_review": g["wait_h"].median(), "p95_h_to_review": g["wait_h"].quantile(.95)})
        t["never_reviewed"] = t["incubating"] - t["reviewed"]
        return t.round(1)
    by_day = tab("day")
    print("\n=== Plate incubation start -> tech review start, by day incubation started ===")
    print(by_day.to_string())
    print("\n=== Same, by specimen type ===")
    print(tab("Type").to_string())
    print("  Healthy: median ~ configured incubation time and never_reviewed ~ 0 except the last 2 days. "
          "Wait or never_reviewed climbing by day = review capacity < plate load.")
    return by_day


def review_pool(spec_type: str) -> str:
    """Mirror of modules.spec_proc_helpers.get_tech_bench: bottles -> tech_blood, urine -> tech_urine,
    everything else -> tech_new (stool follows p.stool_review_bench)."""
    u = spec_type.upper()
    if u.startswith("BCX") or u.startswith("BODYFLUID"):
        return "tech_blood"
    if u.startswith("URINE"):
        return "tech_urine"
    if u.startswith("STOOL"):
        import params_config.params_d3 as p
        return getattr(p, "stool_review_bench", "tech_new")
    return "tech_new"


# Per 8 h shift each tech loses 5+15+30 min of breaks (tech_breaks.py) and every bench loses a 15 min huddle
# (shift_manager_d2.py): ~13.5% of the staffed minutes are not available for work.
AVAILABILITY = 1.0 - (5 + 15 + 30 + 15) / 480.0


def review_capacity_check(spec_types: dict, staffing_profile: dict, get_shift_cfg, sim_start_weekday: int = 0,
                          rejection_frac: float = 0.0, default_range=(2.0, 4.0)) -> pd.DataFrame:
    """Config only. Primary plate-review load vs staffed tech-minutes per bench (weekday and weekend).

    Counts ONLY the first (day-2) plate read, done by tech_new / tech_urine. The comprehensive workup of subbed
    specimens is on tech_routine and is NOT in this table; the day-2 read is (volume x (1-rejection) x mean tech_review_range). Repeat workups, biochem,
    MALDI prep and manual plating also use these benches, so true utilisation is HIGHER than shown.
    Bottle types (BCx, BodyFluid) are reviewed only when positive, so they are listed but not counted.
    rho > 1 on a bench = its plates cannot all be read, whatever the priority rules say.
    """
    try:
        from params_config.specimen_config_d2 import resolve_time_range_override as resolve
    except Exception:
        resolve = None
    rows = []
    for t, cfg in spec_types.items():
        vol = cfg.get("daily_volume_mean")
        if vol is None:
            continue
        rng = cfg.get("tech_review_range") or default_range
        if isinstance(rng, dict):
            rng = (rng["min"], rng["max"])
        cfg_mean = (float(rng[0]) + float(rng[1])) / 2.0
        # What the SIMULATION uses: the same call as specimen_process_d5 (tuning matrix by shift, else default_range),
        # averaged over the 24 hours of a weekday.
        mids = []
        for h in range(24):
            r = None
            if resolve is not None:
                r = resolve(cfg, "tech_review_range", sim_minutes=h * 60.0,
                            default_range=cfg.get("tech_review_range") or default_range)
            r = r if r is not None else default_range
            mids.append((float(r[0]) + float(r[1])) / 2.0)
        mean_min = float(np.mean(mids))
        pool = review_pool(t)
        load = 0.0 if pool == "tech_blood" else float(vol) * (1.0 - rejection_frac) * mean_min
        rows.append(dict(type=t, pool=pool, vol_per_day=float(vol), cfg_review_min=cfg_mean, mean_review_min=mean_min,
                         review_tech_min_day=load))
    d = pd.DataFrame(rows)
    print("\n=== Plate review load by specimen type ===")
    print(d.round(1).to_string(index=False))

    weekend_day = (5 - sim_start_weekday) % 7
    out = []
    for label, day_idx in (("weekday", 0), ("weekend", weekend_day)):
        cap = {}
        for h in range(24):
            cfg = get_shift_cfg(day_idx * 1440.0 + h * 60.0, staffing_profile) or {}
            for k in ("tech_blood", "tech_urine", "tech_stool", "tech_routine", "tech_new"):
                cap[k] = cap.get(k, 0.0) + 60.0 * int(cfg.get(k, 0))
        for pool, g in d.groupby("pool"):
            c = sum(cap.get(k, 0.0) for k in pool.split("+"))
            ld = g["review_tech_min_day"].sum()
            rho = (ld / c) if c else (np.inf if ld else 0.0)
            out.append(dict(daytype=label, pool=pool, demand_tech_min=ld, staffed_tech_min=c, rho=rho,
                            rho_net=rho / AVAILABILITY))
    o = pd.DataFrame(out)
    print("\n=== Review demand vs staffed minutes (all 24 h, review only) ===")
    print(o.round(2).to_string(index=False))
    print(f"  rho_net = rho / {AVAILABILITY:.3f}: after breaks (5+15+30 min per tech) and the 15 min huddle per shift.")
    print("  rho = inf means the bench has NO staff in the profile: plates routed there wait for ever.")
    return o


def media_check(df_pivot: pd.DataFrame) -> pd.DataFrame:
    """How many specimens hit a media stockout / were dropped for media, by type. Dropped specimens are not
    'slow', they are removed from the TAT sample, so a high rate here means your TAT comparison is biased
    before any capacity question."""
    rows = []
    for t, g in df_pivot.groupby("Type"):
        n = len(g)
        stock = int(g[EV.STOCKOUT_DELAY_START].notna().sum()) if EV.STOCKOUT_DELAY_START in g else 0
        fail = int(g[EV.MEDIA_ALLOCATION_FAILED].notna().sum()) if EV.MEDIA_ALLOCATION_FAILED in g else 0
        rows.append(dict(type=t, n=n, stockout_delayed=stock, dropped_media=fail,
                         pct_dropped=round(100.0 * fail / n, 1) if n else np.nan))
    out = pd.DataFrame(rows)
    print("\n=== Media stockouts and drops ===")
    print(out.to_string(index=False))
    return out


# ==================================================================================
# CLI
# ==================================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("capacity")
    sub.add_parser("review", help="config only: plate-review load vs staffed minutes per bench")
    mp = sub.add_parser("media")
    mp.add_argument("--lead-days", type=float, default=3.0, help="supplier lead time used by MediaInventory (default 3)")
    mp.add_argument("--safety", type=float, default=1.25)
    mp.add_argument("--order-days", type=float, default=7.0, help="days of demand per order")
    mp.add_argument("--simulate", action="store_true", help="also run your MediaInventory for 60 days against the demand")
    r = sub.add_parser("run")
    r.add_argument("--sim-days", type=float, default=10)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--initial-conditions", type=str, default=None)
    r.add_argument("--stat-fraction", type=float, default=None,
                   help="set stat_fraction for EVERY specimen type for this run only (e.g. 0.05) to exercise the priority path")
    r.add_argument("--overrides", type=str, default=None, help="JSON dict of parameter overrides")
    a = ap.parse_args()

    from params_config.specimen_config_d2 import SPECIMEN_TYPES

    if a.cmd == "media":
        from params_config.media_config import MEDIA_CONFIG
        from modules.media_checks import (media_supply_report, suggest_media_config, simulate_stockouts,
                                          media_demand_per_day)
        import params_config.params_d3 as p
        media_supply_report(SPECIMEN_TYPES, MEDIA_CONFIG,
                            recheck_minutes=float(getattr(p, "inventory_stockout_recheck", 480.0)),
                            rejection_frac=float(getattr(p, "rejection_percent", 0.0)),
                            lead_time_days=a.lead_days, safety=a.safety, order_days=a.order_days)
        rej = float(getattr(p, "rejection_percent", 0.0))
        print("\n=== Suggested MEDIA_CONFIG (demand based; confirm against your real par levels) ===")
        print(suggest_media_config(SPECIMEN_TYPES, MEDIA_CONFIG, lead_time_days=a.lead_days, safety=a.safety,
                                   order_days=a.order_days, rejection_frac=rej))
        if a.simulate:
            dem = media_demand_per_day(SPECIMEN_TYPES, MEDIA_CONFIG, rej, 1.15)
            print("\n=== YOUR current policy against that demand, 60 days (share of requests with no stock) ===")
            print(simulate_stockouts(MEDIA_CONFIG, dem, lead_time_days=a.lead_days).to_string(index=False))
        return
    if a.cmd == "review":
        import params_config.params_d3 as p
        from params_config.staffing_config import SHIFT_STAFFING_PROFILE
        from modules.shift_manager_d2 import get_current_shift_config
        review_capacity_check(SPECIMEN_TYPES, SHIFT_STAFFING_PROFILE, get_current_shift_config,
                              sim_start_weekday=int(getattr(p, "sim_start_weekday", 0)),
                              rejection_frac=float(getattr(p, "rejection_percent", 0.0)),
                              default_range=(float(getattr(p, "min_tech_review_sub", 2.0)),
                                             float(getattr(p, "max_tech_review_sub", 4.0))))
    elif a.cmd == "capacity":
        import params_config.params_d3 as p
        from params_config.staffing_config import SHIFT_STAFFING_PROFILE
        from modules.shift_manager_d2 import get_current_shift_config
        capacity_check(SPECIMEN_TYPES, SHIFT_STAFFING_PROFILE, get_current_shift_config,
                       sim_start_weekday=int(getattr(p, "sim_start_weekday", 0)))
    else:
        import json
        if a.stat_fraction is not None:
            for cfg in SPECIMEN_TYPES.values():
                cfg["stat_fraction"] = a.stat_fraction
        from modules.simulation_d4 import run_simulation
        df_pivot, *_ = run_simulation(
            sim_days=a.sim_days, seed=a.seed, initial_conditions_json=a.initial_conditions,
            parameter_overrides=json.loads(a.overrides) if a.overrides else None,
            save_plots=False, log_filename="accession_diag_run.log", export_diagnostics=False)
        run_check(df_pivot, SPECIMEN_TYPES)
        accession_time_check(df_pivot, SPECIMEN_TYPES)
        priority_check(df_pivot)
        review_check(df_pivot)
        media_check(df_pivot)


if __name__ == "__main__":
    main()
