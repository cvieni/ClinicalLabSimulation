#!/usr/bin/env python
"""Run N Monte Carlo replications of the lab simulation, keep the per-specimen and system-state
logs of EVERY replication, and plot them for troubleshooting.

Why this does not call modules.monte_carlo.run_monte_carlo_simulation: that function reduces each
run to a few summary numbers and discards per-specimen arrival times and the df_state log, which
the shift-shaded TAT plots and the utilization plots need. This script runs run_simulation directly
(same overrides handling, same seeds: seed_base + i) and saves everything.

Place in the project root (next to project_config.py) and run, e.g.:

    python run_monte_carlo_and_plot.py --iterations 30 --sim-days 40
    python run_monte_carlo_and_plot.py --iterations 30 --sim-days 40 \
        --overrides '{"positive_specimen_rate": 0.15, "scheduled_reads_enabled": true}' \
        --observed observed_lis_month.csv
    python run_monte_carlo_and_plot.py --out results_experiments/mc_20261027_1100 --plots-only

Outputs (in --out):
    run_table.csv                    one row per replication, all KPIs
    replication_summary.csv          mean, SD, t-CI of the mean, and 95% percentile band per KPI
    replications/specimens_###.csv.gz, state_###.csv.gz, logs/rep_###.log
    plots/1_tat_by_hour_of_arrival.png   TAT P50/P95 vs arrival hour, per specimen type, shift-shaded
    plots/2_tat_timeline.png             individual specimens over the first days of one replication
    plots/3_tech_utilization.png         utilization / queues, folded 24 h + timeline, shift-shaded
    plots/4_kpis.png                     P50 / P95 by type and by shift, run health

--observed CSV (optional), columns: Type, P50, P95 [, Shift]  -> drawn as black markers/lines.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import params_config.params_d3 as p
from modules.simulation_d4 import run_simulation
from modules.run_metrics import compute_tat_metrics
from modules.param_overrides import validate_overrides
from modules.MonteCarlo.monte_carlo_d3 import summarize_run_table

SPEC_COLS = ["Specimen_ID", "Type", "Arrival_Minute", "Completed_Minute",
             "Total_TAT_Hours", "Arrival_Shift", "Outcome", "In_Window"]
SHIFT_COLORS = {"Day": "#FFE98A", "Evening": "#FFB86B", "Night": "#9DB4F0"}
SHIFT_ORDER = ["Day", "Evening", "Night"]
MIN_N = 5            # fewer specimens than this in a bin -> no percentile drawn
MIN_N_SHIFT = 10

PROJECT_ROOT = Path(__file__).resolve().parent
INITIAL_CONDITIONS_PATH = PROJECT_ROOT / "params_config" / "initial_conditions.json"


# ==================================================================================
# Worker (top-level so it pickles under spawn on Windows/macOS)
# ==================================================================================
def _run_one(task):
    i, seed, a = task
    rep_dir = Path(a["out"]) / "replications"
    log_dir = Path(a["out"]) / "logs"
    rep_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    df_pivot, df_state, _media, _ai, stats = run_simulation(
        sim_days=a["sim_days"],
        seed=seed,
        initial_conditions_json=a["initial_conditions"],
        parameter_overrides=a["overrides"],
        set_progress=None,
        save_plots=False,
        log_filename=str(log_dir / f"rep_{i:03d}.log"),
        export_diagnostics=False,
    )
    row = {"rep": i, "seed": seed}
    if df_pivot.empty:
        return row

    spec = df_pivot[[c for c in SPEC_COLS if c in df_pivot.columns]].copy()
    spec["rep"] = i
    spec.to_csv(rep_dir / f"specimens_{i:03d}.csv.gz", index=False)
    if df_state is not None and not df_state.empty:
        df_state.assign(rep=i).to_csv(rep_dir / f"state_{i:03d}.csv.gz", index=False)

    metrics, summary, _ = compute_tat_metrics(df_pivot)
    row.update({k: v for k, v in (stats or {}).items() if isinstance(v, (int, float, bool))})
    row.update(metrics)
    row.update(summary)
    row["total_specimens"] = int(len(df_pivot))
    return row


# ==================================================================================
# Load
# ==================================================================================
def _load_concat(rep_dir: Path, prefix: str) -> pd.DataFrame:
    files = sorted(rep_dir.glob(f"{prefix}_*.csv.gz"))
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True) if files else pd.DataFrame()


def _window(run_table: pd.DataFrame, sim_days: float):
    if {"window_start_min", "window_end_min"}.issubset(run_table.columns):
        return float(run_table["window_start_min"].iloc[0]), float(run_table["window_end_min"].iloc[0])
    return 0.0, sim_days * 1440.0


# ==================================================================================
# Shift shading
# ==================================================================================
def _shift_spans():
    """(start_hour, end_hour, label) within one 24 h day, from the params file."""
    return [
        (0, p.shift_1_start, "Night"),
        (p.shift_1_start, p.shift_1_end, "Day"),
        (p.shift_2_start, p.shift_2_end, "Evening"),
        (p.shift_2_end, 24, "Night"),
    ]


def shade_shifts(ax, n_days: int = 1, label: bool = True):
    """Shade shift blocks. n_days=1: folded 24 h axis. n_days>1: x axis in hours over several days."""
    seen = set()
    for d in range(n_days):
        for s, e, name in _shift_spans():
            if e <= s:
                continue
            lab = name if (label and name not in seen) else None
            seen.add(name)
            ax.axvspan(d * 24 + s, d * 24 + e, color=SHIFT_COLORS[name], alpha=0.30, lw=0, label=lab, zorder=0)


def _grid(n, ncol_max=3, cell=(5.2, 3.6)):
    ncol = min(ncol_max, max(n, 1))
    nrow = math.ceil(n / ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(cell[0] * ncol, cell[1] * nrow), squeeze=False)
    flat = axes.ravel()
    for ax in flat[n:]:
        ax.axis("off")
    return fig, flat[:n]


def _band(ax, x, frame: pd.DataFrame, color, label):
    """frame: rows = replications, columns = x bins. Mean line + 2.5-97.5% band across replications."""
    ax.plot(x, frame.mean(axis=0), color=color, lw=2, label=label, zorder=3)
    ax.fill_between(x, frame.quantile(0.025), frame.quantile(0.975), color=color, alpha=0.22, lw=0, zorder=2)


def _observed_lookup(observed: pd.DataFrame | None, t, shift=None):
    if observed is None:
        return None
    m = observed["Type"].astype(str) == str(t)
    if "Shift" in observed.columns:
        m &= (observed["Shift"].astype(str) == str(shift)) if shift else observed["Shift"].isna()
    r = observed[m]
    return None if r.empty else r.iloc[0]


# ==================================================================================
# Plot 1: TAT vs arrival hour of day, per specimen type, shift-shaded
# ==================================================================================
def plot_tat_by_hour(spec: pd.DataFrame, observed, out: Path):
    d_all = spec[spec["In_Window"].astype(bool)].dropna(subset=["Total_TAT_Hours"]).copy()
    types = sorted(d_all["Type"].unique())
    fig, axes = _grid(len(types))
    for ax, t in zip(axes, types):
        d = d_all[d_all["Type"] == t].copy()
        d["hour"] = ((d["Arrival_Minute"] % 1440) // 60).astype(int)
        samp = d.sample(min(len(d), 4000), random_state=0)
        shade_shifts(ax)
        ax.scatter((samp["Arrival_Minute"] % 1440) / 60, samp["Total_TAT_Hours"],
                   s=3, alpha=0.10, color="0.35", lw=0, zorder=1, label="specimens (sample)")
        g = d.groupby(["rep", "hour"])["Total_TAT_Hours"]
        n = g.size().unstack("hour")
        for q, color, lab in ((0.5, "#1f77b4", "P50"), (0.95, "#d62728", "P95")):
            frame = g.quantile(q).unstack("hour").where(n >= MIN_N)
            _band(ax, frame.columns.values + 0.5, frame, color, f"{lab} (mean, 95% band over reps)")
        ob = _observed_lookup(observed, t)
        if ob is not None:
            for col, ls in (("P50", "--"), ("P95", ":")):
                if col in ob and pd.notna(ob[col]):
                    ax.axhline(ob[col], color="k", ls=ls, lw=1.3, label=f"observed {col}", zorder=4)
        ax.set_xlim(0, 24)
        ax.set_xticks(range(0, 25, 3))
        ax.set_ylim(0, max(1.0, float(d["Total_TAT_Hours"].quantile(0.995)) * 1.05))
        ax.set_title(f"{t}  (n={len(d):,} over {d['rep'].nunique()} reps)", fontsize=10, fontweight="bold")
        ax.set_xlabel("Arrival hour of day")
        ax.set_ylabel("TAT (h)")
        ax.grid(alpha=0.25)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=min(len(l), 6), frameon=False, fontsize=8)
    fig.suptitle("TAT by arrival hour (measurement window only); shaded = staffing shifts", fontweight="bold")
    fig.tight_layout(rect=[0, 0.05, 1, 0.97])
    fig.savefig(out, dpi=200)
    plt.close(fig)


# ==================================================================================
# Plot 2: individual specimens over a few days of one replication
# ==================================================================================
def plot_tat_timeline(spec: pd.DataFrame, rep: int, days: int, window_start: float, out: Path):
    d_all = spec[(spec["rep"] == rep)].dropna(subset=["Total_TAT_Hours"]).copy()
    t0 = math.floor(window_start / 1440.0) * 1440.0
    d_all = d_all[(d_all["Arrival_Minute"] >= t0) & (d_all["Arrival_Minute"] < t0 + days * 1440)]
    if d_all.empty:
        print("  (timeline plot skipped: no specimens in that span)")
        return
    types = sorted(d_all["Type"].unique())
    fig, axes = _grid(len(types), ncol_max=1, cell=(13, 2.6))
    for ax, t in zip(axes, types):
        d = d_all[d_all["Type"] == t]
        shade_shifts(ax, n_days=days)
        x = (d["Arrival_Minute"] - t0) / 60.0
        for oc, color in (("neg", "#4c78a8"), ("pos", "#e45756")):
            m = d["Outcome"] == oc
            if m.any():
                ax.scatter(x[m], d.loc[m, "Total_TAT_Hours"], s=7, alpha=0.6, color=color, lw=0,
                           label=f"{oc}", zorder=3)
        ax.set_xlim(0, days * 24)
        ax.set_xticks(range(0, days * 24 + 1, 24))
        ax.set_ylabel(f"{t}\nTAT (h)")
        ax.grid(alpha=0.25)
    axes[-1].set_xlabel(f"Hours since day 0 of the window (replication {rep})")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper right", ncol=6, frameon=False, fontsize=8)
    fig.suptitle(f"Specimen TAT by arrival time, replication {rep}; shaded = shifts; neg/pos = culture outcome",
                 fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(out, dpi=200)
    plt.close(fig)


# ==================================================================================
# Plot 3: utilization and queues
# ==================================================================================
def find_state_series(state: pd.DataFrame, util_filter: str):
    """Work out which df_state columns are utilization, which are queues.

    I have not seen state_monitor_process's output, so this is heuristic and prints what it found:
      1. columns with 'util' in the name  -> used as is (scaled to 0-1 if they look like percent)
      2. columns with in_use / busy / active -> divided by a matching '*cap*' column when one exists,
         otherwise plotted as a raw count
      3. columns with 'queue' / 'waiting' -> queue panel
    --util-filter (regex, default 'tech') selects which resources to show.
    """
    cols = [c for c in state.columns if c not in ("Minute", "rep")]
    low = {c: c.lower() for c in cols}
    queue = [c for c in cols if re.search(r"queue|waiting", low[c])]
    util = [c for c in cols if "util" in low[c] and c not in queue]
    inuse = [c for c in cols if re.search(r"in_?use|busy|active", low[c]) and c not in queue and c not in util]

    def keep(cs):
        sel = [c for c in cs if re.search(util_filter, low[c])]
        return sel if sel else cs

    series, labels = {}, {}
    for c in keep(util):
        s = state[c].astype(float)
        series[c] = s / 100.0 if s.max() > 1.5 else s
        labels[c] = "utilization (0-1)"
    for c in keep(inuse):
        base = re.sub(r"(_?in_?use|_?busy|_?active)", "", low[c])
        cap = [k for k in cols if "cap" in low[k] and base and base in low[k]]
        if cap:
            series[c] = state[c].astype(float) / state[cap[0]].replace(0, np.nan).astype(float)
            labels[c] = "utilization (0-1)"
        else:
            series[c] = state[c].astype(float)
            labels[c] = "in use (count)"
    return series, keep(queue), labels


def _hourly_by_rep(state: pd.DataFrame, series: dict) -> dict:
    """series name -> DataFrame(rows=rep, cols=hour of day) of mean value."""
    hour = ((state["Minute"] % 1440) // 60).astype(int)
    out = {}
    for name, s in series.items():
        out[name] = s.groupby([state["rep"], hour]).mean().unstack()
    return out


def plot_utilization(state: pd.DataFrame, window, rep: int, days: int, util_filter: str, out: Path):
    state = state[(state["Minute"] >= window[0]) & (state["Minute"] < window[1])].copy()
    series, queues, labels = find_state_series(state, util_filter)
    print(f"  state columns available: {[c for c in state.columns if c not in ('Minute', 'rep')]}")
    print(f"  utilization series used: {list(series)}")
    print(f"  queue series used:       {queues}")
    if not series and not queues:
        print("  (utilization plot skipped: no recognisable columns; pass --util-filter or edit find_state_series)")
        return
    qseries = {c: state[c].astype(float) for c in queues}
    pal = plt.get_cmap("tab10")

    fig, axes = plt.subplots(3, 1, figsize=(13, 11))
    ax1, ax2, ax3 = axes

    # (1) folded 24 h
    shade_shifts(ax1)
    for k, (name, frame) in enumerate(_hourly_by_rep(state, series).items()):
        _band(ax1, frame.columns.values + 0.5, frame, pal(k % 10), name)
    ax1.set_xlim(0, 24)
    ax1.set_xticks(range(0, 25, 2))
    ax1.set_ylabel(next(iter(labels.values()), ""))
    ax1.set_title("Resource use by hour of day (mean, 95% band over replications)", fontsize=10, fontweight="bold")
    if series:
        ax1.axhline(1.0, color="k", lw=0.8, ls=":")
    ax1.legend(fontsize=7, ncol=3, frameon=False, loc="upper right")
    ax1.grid(alpha=0.25)

    # (2) timeline of one replication
    t0 = math.floor(window[0] / 1440.0) * 1440.0
    r = state[(state["rep"] == rep) & (state["Minute"] >= t0) & (state["Minute"] < t0 + days * 1440)]
    shade_shifts(ax2, n_days=days)
    for k, (name, s) in enumerate(series.items()):
        ax2.plot((r["Minute"] - t0) / 60.0, s.loc[r.index], color=pal(k % 10), lw=1.2, label=name)
    ax2.set_xlim(0, days * 24)
    ax2.set_xticks(range(0, days * 24 + 1, 24))
    ax2.set_ylabel(next(iter(labels.values()), ""))
    ax2.set_title(f"Resource use over time, replication {rep}", fontsize=10, fontweight="bold")
    ax2.grid(alpha=0.25)

    # (3) queues folded
    shade_shifts(ax3, label=False)
    top = sorted(qseries, key=lambda c: -qseries[c].mean())[:8]
    for k, name in enumerate(top):
        frame = _hourly_by_rep(state, {name: qseries[name]})[name]
        _band(ax3, frame.columns.values + 0.5, frame, pal(k % 10), name)
    ax3.set_xlim(0, 24)
    ax3.set_xticks(range(0, 25, 2))
    ax3.set_xlabel("Hour of day")
    ax3.set_ylabel("Waiting in queue")
    ax3.set_title("Queue length by hour of day (top 8 queues)", fontsize=10, fontweight="bold")
    ax3.legend(fontsize=7, ncol=3, frameon=False, loc="upper right")
    ax3.grid(alpha=0.25)

    h = [plt.Rectangle((0, 0), 1, 1, color=SHIFT_COLORS[s], alpha=0.5) for s in SHIFT_ORDER]
    fig.legend(h, SHIFT_ORDER, loc="lower center", ncol=3, frameon=False)
    fig.tight_layout(rect=[0, 0.03, 1, 1])
    fig.savefig(out, dpi=200)
    plt.close(fig)


# ==================================================================================
# Plot 4: KPIs
# ==================================================================================
def kpi_table(spec: pd.DataFrame) -> pd.DataFrame:
    d = spec[spec["In_Window"].astype(bool)].dropna(subset=["Total_TAT_Hours"])
    rows = []
    for (rep, t), g in d.groupby(["rep", "Type"]):
        s = g["Total_TAT_Hours"]
        rows.append(dict(rep=rep, Type=t, Shift="All", n=len(s), p50=s.quantile(.5), p95=s.quantile(.95)))
        for sh, gs in g.groupby("Arrival_Shift"):
            if len(gs) >= MIN_N_SHIFT:
                s2 = gs["Total_TAT_Hours"]
                rows.append(dict(rep=rep, Type=t, Shift=sh, n=len(s2), p50=s2.quantile(.5), p95=s2.quantile(.95)))
    return pd.DataFrame(rows)


def plot_kpis(spec: pd.DataFrame, run_table: pd.DataFrame, observed, out: Path):
    k = kpi_table(spec)
    types = sorted(k["Type"].unique())
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))

    for ax, col, color in ((axes[0, 0], "p50", "#1f77b4"), (axes[0, 1], "p95", "#d62728")):
        data = [k[(k.Type == t) & (k.Shift == "All")][col].dropna().values for t in types]
        ax.boxplot(data, tick_labels=types, patch_artist=True,
                   boxprops=dict(facecolor=color, alpha=0.35), medianprops=dict(color="k"))
        for i, v in enumerate(data, 1):
            ax.scatter(np.random.default_rng(i).normal(i, 0.04, len(v)), v, s=8, color=color, alpha=0.7, zorder=3)
        for i, t in enumerate(types, 1):
            ob = _observed_lookup(observed, t)
            if ob is not None and col.upper() in ob and pd.notna(ob[col.upper()]):
                ax.scatter([i], [ob[col.upper()]], marker="D", s=70, color="k", zorder=5,
                           label="observed" if i == 1 else None)
        ax.set_ylabel("hours")
        ax.set_title(f"{col.upper()} TAT by specimen type (one point per replication)", fontsize=10, fontweight="bold")
        ax.grid(axis="y", alpha=0.25)
        ax.tick_params(axis="x", rotation=30)
        if observed is not None:
            ax.legend(frameon=False)

    ax = axes[1, 0]
    width = 0.8 / len(SHIFT_ORDER)
    for j, sh in enumerate(SHIFT_ORDER):
        data = [k[(k.Type == t) & (k.Shift == sh)]["p95"].dropna().values for t in types]
        pos = np.arange(len(types)) + (j - 1) * width
        bp = ax.boxplot(data, positions=pos, widths=width * 0.9, patch_artist=True, manage_ticks=False,
                        boxprops=dict(facecolor=SHIFT_COLORS[sh], alpha=0.9), medianprops=dict(color="k"),
                        flierprops=dict(markersize=2))
        bp["boxes"][0].set_label(sh)
        for i, t in enumerate(types):
            ob = _observed_lookup(observed, t, sh)
            if ob is not None and pd.notna(ob.get("P95", np.nan)):
                ax.scatter([pos[i]], [ob["P95"]], marker="D", s=40, color="k", zorder=5)
    ax.set_xticks(range(len(types)))
    ax.set_xticklabels(types, rotation=30)
    ax.set_ylabel("hours")
    ax.set_title("P95 TAT by ARRIVAL shift", fontsize=10, fontweight="bold")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25)

    ax = axes[1, 1]
    x = run_table["rep"].values
    if "n_in_window" in run_table.columns:
        ax.bar(x, run_table["n_in_window"], color="0.7", label="specimens in window")
    ax.set_xlabel("replication")
    ax.set_ylabel("specimens in window")
    if "n_incomplete_in_window" in run_table.columns:
        ax2 = ax.twinx()
        ax2.plot(x, run_table["n_incomplete_in_window"], "o-", color="#d62728", label="incomplete (censored)")
        ax2.set_ylabel("incomplete in window", color="#d62728")
        ax2.set_ylim(bottom=0)
    ax.set_title("Run health: should have ~0 incomplete in window", fontsize=10, fontweight="bold")

    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


# ==================================================================================
# Main
# ==================================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iterations", type=int, default=30)
    ap.add_argument("--sim-days", type=float, default=43,
                    help="must exceed warmup_days + cooldown_days + the period you want measured")
    ap.add_argument("--seed", type=int, default=42, help="replication i uses seed + i")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", type=str, default=None, help="output dir (default results_experiments/mc_<timestamp>)")
    ap.add_argument("--initial-conditions", type=str, default=None)
    ap.add_argument("--overrides", type=str, default=None, help="JSON dict of parameter overrides")
    ap.add_argument("--overrides-file", type=str, default=None)
    ap.add_argument("--observed", type=str, default=None, help="CSV: Type,P50,P95[,Shift]")
    ap.add_argument("--timeline-rep", type=int, default=0)
    ap.add_argument("--timeline-days", type=int, default=7)
    ap.add_argument("--util-filter", type=str, default="tech", help="regex selecting resources for the utilization plot")
    ap.add_argument("--plots-only", action="store_true", help="re-plot an existing --out directory")
    a = ap.parse_args()

    if a.initial_conditions is None and INITIAL_CONDITIONS_PATH.exists():
        a.initial_conditions = str(INITIAL_CONDITIONS_PATH)
        print(f"Initial conditions not provided, defaulting to \n {INITIAL_CONDITIONS_PATH}")


    overrides = None
    if a.overrides_file:
        overrides_path = Path(a.overrides_file)
        if not overrides_path.exists():
            raise FileNotFoundError(f"Specified overrides file not found: {overrides_path.resolve()}")
        
        raw_json = json.loads(overrides_path.read_text(encoding="utf-8"))
        
        # Extract parameter dictionary if nested, or use as top-level dict
        if "ttp_config" in raw_json and "params" in raw_json["ttp_config"]:
            overrides = raw_json["ttp_config"]["params"]
        else:
            overrides = raw_json

    if a.overrides:
        overrides = {**(overrides or {}), **json.loads(a.overrides)}

    if overrides:
        validate_overrides(overrides)

    if a.plots_only and not a.out:
        sys.exit("--plots-only needs --out pointing at an existing run directory")
    out = Path(a.out) if a.out else Path("results_experiments") / f"mc_{datetime.now():%Y%m%d_%H%M%S}"
    (out / "plots").mkdir(parents=True, exist_ok=True)
    rep_dir = out / "replications"

    if not a.plots_only:
        (out / "config.json").write_text(json.dumps(
            {"iterations": a.iterations, "sim_days": a.sim_days, "seed": a.seed, "overrides": overrides,
             "initial_conditions": a.initial_conditions, "ttp_source": p.TTP_SOURCE,
             "warmup_days": p.warmup_days, "cooldown_days": p.cooldown_days,
             "scheduled_reads_enabled": p.scheduled_reads_enabled}, indent=2, default=str))
        task_args = {"out": str(out), "sim_days": a.sim_days, "initial_conditions": a.initial_conditions,
                     "overrides": overrides}
        tasks = [(i, a.seed + i, task_args) for i in range(a.iterations)]
        workers = a.workers or min(__import__("os").cpu_count() or 4, a.iterations)
        print(f"Running {a.iterations} replications x {a.sim_days} days on {workers} workers -> {out}")
        t0, rows = time.time(), []
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_run_one, t) for t in tasks]
            for n, f in enumerate(as_completed(futs), 1):
                rows.append(f.result())      # a failing replication raises here, with its traceback
                print(f"  {n}/{a.iterations} done ({time.time() - t0:.0f}s)", end="\r", flush=True)
        print()
        run_table = pd.DataFrame(sorted(rows, key=lambda r: r["rep"]))
        run_table.to_csv(out / "run_table.csv", index=False)
    else:
        run_table = pd.read_csv(out / "run_table.csv")

    summary = summarize_run_table(run_table)
    summary.to_csv(out / "replication_summary.csv", index=False)

    spec = _load_concat(rep_dir, "specimens")
    state = _load_concat(rep_dir, "state")
    if spec.empty:
        sys.exit("No specimen data was produced.")
    observed = pd.read_csv(a.observed) if a.observed else None
    window = _window(run_table, a.sim_days)

    print("\nKey KPIs across replications (hours): mean [95% band of one simulated month]")
    # key = summary[summary["metric"].str.match(r"^tat_(overall_p50|overall_p95|p50_[^_]+$|p95_[^_]+$)")]
    if not summary.empty and "metric" in summary.columns:
        key = summary[summary["metric"].str.match(r"^tat_(overall_p50|overall_p95|p50_[^_]+$|p95_[^_]+$)")]
        for _, r in key.iterrows():
            print(f"  {r['metric']:<28} {r['mean']:7.2f}  [{r['pi_lo']:.2f}, {r['pi_hi']:.2f}]   n={int(r['n'])}")
    else:
        print("  WARNING: No completed specimens recorded across replications; TAT metrics unavailable.")

    
    # for _, r in key.iterrows():
    #     print(f"  {r['metric']:<28} {r['mean']:7.2f}  [{r['pi_lo']:.2f}, {r['pi_hi']:.2f}]   n={int(r['n'])}")
    # if "n_incomplete_in_window" in run_table.columns and run_table["n_incomplete_in_window"].max() > 0:
    #     print(f"\n  WARNING: up to {int(run_table['n_incomplete_in_window'].max())} in-window specimens never "
    #           f"finished (right-censored). Raise --sim-days or cooldown_days.")

    pl = out / "plots"
    print("\nPlotting...")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        plot_tat_by_hour(spec, observed, pl / "1_tat_by_hour_of_arrival.png")
        plot_tat_timeline(spec, a.timeline_rep, a.timeline_days, window[0], pl / "2_tat_timeline.png")
        if state.empty:
            print("  (no df_state logs: utilization plot skipped)")
        else:
            plot_utilization(state, window, a.timeline_rep, a.timeline_days, a.util_filter,
                             pl / "3_tech_utilization.png")
        plot_kpis(spec, run_table, observed, pl / "4_kpis.png")
    print(f"Done. Open {pl.resolve()}")





if __name__ == "__main__":
    main()