#!/usr/bin/env python3
"""
Standalone script to generate Figure S3 (Bench Utilization Heatmap) from simulation state logs.

Usage:
    python FigS3_BenchUtilization.py --mc-dir results_experiments/mc_my_run [--out manuscript_png] [--bare]
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
OUTPUT_DIR = Path("manuscript_png")          # where the PNGs (and table2_validation.csv) go
PNG_WIDTH = 4.2                              # inches
LEFT_MARGIN_IN = 1.75                        # room for the y-axis labels (inches); raise it if a label is cut off
LEGEND_COLUMNS = 1
PNG_HEIGHT = None                            # inches; None = automatic from the number of rows (0.3 in per row + 1.4)
DPI = 300
BARE = False                                 # True: the unlabelled version also loses the legend and in-plot text

MC_DIR = "results_experiments/mc_gerada_gram"                       # Monte Carlo folder (has replications/ and run_table.csv)
OBS_2025 = ["data/observed_2025_lis_clean.csv"]                     # list of RAW LIS files (tuned / calibration year)
OBS_2024 = ["data/observed_2024_lis_clean.csv"]                                                       # list of RAW LIS files (held-out validation year); [] = none
OBS_EXCLUDE = None                                                  # drop LIS rows whose source file name contains this text

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
DPI = 300

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.8,
    "xtick.major.width": 0.8, "ytick.major.width": 0.8, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.5, "axes.axisbelow": True, "figure.facecolor": "white", "axes.facecolor": "white",
    "pdf.fonttype": 42, "svg.fonttype": "none",
})

OUT = Path("manuscript_png")
BARE = False


# ----------------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------------
def shift_of_hour(h):
    h = np.asarray(h)
    return np.where((h >= SHIFT_HOURS["Day"][0]) & (h < SHIFT_HOURS["Day"][1]), "Day",
                    np.where((h >= SHIFT_HOURS["Evening"][0]) & (h < SHIFT_HOURS["Evening"][1]), "Evening", "Night"))


def save_both(fig, stem):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{stem}_labelled.png", dpi=DPI, facecolor="white")
    for ax in fig.axes:
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(labelbottom=False, labelleft=False, labelright=False, labeltop=False)
        if BARE:
            ax.set_title("")
            if ax.get_legend():
                ax.get_legend().remove()
            for t in ax.texts:
                t.set_visible(False)
    if BARE:
        for lg in list(fig.legends):
            lg.remove()
    fig.savefig(OUT / f"{stem}_unlabelled.png", dpi=DPI, facecolor="white")
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
    
    fig = plt.figure(figsize=(5.0, 0.3 * len(benches) + 1.1))
    ax = fig.add_axes([0.30, 0.17, 0.55, 0.72])
    cax = fig.add_axes([0.88, 0.17, 0.025, 0.72])
    
    im = ax.imshow(np.ma.masked_invalid(M), cmap=cmap, vmin=0, vmax=100, aspect="auto")
    ax.grid(False)
    ax.set_xticks(range(0, 24, 3))
    ax.set_yticks(range(len(benches)))
    ax.set_yticklabels([BENCH_LABELS[b] for b in benches])
    
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    
    cb = fig.colorbar(im, cax=cax)
    cb.outline.set_visible(False)
    cb.ax.tick_params(length=2, labelsize=7)
    cb.set_label("Utilisation (%)")
    cb.ax.grid(False)
    
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Bench")
    
    save_both(fig, "05_utilization_heatmap")


# ----------------------------------------------------------------------------
# MAIN EXECUTION
# ----------------------------------------------------------------------------
def main():
    global OUT, BARE
    ap = argparse.ArgumentParser(description="Generate bench utilization heatmap figure from simulation state logs.")
    ap.add_argument("--mc-dir", required=True, help="Path to Monte Carlo run directory or a direct state CSV file.")
    ap.add_argument("--out", default="manuscript_png", help="Output directory for generated PNGs.")
    ap.add_argument("--bare", action="store_true", help="Unlabelled versions also drop legends, panel titles, and in-plot text.")
    args = ap.parse_args()

    OUT = Path(args.out)
    BARE = args.bare

    print(f"Loading state logs from {args.mc_dir}...")
    st = load_state(args.mc_dir)
    print(f"Loaded {len(st):,} state records. Generating utilization heatmap...")
    fig_utilization_heatmap(st)
    print(f"\nDone. Figures saved in {OUT}/")


if __name__ == "__main__":
    main()