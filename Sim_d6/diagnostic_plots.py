"""Pictures of the accession_diagnostics tables.   Run from the project root (next to accession_diagnostics.py):

    python diagnostic_plots.py --sim-days 25 --seed 1
    python diagnostic_plots.py --sim-days 25 --seed 1 --out diag_plots --grace-hours 24 [--stat-fraction 0.05]

Runs ONE replication (same call as `accession_diagnostics.py run`) and writes PNGs to --out:
  1_funnel.png             how many specimens reach each stage (bars, red where >50% drop vs the previous stage)
  2_review_backlog.png     plates still unreviewed `grace` hours after incubation started, over time, stacked by type
                           (flat = keeping up; rising = review capacity < plate load)
  3_review_wait_by_day.png median hours incubation start -> tech review, per type per day + unreviewed per day
  4_review_capacity.png    config only: review demand vs staffed tech-minutes per bench (rho on the bars)
  5_accession_vs_lis.png   simulated arrival->accessioned P50/P95 vs the JSON histogram, per type
  6_queues_over_time.png   queue length of the busiest tech/instrument queues from df_state (if the columns exist)
  7_tech_bench_use.png     tech_new / tech_urine / tech_routine: scheduled vs live capacity vs techs actually busy
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from params_config import event_name as EV
import accession_diagnostics as AD

PAL = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
       "#bcbd22", "#17becf", "#393b79", "#ad494a", "#637939"]


def _save(fig, out: Path, name: str):
    fig.tight_layout()
    fig.savefig(out / name, dpi=150)
    plt.close(fig)
    print("  wrote", out / name)


# ---------------------------------------------------------------- 1. funnel
def plot_funnel(df: pd.DataFrame, out: Path):
    rows = []
    for c in AD._stage_cols(df):
        k = int(df[c].notna().sum())
        if k:
            m = re.match(r"(\d+)([A-Za-z]*)", str(c))
            rows.append(((0, int(m.group(1)), m.group(2).lower(), str(c)) if m else (1, 0, "", str(c)), c, k))
    rows.sort(key=lambda r: r[0])
    labels = [r[1] for r in rows][::-1]
    vals = [r[2] for r in rows][::-1]
    prev, cols = None, []
    for v in vals[::-1]:
        cols.append("#d62728" if prev and v < 0.5 * prev else "#4c78a8")
        prev = v
    cols = cols[::-1]
    fig, ax = plt.subplots(figsize=(11, max(6, 0.22 * len(labels))))
    ax.barh(labels, vals, color=cols)
    ax.set_xlabel("specimens reaching the stage")
    ax.set_title(f"Stage funnel ({len(df):,} specimens). Red = <50% of the previous stage "
                 "(often a normal branch, e.g. only positives continue)", fontsize=10)
    ax.tick_params(axis="y", labelsize=7)
    ax.grid(axis="x", alpha=0.25)
    _save(fig, out, "1_funnel.png")


# ---------------------------------------------------------------- 2/3. review backlog
def _review_frame(df: pd.DataFrame):
    if EV.PRIMARY_INCUBATION not in df or EV.TECH_REVIEW not in df:
        return None
    d = df.dropna(subset=[EV.PRIMARY_INCUBATION]).copy()
    d["start"] = d[EV.PRIMARY_INCUBATION]
    d["review"] = d[EV.TECH_REVIEW]
    return d


def plot_review_backlog(df: pd.DataFrame, out: Path, grace_hours: float):
    d = _review_frame(df)
    if d is None:
        print("  review backlog skipped: incubation / review stage columns missing")
        return
    t_end = float(df[[c for c in df.columns if c in (EV.PRIMARY_INCUBATION, EV.TECH_REVIEW)]].max().max())
    grid = np.arange(0, t_end, 60.0)                       # hourly
    types = sorted(d["Type"].unique())
    stack = []
    for t in types:
        g = d[d["Type"] == t]
        due = g["start"].to_numpy() + grace_hours * 60.0
        rev = g["review"].fillna(np.inf).to_numpy()
        stack.append(_fast_count(due, rev, grid))   # waiting at time x  <=>  due <= x < review
    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.stackplot(grid / 1440.0, stack, labels=types, colors=PAL[:len(types)], alpha=0.9)
    ax.set_xlabel("simulation day")
    ax.set_ylabel(f"plates unreviewed > {grace_hours:g} h after incubation started")
    ax.set_title("Review backlog over time. Flat = keeping up; rising = review capacity < plate load")
    ax.legend(ncol=3, fontsize=8, frameon=False, loc="upper left")
    ax.grid(alpha=0.25)
    _save(fig, out, "2_review_backlog.png")


def _fast_count(due, rev, grid):
    """#(due <= x < rev) for every x, using sorted arrays (rev may be inf)."""
    # specimens reviewed before they were due never wait: exclude them from both counts
    keep = rev > due
    due_k, rev_k = np.sort(due[keep]), np.sort(rev[keep][np.isfinite(rev[keep])])
    return np.searchsorted(due_k, grid, side="right") - np.searchsorted(rev_k, grid, side="right")


