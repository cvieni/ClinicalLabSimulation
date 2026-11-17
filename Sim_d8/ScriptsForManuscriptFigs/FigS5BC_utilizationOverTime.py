#!/usr/bin/env python3
"""Figure S5B–F: Five separate standalone figures for bench utilization & queue length:
  1. FigS5B_daily_utilization_by_bench   (daily mean % utilization by bench across simulation days)
  2. FigS5C_daily_utilization_by_shift   (daily mean % utilization by shift across simulation days)
  3. FigS5D_utilization_by_hour          (folded 24 h % utilization by bench, mean & 95% band)
  4. FigS5E_utilization_timeline         (single-replication % utilization timeline over days)
  5. FigS5F_queue_by_hour                (folded 24 h normalized queue length by bench, mean & 95% band)

Each figure is saved as <stem>_labelled.png (white background, visible axes & labels)
and <stem>_unlabelled.png (transparent background, visible axes & tick marks, no text/legends).
"""
import glob
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

import fig_common as fc

# =========================================================== SETTINGS ===========================================================
# Research/ClinicalLabSimulation
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# Research/ClinicalLabSimulation/Sim_d8
SIM_DIR = Path(__file__).resolve().parent.parent
# Research/ClinicalLabSimulation/Sim_d8/manuscript_png/FigS5_UtilizationTime
OUTPUT_DIR = Path(SIM_DIR, "manuscript_png/FigS5_UtilizationTime")
MC_DIR = Path(SIM_DIR, "results_experiments/scn_baseline")

PNG_WIDTH = 6.8
PNG_HEIGHT = 4.2
DPI = 300
LEGEND_COLUMNS = 3

TIMELINE_REP = 0              # replication index for the timeline plot
TIMELINE_DAYS = 7             # number of days shown in the timeline plot
TOP_N_QUEUES = 8              # maximum number of individual bench queues plotted
QUEUE_NORM_MODE = "max_queue" # "max_queue" (% of each bench's peak queue) or "daily_specimens" (% of mean daily specimens)

BENCH_LABELS = {
    "tech_accession": "Accessioning",
    "tech_float_accession": "Float (accession/plating)",
    "tech_plating": "Plating",
    "tech_blood": "Blood culture bench",
    "tech_urine": "Urine bench",
    "tech_stool": "Stool bench",
    "tech_new": "New-plate bench",
    "tech_float_newroutine": "Float (new/routine)",
    "tech_routine": "Routine bench",
    "tech_supervisor": "Supervisor",
}

QUEUE_LABELS = {
    "Tech_Accession_Queue_Length": "Accessioning",
    "Tech_Float_accession_Queue_Length": "Float (accession/plating)",
    "Tech_Plating_Queue_Length": "Plating",
    "Tech_Blood_Queue_Length": "Blood culture bench",
    "Tech_Urine_Queue_Length": "Urine bench",
    "Tech_Stool_Queue_Length": "Stool bench",
    "Tech_New_Queue_Length": "New-plate bench",
    "Tech_Float_newroutine_Queue_Length": "Float (new/routine)",
    "Tech_Routine_Queue_Length": "Routine bench",
    "Tech_Supervisor_Queue_Length": "Supervisor",
}

# Exclude aggregate totals and physical incubator/instrument slots so only bench tech queues are shown
EXCLUDE_COLS_PATTERN = re.compile(
    r"busy_techs|active_techs|total_tech|simpy_capacity|^res_",
    re.IGNORECASE,
)

# 12 distinct colors so every bench gets a unique color
DISTINCT_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#393b79",
    "#637939", "#8c6d31",
]

SHIFT_COLORS = {"Day": "#FFE98A", "Evening": "#FFB86B", "Night": "#9DB4F0"}
SHIFT_ORDER = ["Day", "Evening", "Night"]
# ================================================================================================================================


