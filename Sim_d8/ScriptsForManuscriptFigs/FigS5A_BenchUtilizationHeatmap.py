#!/usr/bin/env python3
"""
Standalone script to generate Figure S5A (Bench Utilization Heatmap) from simulation state logs.

Usage:
    python FigS5A_BenchUtilizationHeatmap_2.py
    python FigS5A_BenchUtilizationHeatmap_2.py --mc-dir results_experiments/mc_my_run --out manuscript_png
"""
import argparse
import glob
import re
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap


# =========================================================== SETTINGS (edit these) ===========================================================
PNG_WIDTH = 5.0      
PNG_HEIGHT = 5.0
DPI = 300

# Research/ClinicalLabSimulation
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# Research/ClinicalLabSimulation/Sim_d8
SIM_DIR = Path(__file__).resolve().parent.parent
# Research/ClinicalLabSimulation/Sim_d8/manuscript_png
OUTPUT_DIR = Path(SIM_DIR, "manuscript_png/FigS5A_Util_heatmap")         
MC_DIR = Path(SIM_DIR, "results_experiments/scn_baseline")

# ==============================================================================================================================================



# ----------------------------------------------------------------------------
# CONFIG & STYLING
# ----------------------------------------------------------------------------
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
SHIFT_HOURS = {"Day": (7, 15), "Evening": (15, 23)}
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SEQ = LinearSegmentedColormap.from_list("blue_red", ["#1f5fb4", "#8ec1ee", "#f5f1e8", "#f2a38b", "#c62828"])

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.8,
    "xtick.bottom": True, "ytick.left": True,
    "xtick.major.width": 0.8, "ytick.major.width": 0.8,
    "xtick.major.size": 3.5, "ytick.major.size": 3.5,
    "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.5, "axes.axisbelow": True,
    "figure.facecolor": "white", "axes.facecolor": "white",
    "pdf.fonttype": 42, "svg.fonttype": "none",
})

OUT = OUTPUT_DIR


# ----------------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------------
def shift_of_hour(h):
    h = np.asarray(h)
    return np.where((h >= SHIFT_HOURS["Day"][0]) & (h < SHIFT_HOURS["Day"][1]), "Day",
                    np.where((h >= SHIFT_HOURS["Evening"][0]) & (h < SHIFT_HOURS["Evening"][1]), "Evening", "Night"))


def save_both(fig, stem, cax=None):
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. Labelled version: white background, visible axes, tick labels, and titles
    fig.patch.set_facecolor("white")
    fig.patch.set_alpha(1.0)
    for ax in fig.axes:
        ax.set_facecolor("white")
        ax.patch.set_alpha(1.0)
    fig.savefig(
        OUT / f"{stem}_labelled.png",
        dpi=DPI,
        transparent=False,
        facecolor="white",
    )

    # 2. Strip all text/labels/titles/legends and hide colorbar while keeping main axis tick marks
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

    if cax is not None:
        cax.set_visible(False)

    for lg in list(fig.legends):
        lg.remove()
    if fig._suptitle is not None:
        fig._suptitle.set_visible(False)

    # 3. Unlabelled version: transparent background, visible main axes & tick marks, no colorbar
    fig.patch.set_alpha(0.0)
    for ax in fig.axes:
        ax.patch.set_alpha(0.0)
    fig.savefig(
        OUT / f"{stem}_unlabelled.png",
        dpi=DPI,
        transparent=True,
        facecolor="none",
    )
    plt.close(fig)
    print(f"  wrote {stem}_labelled.png & {stem}_unlabelled.png")