def plot_review_wait_by_day(df: pd.DataFrame, out: Path):
    d = _review_frame(df)
    if d is None:
        return
    d["day"] = (d["start"] // 1440).astype(int)
    d["wait_h"] = (d["review"] - d["start"]) / 60.0
    types = sorted(d["Type"].unique())
    last = d["day"].max() - 2                              # last 2 days are censored
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 9), sharex=True)
    for i, t in enumerate(types):
        g = d[(d["Type"] == t) & (d["day"] <= last)]
        a1.plot(g.groupby("day")["wait_h"].median(), color=PAL[i % len(PAL)], lw=1.8, label=t)
    a1.set_ylabel("median hours: incubation start -> tech review")
    a1.set_title("Time to review by day incubation started (last 2 days dropped: not finished yet)")
    a1.legend(ncol=3, fontsize=8, frameon=False)
    a1.grid(alpha=0.25)
    un = d[d["day"] <= last].assign(un=lambda x: x["review"].isna()).groupby(["day", "Type"])["un"].sum().unstack(fill_value=0)
    un = un.reindex(columns=types, fill_value=0)
    un.plot(kind="bar", stacked=True, ax=a2, color=PAL[:len(types)], width=0.85, legend=False)
    a2.set_ylabel("plates never reviewed")
    a2.set_xlabel("day incubation started")
    a2.grid(axis="y", alpha=0.25)
    _save(fig, out, "3_review_wait_by_day.png")


