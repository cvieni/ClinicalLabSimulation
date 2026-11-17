#!/usr/bin/env python3
"""Figure S5B/C: Bench utilization over simulation days (overall and by shift) from state_*.csv.gz.
Run: python FigS5BC_utilizationOverTime.py"""
import glob
import re
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import fig_common as fc

# =========================================================== SETTINGS ===========================================================

# Research/ClinicalLabSimulation
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# Research/ClinicalLabSimulation/Sim_d8
SIM_DIR = Path(__file__).resolve().parent.parent
# Research/ClinicalLabSimulation/Sim_d8/manuscript_png
OUTPUT_DIR = Path(SIM_DIR, "manuscript_png/FigS5_UtilizationTime")         
MC_DIR = Path(SIM_DIR, "results_experiments/scn_baseline")

OBS_2025 = Path(SIM_DIR, "data/observed_2025_lis_clean.csv")
OBS_2024 = Path(SIM_DIR, "data/observed_2024_lis_clean.csv") 


PNG_WIDTH = 5.5
PNG_HEIGHT = 4.6
DPI = 300
BARE = False
LEGEND_COLUMNS = 3

figure_margin_size = 0.0
set_background_transparent = True

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
# ================================================================================================================================


def save_both(fig, stem, out_dir: Path, dpi: int = 300, bare: bool = False):
    """Save <stem>_labelled.png and <stem>_unlabelled.png with transparent background and zero margin."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        out_dir / f"{stem}_labelled.png",
        dpi=dpi,
        transparent=set_background_transparent,
        facecolor="none" if set_background_transparent else "white",
        edgecolor="none",
        bbox_inches="tight" if figure_margin_size == 0.0 else None,
        pad_inches=0.0,
    )

    for ax in fig.axes:
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(
            which="both",
            bottom=True, left=True,
            labelbottom=False, labelleft=False, labelright=False, labeltop=False,
        )
        if bare:
            ax.set_title("")
            if ax.get_legend():
                ax.get_legend().remove()
            for t in ax.texts:
                t.set_visible(False)

    if bare:
        for lg in list(fig.legends):
            lg.remove()
        if fig._suptitle is not None:
            fig._suptitle.set_visible(False)

    fig.savefig(
        out_dir / f"{stem}_unlabelled.png",
        dpi=dpi,
        transparent=set_background_transparent,
        facecolor="none" if set_background_transparent else "white",
        edgecolor="none",
        bbox_inches="tight" if figure_margin_size == 0.0 else None,
        pad_inches=0.0,
    )
    plt.close(fig)
    print(f"  wrote {stem}_labelled.png & {stem}_unlabelled.png")


def load_state_daily(mc_dir):
    path = Path(mc_dir)
    rt_path = path / "run_table.csv"
    w0, w1 = 0.0, np.inf
    if rt_path.exists():
        rt = pd.read_csv(rt_path)
        w0 = float(rt["window_start_min"].iloc[0]) / 1440 if "window_start_min" in rt else 0.0
        w1 = float(rt["window_end_min"].iloc[0]) / 1440 if "window_end_min" in rt else np.inf

    files = sorted(glob.glob(str(path / "replications" / "state_*.csv.gz")))
    if not files:
        raise SystemExit(f"No state_*.csv.gz files found in {path / 'replications'}")

    frames = []
    for f in files:
        d = pd.read_csv(f, low_memory=False)
        d["rep"] = int(re.findall(r"(\d+)", Path(f).name)[0])
        if "Day" not in d.columns and "Minute" in d.columns:
            d["Day"] = (d["Minute"] // 1440).astype(int)
        d = d[(d["Day"] >= w0) & (d["Day"] < w1)].copy()
        d["day_rel"] = (d["Day"] - int(w0)).astype(int)

        if "Hour" in d.columns:
            hod = (d["Hour"] % 24).astype(int)
        elif "Minute" in d.columns:
            hod = ((d["Minute"] % 1440) // 60).astype(int)
        else:
            raise KeyError("State file must contain 'Hour' or 'Minute'.")
        d["shift"] = fc.shift_of_hour(hod)
        frames.append(d)

    return pd.concat(frames, ignore_index=True)


def main():
    fc.apply_style()
    if set_background_transparent:
        plt.rcParams.update({"figure.facecolor": "none", "axes.facecolor": "none"})

    st = load_state_daily(MC_DIR)

    benches = [b for b in BENCH_LABELS if f"Res_{b}_in_use" in st and f"Res_{b}_capacity" in st]
    if not benches:
        raise SystemExit("No Res_<bench>_in_use / Res_<bench>_capacity columns found in state logs.")

    daily_records = []
    for b in benches:
        active = st[st[f"Res_{b}_capacity"] > 0].copy()
        active["util_pct"] = 100.0 * active[f"Res_{b}_in_use"] / active[f"Res_{b}_capacity"]
        g = active.groupby(["day_rel", "shift"])["util_pct"].mean().reset_index()
        g["bench"] = BENCH_LABELS[b]
        daily_records.append(g)

    df_util = pd.concat(daily_records, ignore_index=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df_util.to_csv(OUTPUT_DIR / "table_s5bc_utilization_over_time.csv", index=False, float_format="%.2f")

    fig, axes = plt.subplots(2, 1, figsize=(PNG_WIDTH, PNG_HEIGHT), sharex=True)
    fig.subplots_adjust(left=0.12, right=0.97, bottom=0.11, top=0.80, hspace=0.35)

    # Panel B: Daily mean utilization by bench (averaged across shifts)
    ax = axes[0]
    by_bench = df_util.groupby(["day_rel", "bench"])["util_pct"].mean().unstack("bench")
    for i, label in enumerate([BENCH_LABELS[b] for b in benches if BENCH_LABELS[b] in by_bench.columns]):
        color = fc.FALLBACK_PALETTE[i % len(fc.FALLBACK_PALETTE)]
        ax.plot(by_bench.index, by_bench[label], label=label, color=color, linewidth=1.2)
    ax.set_ylabel("Mean utilisation (%)")
    ax.set_title("B. Daily bench utilisation across simulation window", loc="left", fontsize=8, fontweight="bold")
    ax.set_ylim(0, 105)

    # Panel C: Mean utilization across all benches by shift
    ax = axes[1]
    shift_colors = {"Day": fc.SIM_C, "Evening": fc.OBS24_C, "Night": fc.INK2}
    by_shift = df_util.groupby(["day_rel", "shift"])["util_pct"].mean().unstack("shift")
    for sh in ("Day", "Evening", "Night"):
        if sh in by_shift.columns:
            ax.plot(by_shift.index, by_shift[sh], label=f"{sh} shift", color=shift_colors[sh], linewidth=1.4)
    ax.set_ylabel("Mean utilisation (%)")
    ax.set_xlabel("Measured simulation day")
    ax.set_title("C. Mean bench utilisation by shift", loc="left", fontsize=8, fontweight="bold")
    ax.set_ylim(0, 105)
    ax.legend(loc="upper right", frameon=False, ncol=3)

    fc.top_legend(axes[0], ncol=LEGEND_COLUMNS)
    save_both(fig, "FigS5BC_utilization_over_time", OUTPUT_DIR, dpi=DPI, bare=BARE)


if __name__ == "__main__":
    main()