def load_state(source_path):
    """Load state dataframe either from a Monte Carlo simulation directory or directly from a CSV file."""
    path = Path(source_path)
    if path.is_dir():
        rt_path = path / "run_table.csv"
        w0, w1 = 0.0, np.inf
        if rt_path.exists():
            rt = pd.read_csv(rt_path)
            w0 = float(rt["window_start_min"].iloc[0]) / 1440 if "window_start_min" in rt else 0.0
            w1 = float(rt["window_end_min"].iloc[0]) / 1440 if "window_end_min" in rt else np.inf

        frames = []
        for f in sorted(glob.glob(str(path / "replications" / "state_*.csv.gz"))):
            d = pd.read_csv(f, low_memory=False)
            d["rep"] = int(re.findall(r"(\d+)", Path(f).name)[0])
            if "Day" in d.columns:
                d = d[(d["Day"] >= w0) & (d["Day"] < w1)]
            frames.append(d)
        if not frames:
            raise SystemExit(f"No state_*.csv.gz files found in {path / 'replications'}")
        st = pd.concat(frames, ignore_index=True)
    else:
        st = pd.read_csv(path, low_memory=False)

    if "Hour" in st.columns:
        st["hod"] = (st["Hour"] % 24).astype(int)
    elif "Minute" in st.columns:
        st["hod"] = ((st["Minute"] % 1440) // 60).astype(int)
    elif "hod" not in st.columns:
        raise KeyError("State dataframe must contain 'Hour', 'Minute', or 'hod' column.")

    st["shift"] = shift_of_hour(st["hod"])
    return st


# ----------------------------------------------------------------------------
# CORE FUNCTION
# ----------------------------------------------------------------------------
def fig_utilization_heatmap(st):
    benches = [b for b in BENCH_LABELS if f"Res_{b}_in_use" in st and f"Res_{b}_capacity" in st]
    if not benches:
        print("Warning: No matching bench resource columns (Res_*_in_use / Res_*_capacity) found in state data.")

    M = np.full((len(benches), 24), np.nan)
    for i, b in enumerate(benches):
        d = st[st[f"Res_{b}_capacity"] > 0]
        u = (100 * d[f"Res_{b}_in_use"] / d[f"Res_{b}_capacity"]).groupby(d["hod"]).mean()
        M[i, u.index.values] = u.values

    cmap = SEQ.copy()
    cmap.set_bad("#f0efec")

    fig_h = PNG_HEIGHT if PNG_HEIGHT is not None else (0.3 * len(benches) + 1.1)
    fig = plt.figure(figsize=(PNG_WIDTH, fig_h))
    ax = fig.add_axes([0.30, 0.17, 0.55, 0.72])
    cax = fig.add_axes([0.88, 0.17, 0.025, 0.72])

    im = ax.imshow(np.ma.masked_invalid(M), cmap=cmap, vmin=0, vmax=100, aspect="auto")
    ax.grid(False)
    ax.set_xticks(range(0, 24, 3))
    ax.set_yticks(range(len(benches)))
    ax.set_yticklabels([BENCH_LABELS[b] for b in benches])

    # Keep bottom and left axis lines + tick marks visible
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_visible(True)
    ax.spines["left"].set_visible(True)
    ax.tick_params(bottom=True, left=True, length=3.5)

    cb = fig.colorbar(im, cax=cax)
    cb.outline.set_visible(True)
    cb.outline.set_linewidth(0.8)
    cb.outline.set_edgecolor(INK2)
    cb.ax.tick_params(length=2.5, labelsize=7)
    cb.set_label("Utilisation (%)")
    cb.ax.grid(False)

    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Bench")

    save_both(fig, "05_utilization_heatmap", cax=cax)


# ----------------------------------------------------------------------------
# MAIN EXECUTION
# ----------------------------------------------------------------------------
def main():
    global OUT
    ap = argparse.ArgumentParser(description="Generate bench utilization heatmap figure from simulation state logs.")
    ap.add_argument("--mc-dir", default=str(MC_DIR), help="Path to Monte Carlo run directory or a direct state CSV file.")
    ap.add_argument("--out", default=str(OUTPUT_DIR), help="Output directory for generated PNGs.")
    args = ap.parse_args()

    OUT = Path(args.out)

    print(f"Loading state logs from {args.mc_dir}...")
    st = load_state(args.mc_dir)
    print(f"Loaded {len(st):,} state records. Generating utilization heatmap...")
    fig_utilization_heatmap(st)
    print(f"\nDone. Figures saved in {OUT}/")


if __name__ == "__main__":
    main()