def save_both(fig, stem, out_dir: Path, dpi: int = 300):
    """Save <stem>_labelled.png (white bg, visible axes) and <stem>_unlabelled.png (transparent bg, tick marks only) on an identical canvas."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Labelled version: solid white background, visible axes, tick labels, titles, and legends
    fig.patch.set_facecolor("white")
    fig.patch.set_alpha(1.0)
    for ax in fig.axes:
        ax.set_facecolor("white")
        ax.patch.set_alpha(1.0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_visible(True)
        ax.spines["left"].set_visible(True)
        ax.tick_params(which="both", bottom=True, left=True)

    fig.savefig(
        out_dir / f"{stem}_labelled.png",
        dpi=dpi,
        transparent=False,
        facecolor="white",
    )

    # 2. Strip all titles, axis labels, tick values, legends, and text annotations (keep tick marks & axis lines)
    for ax in fig.axes:
        ax.set_title("")
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(
            which="both",
            bottom=True, left=True,
            labelbottom=False, labelleft=False, labelright=False, labeltop=False,
        )
        if ax.get_legend():
            ax.get_legend().remove()
        for t in ax.texts:
            t.set_visible(False)

    for lg in list(fig.legends):
        lg.remove()
    if fig._suptitle is not None:
        fig._suptitle.set_visible(False)

    # 3. Unlabelled version: transparent background, visible axes & tick marks, identical canvas alignment
    fig.patch.set_alpha(0.0)
    for ax in fig.axes:
        ax.patch.set_alpha(0.0)

    fig.savefig(
        out_dir / f"{stem}_unlabelled.png",
        dpi=dpi,
        transparent=True,
        facecolor="none",
    )
    plt.close(fig)
    print(f"  wrote {stem}_labelled.png & {stem}_unlabelled.png")


def style_top_header(fig, ax, title: str, ncol: int = 3, has_shifts: bool = False):
    """Place title, optional shift legend on top-right, and bench line legend below title with zero overlap."""
    handles, labels = ax.get_legend_handles_labels()
    n_items = len(handles)
    n_rows = max(1, math.ceil(n_items / max(1, ncol)))

    # Reserve enough vertical space at top for title + optional shift bar + bench legend rows
    top_margin = max(0.62, 0.88 - 0.045 * n_rows)
    fig.subplots_adjust(left=0.10, right=0.98, bottom=0.13, top=top_margin)

    fig.suptitle(title, x=0.10, y=0.97, ha="left", va="top", fontsize=9.5, fontweight="bold", color=fc.INK)

    if has_shifts:
        shift_handles = [
            Patch(facecolor=SHIFT_COLORS[s], edgecolor="none", alpha=0.45, label=f"{s} shift")
            for s in SHIFT_ORDER
        ]
        fig.legend(
            handles=shift_handles,
            loc="upper right",
            bbox_to_anchor=(0.98, 0.975),
            ncol=3,
            frameon=False,
            fontsize=6.8,
            columnspacing=1.0,
            handlelength=1.2,
        )

    if handles:
        fig.legend(
            handles,
            labels,
            loc="upper left",
            bbox_to_anchor=(0.10, 0.91),
            ncol=ncol,
            frameon=False,
            fontsize=7.0,
            columnspacing=1.4,
            handlelength=1.8,
        )


def _shift_spans():
    """(start_hour, end_hour, label) within one 24 h day."""
    d0, d1 = fc.SHIFT_HOURS["Day"]
    e0, e1 = fc.SHIFT_HOURS["Evening"]
    return [
        (0, d0, "Night"),
        (d0, d1, "Day"),
        (e0, e1, "Evening"),
        (e1, 24, "Night"),
    ]


def shade_shifts(ax, n_days: int = 1):
    """Shade shift blocks without adding duplicate entries to the line legend."""
    for d in range(n_days):
        for s, e, name in _shift_spans():
            if e <= s:
                continue
            ax.axvspan(d * 24 + s, d * 24 + e, color=SHIFT_COLORS[name], alpha=0.28, lw=0, zorder=0)


def _band(ax, x, frame: pd.DataFrame, color, label):
    """frame: rows = replications, columns = x bins. Mean line + 2.5-97.5% band across replications."""
    ax.plot(x, frame.mean(axis=0), color=color, lw=1.6, label=label, zorder=3)
    ax.fill_between(x, frame.quantile(0.025), frame.quantile(0.975), color=color, alpha=0.16, lw=0, zorder=2)


def _hourly_by_rep(state: pd.DataFrame, series: dict) -> dict:
    """series name -> DataFrame(rows=rep, cols=hour of day) of mean value."""
    hour = ((state["Minute"] % 1440) // 60).astype(int)
    out = {}
    for name, s in series.items():
        out[name] = s.groupby([state["rep"], hour]).mean().unstack()
    return out


def compute_mean_daily_specimens(mc_dir: Path, n_days: float) -> float:
    """Compute average daily arriving specimens across replications from specimens_*.csv.gz."""
    spec_files = sorted(glob.glob(str(mc_dir / "replications" / "specimens_*.csv.gz")))
    if not spec_files or n_days <= 0:
        return np.nan
    counts = []
    for f in spec_files:
        d = pd.read_csv(f, usecols=["In_Window"], low_memory=False)
        counts.append(float(d["In_Window"].astype(bool).sum()) / n_days)
    return float(np.mean(counts)) if counts else np.nan


def load_state_window(mc_dir):
    path = Path(mc_dir)
    rt_path = path / "run_table.csv"
    w0_min, w1_min = 0.0, np.inf
    if rt_path.exists():
        rt = pd.read_csv(rt_path)
        w0_min = float(rt["window_start_min"].iloc[0]) if "window_start_min" in rt else 0.0
        w1_min = float(rt["window_end_min"].iloc[0]) if "window_end_min" in rt else np.inf

    files = sorted(glob.glob(str(path / "replications" / "state_*.csv.gz")))
    if not files:
        raise SystemExit(f"No state_*.csv.gz files found in {path / 'replications'}")

    frames = []
    for f in files:
        d = pd.read_csv(f, low_memory=False)
        d["rep"] = int(re.findall(r"(\d+)", Path(f).name)[0])
        if "Minute" not in d.columns and "Hour" in d.columns:
            d["Minute"] = d["Hour"] * 60.0
        if "Day" not in d.columns:
            d["Day"] = (d["Minute"] // 1440).astype(int)
        frames.append(d)

    st = pd.concat(frames, ignore_index=True)
    if np.isfinite(w1_min):
        st = st[(st["Minute"] >= w0_min) & (st["Minute"] < w1_min)].copy()
    else:
        w1_min = float(st["Minute"].max()) + 1.0
        st = st[st["Minute"] >= w0_min].copy()

    st["day_rel"] = (st["Day"] - int(w0_min // 1440)).astype(int)
    hod = ((st["Minute"] % 1440) // 60).astype(int)
    st["shift"] = fc.shift_of_hour(hod)
    n_days = max((w1_min - w0_min) / 1440.0, 1.0)
    return st, (w0_min, w1_min), n_days


def extract_individual_series(state: pd.DataFrame):
    """Build clean percentage utilization (0-100%) and raw queue series for individual benches only."""
    util_series = {}
    for b, label in BENCH_LABELS.items():
        in_col, cap_col = f"Res_{b}_in_use", f"Res_{b}_capacity"
        if in_col in state.columns and cap_col in state.columns:
            cap = state[cap_col].replace(0, np.nan).astype(float)
            util_series[label] = 100.0 * state[in_col].astype(float) / cap

    queue_cols = [
        c for c in state.columns
        if re.search(r"queue|waiting", c, re.IGNORECASE)
        and not EXCLUDE_COLS_PATTERN.search(c)
    ]
    queue_series = {}
    for c in queue_cols:
        label = QUEUE_LABELS.get(c, c.replace("_Queue_Length", "").replace("_", " "))
        if label in queue_series:
            label = f"{label} ({c})"
        queue_series[label] = state[c].astype(float)

    return util_series, queue_series


def plot_all_separate(state: pd.DataFrame, window, n_days: float, rep: int, days: int, out_dir: Path, mc_dir: Path):
    util_series, queue_series = extract_individual_series(state)
    print(f"  individual bench utilization series ({len(util_series)}): {list(util_series)}")
    print(f"  individual queue series ({len(queue_series)}): {list(queue_series)}")

    # ------------------------------------------------------------------
    # 1. Daily mean utilization by bench across simulation days (FigS5B)
    # ------------------------------------------------------------------
    daily_records = []
    for b, label in BENCH_LABELS.items():
        in_col, cap_col = f"Res_{b}_in_use", f"Res_{b}_capacity"
        if in_col in state.columns and cap_col in state.columns:
            active = state[state[cap_col] > 0].copy()
            active["util_pct"] = 100.0 * active[in_col] / active[cap_col]
            g = active.groupby(["day_rel", "shift"])["util_pct"].mean().reset_index()
            g["bench"] = label
            daily_records.append(g)

    if daily_records:
        df_util = pd.concat(daily_records, ignore_index=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        df_util.to_csv(out_dir / "table_s5bc_utilization_over_time.csv", index=False, float_format="%.2f")

        fig_b, ax_b = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
        by_bench = df_util.groupby(["day_rel", "bench"])["util_pct"].mean().unstack("bench")
        for i, label in enumerate([lbl for lbl in BENCH_LABELS.values() if lbl in by_bench.columns]):
            ax_b.plot(by_bench.index, by_bench[label], label=label, color=DISTINCT_COLORS[i % len(DISTINCT_COLORS)], lw=1.4)
        ax_b.set_ylabel("Mean utilisation (%)")
        ax_b.set_xlabel("Measured simulation day")
        ax_b.set_ylim(0, 105)
        ax_b.grid(alpha=0.35)
        style_top_header(fig_b, ax_b, "Daily bench utilisation across simulation window", ncol=LEGEND_COLUMNS, has_shifts=False)
        save_both(fig_b, "FigS5B_daily_utilization_by_bench", out_dir, dpi=DPI)

        # ------------------------------------------------------------------
        # 2. Daily mean utilization by shift across simulation days (FigS5C)
        # ------------------------------------------------------------------
        fig_c, ax_c = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
        shift_line_colors = {"Day": fc.SIM_C, "Evening": fc.OBS24_C, "Night": fc.INK2}
        by_shift = df_util.groupby(["day_rel", "shift"])["util_pct"].mean().unstack("shift")
        for sh in ("Day", "Evening", "Night"):
            if sh in by_shift.columns:
                ax_c.plot(by_shift.index, by_shift[sh], label=f"{sh} shift", color=shift_line_colors[sh], lw=1.6)
        ax_c.set_ylabel("Mean utilisation (%)")
        ax_c.set_xlabel("Measured simulation day")
        ax_c.set_ylim(0, 105)
        ax_c.grid(alpha=0.35)
        style_top_header(fig_c, ax_c, "Mean bench utilisation by shift across simulation window", ncol=3, has_shifts=False)
        save_both(fig_c, "FigS5C_daily_utilization_by_shift", out_dir, dpi=DPI)

    # ------------------------------------------------------------------
    # 3. Folded 24 h bench utilization (mean & 95% band) (FigS5D)
    # ------------------------------------------------------------------
    if util_series:
        fig_d, ax_d = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
        shade_shifts(ax_d)
        for k, (name, frame) in enumerate(_hourly_by_rep(state, util_series).items()):
            _band(ax_d, frame.columns.values + 0.5, frame, DISTINCT_COLORS[k % len(DISTINCT_COLORS)], name)
        ax_d.set_xlim(0, 24)
        ax_d.set_xticks(range(0, 25, 3))
        ax_d.set_ylim(0, 105)
        ax_d.set_xlabel("Hour of day")
        ax_d.set_ylabel("Utilisation (%)")
        ax_d.grid(alpha=0.35)
        style_top_header(fig_d, ax_d, "Bench utilisation by hour of day (mean, 95% band)", ncol=LEGEND_COLUMNS, has_shifts=True)
        save_both(fig_d, "FigS5D_utilization_by_hour", out_dir, dpi=DPI)

        # ------------------------------------------------------------------
        # 4. Single-replication utilization timeline (FigS5E)
        # ------------------------------------------------------------------
        t0 = math.floor(window[0] / 1440.0) * 1440.0
        r = state[(state["rep"] == rep) & (state["Minute"] >= t0) & (state["Minute"] < t0 + days * 1440)]
        if not r.empty:
            fig_e, ax_e = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
            shade_shifts(ax_e, n_days=days)
            for k, (name, s) in enumerate(util_series.items()):
                ax_e.plot((r["Minute"] - t0) / 60.0, s.loc[r.index], color=DISTINCT_COLORS[k % len(DISTINCT_COLORS)], lw=1.2, label=name)
            ax_e.set_xlim(0, days * 24)
            ax_e.set_xticks(range(0, days * 24 + 1, 24))
            ax_e.set_ylim(0, 105)
            ax_e.set_xlabel(f"Hours since start of measurement window (replication {rep})")
            ax_e.set_ylabel("Utilisation (%)")
            ax_e.grid(alpha=0.35)
            style_top_header(fig_e, ax_e, f"Bench utilisation over time (replication {rep})", ncol=LEGEND_COLUMNS, has_shifts=True)
            save_both(fig_e, "FigS5E_utilization_timeline", out_dir, dpi=DPI)
        else:
            print(f"  SKIPPED timeline plot: no state rows found for replication {rep}")

    # ------------------------------------------------------------------
    # 5. Folded 24 h queue length by bench (normalized %) (FigS5F)
    # ------------------------------------------------------------------
    if queue_series:
        # Rank benches by raw mean queue length, keeping non-zero queues
        non_empty = [c for c in queue_series if queue_series[c].max() > 0]
        top = sorted(non_empty, key=lambda c: -queue_series[c].mean())[:TOP_N_QUEUES]

        norm_qseries = {}
        if QUEUE_NORM_MODE == "daily_specimens":
            daily_spec = compute_mean_daily_specimens(mc_dir, n_days)
            if not np.isfinite(daily_spec) or daily_spec <= 0:
                raise SystemExit("Could not compute daily specimens for QUEUE_NORM_MODE='daily_specimens'.")
            for name in top:
                norm_qseries[name] = 100.0 * queue_series[name] / daily_spec
            y_label = "Queue length (% of daily specimens)"
            title_txt = "Relative queue length by hour of day (% of daily specimens)"
        else:
            # Normalize each bench by its 99th-percentile / peak queue length so small and large benches share a 0-100% scale
            for name in top:
                peak = float(queue_series[name].max())
                norm_qseries[name] = 100.0 * queue_series[name] / max(peak, 1.0)
            y_label = "Queue length (% of bench peak)"
            title_txt = "Normalized queue length by hour of day (% of bench peak)"

        fig_f, ax_f = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
        shade_shifts(ax_f)
        for k, name in enumerate(top):
            frame = _hourly_by_rep(state, {name: norm_qseries[name]})[name]
            _band(ax_f, frame.columns.values + 0.5, frame, DISTINCT_COLORS[k % len(DISTINCT_COLORS)], name)
        ax_f.set_xlim(0, 24)
        ax_f.set_xticks(range(0, 25, 3))
        ax_f.set_ylim(0, 105)
        ax_f.set_xlabel("Hour of day")
        ax_f.set_ylabel(y_label)
        ax_f.grid(alpha=0.35)
        style_top_header(fig_f, ax_f, title_txt, ncol=LEGEND_COLUMNS, has_shifts=True)
        save_both(fig_f, "FigS5F_queue_by_hour", out_dir, dpi=DPI)


def main():
    fc.apply_style()
    st, window, n_days = load_state_window(MC_DIR)
    plot_all_separate(
        state=st,
        window=window,
        n_days=n_days,
        rep=TIMELINE_REP,
        days=TIMELINE_DAYS,
        out_dir=OUTPUT_DIR,
        mc_dir=MC_DIR,
    )
    print(f"\nDone. Separate figures saved in {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()