# ---------------------------------------------------------------- 4. capacity (config only)
def plot_review_capacity(out: Path):
    import params_config.params_d3 as p
    from params_config.specimen_config_d2 import SPECIMEN_TYPES
    from params_config.staffing_config import SHIFT_STAFFING_PROFILE
    from modules.shift_manager_d2 import get_current_shift_config
    o = AD.review_capacity_check(SPECIMEN_TYPES, SHIFT_STAFFING_PROFILE, get_current_shift_config,
                                 sim_start_weekday=int(getattr(p, "sim_start_weekday", 0)),
                                 rejection_frac=float(getattr(p, "rejection_percent", 0.0)),
                                 default_range=(float(getattr(p, "min_tech_review_sub", 2.0)),
                                                float(getattr(p, "max_tech_review_sub", 4.0))))
    o = o[o["pool"] != "tech_blood"]
    o = o.assign(demand_tech_min=o["demand_tech_min"] / AD.AVAILABILITY)   # compare against GROSS staffed minutes
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for ax, day in zip(axes, ("weekday", "weekend")):
        g = o[o["daytype"] == day].reset_index(drop=True)
        x = np.arange(len(g))
        ax.bar(x - 0.2, g["staffed_tech_min"], 0.4, color="#b0b0b0", label="staffed tech-minutes / day")
        ax.bar(x + 0.2, g["demand_tech_min"], 0.4, color="#d62728", label="plate-review demand")
        for i, r in g.iterrows():
            ax.text(i + 0.2, r["demand_tech_min"], f"rho {r['rho']:.2f}", ha="center", va="bottom", fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels(g["pool"], rotation=20, fontsize=8)
        ax.set_title(day)
        ax.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("tech-minutes per day")
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle("Review demand vs staffing (review ONLY: workups, MALDI prep, plating share these benches, "
                 "so real rho is higher)", fontsize=10)
    _save(fig, out, "4_review_capacity.png")


# ---------------------------------------------------------------- 5. accession vs LIS
def plot_accession(df: pd.DataFrame, out: Path):
    from params_config.specimen_config_d2 import SPECIMEN_TYPES
    t = AD.accession_time_check(df, SPECIMEN_TYPES).set_index("type")
    x = np.arange(len(t))
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, s, h, name in ((axes[0], "sim_total_p50", "hist_p50", "P50"), (axes[1], "sim_total_p95", "hist_p95", "P95")):
        ax.bar(x - 0.2, t[s], 0.4, color="#1f77b4", label="simulation")
        ax.bar(x + 0.2, t[h], 0.4, color="#7f7f7f", label="LIS histogram")
        ax.set_xticks(x)
        ax.set_xticklabels(t.index, rotation=35, ha="right", fontsize=8)
        ax.set_ylabel("minutes, arrival -> accessioned")
        ax.set_title(name)
        ax.grid(axis="y", alpha=0.25)
    axes[0].legend(frameon=False)
    _save(fig, out, "5_accession_vs_lis.png")


# ---------------------------------------------------------------- 6. queues from df_state
def plot_queues(state: pd.DataFrame, out: Path, top: int = 8):
    if state is None or state.empty or "Minute" not in state:
        print("  queue plot skipped: no df_state")
        return
    q = [c for c in state.columns if re.search(r"queue|waiting", c.lower()) and c != "Minute"]
    if not q:
        print("  queue plot skipped; df_state columns:", list(state.columns))
        return
    best = sorted(q, key=lambda c: -pd.to_numeric(state[c], errors="coerce").mean())[:top]
    print("  queue columns plotted:", best)
    fig, ax = plt.subplots(figsize=(12, 5.5))
    for i, c in enumerate(best):
        ax.plot(state["Minute"] / 1440.0, pd.to_numeric(state[c], errors="coerce"), lw=1.0, color=PAL[i], label=c)
    ax.set_xlabel("simulation day")
    ax.set_ylabel("items waiting")
    ax.set_title(f"Busiest {len(best)} queues over time")
    ax.legend(fontsize=7, ncol=2, frameon=False)
    ax.grid(alpha=0.25)
    _save(fig, out, "6_queues_over_time.png")


# ---------------------------------------------------------------- 7. tech bench use (needs the patched state monitor)
def plot_tech_use(state: pd.DataFrame, out: Path, benches=("tech_new", "tech_urine", "tech_routine"), days: int = 4):
    need = [f"Res_{b}_in_use" for b in benches]
    if state is None or state.empty or any(c not in state for c in need):
        print("  tech-use plot skipped: df_state has no Res_tech_*_in_use columns "
              "(install the updated modules/state_monitor_process.py)")
        return
    st = state.copy()
    st["hour"] = ((st["Minute"] % 1440) // 60).astype(int)
    fig, axes = plt.subplots(2, len(benches), figsize=(5.2 * len(benches), 8), squeeze=False)
    print("\n=== Tech bench use (whole run) ===")
    print(f"  {'bench':<13}{'mean scheduled':>15}{'mean capacity':>15}{'mean in use':>13}{'in_use/capacity':>17}"
          f"{'% time cap<sched':>18}{'mean queue':>12}")
    for j, b in enumerate(benches):
        cap, use, sch = st[f"Res_{b}_capacity"], st[f"Res_{b}_in_use"], st[f"Res_{b}_scheduled"]
        q = st.get(f"Tech_{b.replace('tech_', '').capitalize()}_Queue_Length", pd.Series(0, index=st.index))
        util = use.sum() / max(cap.sum(), 1)
        print(f"  {b:<13}{sch.mean():>15.2f}{cap.mean():>15.2f}{use.mean():>13.2f}{util:>17.2f}"
              f"{100 * (cap < sch).mean():>18.1f}{q.mean():>12.0f}")
        w = st[(st["Minute"] >= 0) & (st["Minute"] < days * 1440)]
        ax = axes[0, j]
        ax.step(w["Minute"] / 60, w[f"Res_{b}_scheduled"], where="post", color="#7f7f7f", lw=2, label="scheduled (profile)")
        ax.step(w["Minute"] / 60, w[f"Res_{b}_capacity"], where="post", color="#1f77b4", lw=1.5, label="simpy capacity")
        ax.plot(w["Minute"] / 60, w[f"Res_{b}_in_use"], color="#d62728", lw=1.2, label="in use")
        ax.set_title(f"{b}: first {days} days")
        ax.set_xlabel("hour")
        ax.set_ylabel("techs")
        ax.grid(alpha=0.25)
        if j == 0:
            ax.legend(fontsize=8, frameon=False)
        ax2 = axes[1, j]
        h = st.groupby("hour")
        ax2.plot(h[f"Res_{b}_capacity"].mean(), color="#1f77b4", label="mean capacity")
        ax2.plot(h[f"Res_{b}_in_use"].mean(), color="#d62728", label="mean in use")
        ax3 = ax2.twinx()
        ax3.plot(q.groupby(st["hour"]).mean(), color="#2ca02c", ls="--", label="mean queue (right)")
        ax2.set_title(f"{b}: by hour of day (whole run)")
        ax2.set_xlabel("hour of day")
        ax2.set_ylabel("techs")
        ax3.set_ylabel("items waiting")
        ax2.grid(alpha=0.25)
        if j == 0:
            h1, l1 = ax2.get_legend_handles_labels()
            h2, l2 = ax3.get_legend_handles_labels()
            ax2.legend(h1 + h2, l1 + l2, fontsize=8, frameon=False)
    _save(fig, out, "7_tech_bench_use.png")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim-days", type=float, default=25)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--initial-conditions", type=str, default=None)
    ap.add_argument("--overrides", type=str, default=None)
    ap.add_argument("--stat-fraction", type=float, default=None)
    ap.add_argument("--audit", action="store_true", help="also print tech-minutes per bench by activity (modules/tech_audit.py)")
    ap.add_argument("--out", type=str, default="diag_plots")
    ap.add_argument("--grace-hours", type=float, default=24.0,
                    help="a plate counts as backlog once it is unreviewed this many hours after incubation started")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    from params_config.specimen_config_d2 import SPECIMEN_TYPES
    if a.stat_fraction is not None:
        for cfg in SPECIMEN_TYPES.values():
            cfg["stat_fraction"] = a.stat_fraction
    if a.audit:
        from modules import tech_audit
        tech_audit.install()
    from modules.simulation_d4 import run_simulation
    df, state, *_ = run_simulation(sim_days=a.sim_days, seed=a.seed, initial_conditions_json=a.initial_conditions,
                                   parameter_overrides=json.loads(a.overrides) if a.overrides else None,
                                   save_plots=False, log_filename="diag_plots_run.log", export_diagnostics=False)
    print("Plotting...")
    plot_funnel(df, out)
    plot_review_backlog(df, out, a.grace_hours)
    plot_review_wait_by_day(df, out)
    plot_review_capacity(out)
    plot_accession(df, out)
    plot_queues(state, out)
    plot_tech_use(state, out)
    if a.audit:
        tech_audit.report(a.sim_days, state).to_csv(out / "tech_audit.csv", index=False)
    print("Done. Open", out.resolve())


if __name__ == "__main__":
    main()
