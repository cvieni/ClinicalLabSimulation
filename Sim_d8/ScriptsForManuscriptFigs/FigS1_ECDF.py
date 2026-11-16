#!/usr/bin/env python3
"""
Standalone script to generate individual ECDF figures by combined specimen groups,
comparing simulation against LIS 2025 and optional LIS 2024 data.

Usage:
    python figS1_ECDF.py \
        --mc-dir results_experiments/mc_my_run \
        --obs-2025 data/observed_2025_lis_clean.csv \
        [--obs-2024 data/observed_2024_lis_clean.csv] \
        [--obs-exclude UofU] \
        [--out manuscript_png/FigS1_ECDF] [--bare]
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
from matplotlib.lines import Line2D
from scipy import stats

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
# CONFIG & COMBINED GROUP DEFINITIONS (Edit combinations here)
# ----------------------------------------------------------------------------
ECDF_GROUPS = {
    "Blood culture": [
        "BCx"
    ],
    "Body fluid": [
        "BodyFluid"
    ],
    "Bone": [
        "Bone_Cx"
    ],
    "Wound & Tissue": [
        "Tissue", "Tissue_FNA", "Tissue_genital", "Wound", "Wound_Genital"
    ],
    "Stool": [
        "Stool", "Stool_Ecoli", "Stool_EcoliRoutine", "Stool_Campy", "Stool_Vibrio", "Stool_Yersinia",
        "Stool 60134 (E. coli)", "Stool 60135 (Campylobacter)", "Stool 60136 (Vibrio)", "Stool 60137 (Yersinia)"
    ],
    "Respiratory": [
        "Respiratory", "Resp_NonCF", "Resp_CystFibrosis", "Resp_CF"
    ],
    "Urine": [
        "Urine_Invasive", "Urine_NonInvasive"
    ],
}

# Automatically map simulation types to their combined group
SIM_TO_GROUP = {s: g for g, ss in ECDF_GROUPS.items() for s in ss}

# Map LIS observation labels to the new combined groups
OBS_TO_GROUP = {
    "bloodculture": "Blood culture", 
    "bodyfluid": "Body fluid", 
    "bone": "Bone", 
    "tissue": "Wound & Tissue",
    "fnatissue": "Wound & Tissue", 
    "genitaltissue": "Wound & Tissue", 
    "wound": "Wound & Tissue",
    "genitalwound": "Wound & Tissue", 
    "woundgenital": "Wound & Tissue", 
    "stool": "Stool",
    "respiratory": "Respiratory", 
    "respiratorynoncf": "Respiratory", 
    "respnoncf": "Respiratory", 
    "noncf": "Respiratory",
    "respiratorycf": "Respiratory", 
    "respcf": "Respiratory", 
    "cf": "Respiratory", 
    "cysticfibrosis": "Respiratory", 
    "invasiveurine": "Urine", 
    "urineinvasive": "Urine",
    "noninvasiveurine": "Urine", 
    "urinenoninvasive": "Urine",
    "urine": "Urine"
}

STOOL_SPLIT = {
    "60134": "Stool 60134 (E. coli)", "60135": "Stool 60135 (Campylobacter)",
    "60136": "Stool 60136 (Vibrio)", "60137": "Stool 60137 (Yersinia)"
}
SIM_STOOL_CODE = {
    "Stool_Ecoli": "60134", "Stool_EcoliRoutine": "60134", "Stool_Campy": "60135", 
    "Stool_Vibrio": "60136", "Stool_Yersinia": "60137"
}

INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SIM_C, OBS_C, OBS24_C = "#2a78d6", "#0b0b0b", "#eb6834"
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

OUT = Path("manuscript_png/FigS1_ECDF")
BARE = False


# ----------------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------------
def norm(s):
    return re.sub(r"[^a-z]", "", str(s).lower())


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


def _code(x):
    return re.sub(r"\.0+$", "", str(x).strip()).lstrip("0")


def _find_col(d, wanted):
    low = {c.lower(): c for c in d.columns}
    for w in wanted:
        if w.lower() in low:
            return low[w.lower()]
    return None


def with_stool_split(df, kind):
    if df is None:
        return None
    if kind == "sim":
        code = df["Type"].map(SIM_STOOL_CODE)
    else:
        ocol = _find_col(df, ["order_num", "order_number", "ordernum", "test_code", "order_code"])
        if ocol is None:
            return df
        code = df[ocol].map(_code).where(df["group"] == "Stool")
    sub = df[code.isin(STOOL_SPLIT)].copy()
    if sub.empty:
        return df
    sub["group"] = code[sub.index].map(STOOL_SPLIT)
    return pd.concat([df, sub], ignore_index=True)


def load_sim(mc_dir):
    mc = Path(mc_dir)
    rt = pd.read_csv(mc / "run_table.csv")
    w0 = float(rt["window_start_min"].iloc[0]) if "window_start_min" in rt else 0.0
    w1 = float(rt["window_end_min"].iloc[0]) if "window_end_min" in rt else np.inf
    frames = []
    for f in sorted(glob.glob(str(mc / "replications" / "specimens_*.csv.gz"))):
        d = pd.read_csv(f, low_memory=False)
        if "rep" not in d.columns:
            d["rep"] = int(re.findall(r"(\d+)", Path(f).name)[0])
        d = d[d["In_Window"].astype(bool) & d["Total_TAT_Hours"].notna()]
        frames.append(d[["Type", "Arrival_Minute", "Total_TAT_Hours", "Arrival_Shift", "Outcome", "rep"]])
    if not frames:
        raise SystemExit(f"No replications/specimens_*.csv.gz found in {mc}")
    s = pd.concat(frames, ignore_index=True)
    s["group"] = s["Type"].map(SIM_TO_GROUP)
    s = s.dropna(subset=["group"])
    s["tat_h"] = s["Total_TAT_Hours"].astype(float)
    return s


def load_obs(paths, exclude=None):
    frames = []
    for path in ([paths] if isinstance(paths, str) else paths):
        d = pd.read_csv(path, low_memory=False)
        tcol = _find_col(d, ["TAT_Hours", "tat_hours", "Total_TAT_Hours", "TAT", "tat_h"])
        if tcol is None:
            raise SystemExit(f"{path}: no TAT column found.")
        d = d.rename(columns={tcol: "TAT_Hours"})
        scol = _find_col(d, ["specimen_type", "Type", "specimen"])
        if scol is None:
            raise SystemExit(f"{path}: no specimen_type column found.")
        d["group"] = d[scol].map(lambda x: OBS_TO_GROUP.get(norm(x)))
        d = d.dropna(subset=["group"])
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    if exclude and "source_file" in d.columns:
        keep = ~d["source_file"].astype(str).str.contains(exclude, case=False, regex=False)
        d = d[keep]
    d["tat_h"] = pd.to_numeric(d["TAT_Hours"], errors="coerce")
    d = d.dropna(subset=["tat_h"])
    return d


# ----------------------------------------------------------------------------
# INDIVIDUAL ECDF GENERATION PER COMBINED GROUP
# ----------------------------------------------------------------------------
def generate_individual_ecdgs(sim, obs25, obs24):
    groups = [g for g in ECDF_GROUPS if g in set(sim["group"])]
    
    for g in groups:
        fig, ax = plt.subplots(figsize=(3.5, 3.0))
        fig.subplots_adjust(left=0.15, right=0.95, bottom=0.15, top=0.85)
        
        s = np.sort(sim[sim.group == g]["tat_h"].values)
        allv = [s]
        
        # Plot simulation ECDF
        if len(s) > 0:
            ax.step(s, np.arange(1, len(s) + 1) / len(s), where="post", color=SIM_C, linewidth=1.4, label="Simulated")
        
        # Plot LIS 2025 ECDF
        if obs25 is not None and g in set(obs25["group"]):
            v25 = np.sort(obs25[obs25.group == g]["tat_h"].values)
            if len(v25) > 0:
                allv.append(v25)
                ax.step(v25, np.arange(1, len(v25) + 1) / len(v25), where="post", color=OBS_C, linewidth=1.2, linestyle="--", label="LIS 2025")
        
        # Plot LIS 2024 ECDF
        if obs24 is not None and g in set(obs24["group"]):
            v24 = np.sort(obs24[obs24.group == g]["tat_h"].values)
            if len(v24) > 0:
                allv.append(v24)
                ax.step(v24, np.arange(1, len(v24) + 1) / len(v24), where="post", color=OBS24_C, linewidth=1.2, linestyle=":", label="LIS 2024")
                
        if allv:
            cat = np.concatenate(allv)
            lo, hi = np.percentile(cat, 0.5), np.percentile(cat, 99.8)
            pad = 0.04 * (hi - lo)
            ax.set_xlim(max(0, lo - pad), hi + pad)
            
        ax.set_ylim(0, 1.02)
        ax.set_title(g, fontsize=8, fontweight="bold")
        ax.set_xlabel("TAT (h)")
        ax.set_ylabel("Cumulative proportion")
        
        # Compute and annotate KS statistic vs LIS 2025 if available
        if obs25 is not None and g in set(obs25["group"]) and len(s) > 0:
            x = obs25[obs25.group == g]["tat_h"].values
            if len(x) > 0:
                rng = np.random.default_rng(0)
                ks = stats.ks_2samp(rng.choice(s, min(len(s), 20000), replace=False),
                                    rng.choice(x, min(len(x), 20000), replace=False)).statistic
                ax.text(0.05, 0.90, f"D = {ks:.2f}", transform=ax.transAxes, ha="left", va="top", fontsize=7, color=INK2)
                
        h, l = ax.get_legend_handles_labels()
        ax.legend(h, l, loc="lower right", frameon=False, fontsize=7)
        
        # Create safe filename from group name
        safe_name = re.sub(r"[^A-Za-z0-9]+", "_", g).strip("_")
        save_both(fig, f"ecdf_{safe_name}")


# ----------------------------------------------------------------------------
# MAIN EXECUTION
# ----------------------------------------------------------------------------
def main():
    global OUT, BARE
    ap = argparse.ArgumentParser(description="Generate individual ECDF figures for combined specimen groups.")
    ap.add_argument("--mc-dir", required=True, help="Path to Monte Carlo run directory.")
    ap.add_argument("--obs-2025", nargs="+", help="One or more LIS 2025 CSV files.")
    ap.add_argument("--obs-2024", nargs="+", help="One or more LIS 2024 CSV files.")
    ap.add_argument("--obs-exclude", default=None, help="Drop LIS rows whose source file name contains this text.")
    ap.add_argument("--out", default="manuscript_png/FigS1_ECDF", help="Output directory for generated PNGs.")
    ap.add_argument("--bare", action="store_true", help="Unlabelled versions also drop legends, panel titles, and text.")
    args = ap.parse_args()

    OUT = Path(args.out)
    BARE = args.bare

    print(f"Loading simulation specimens from {args.mc_dir}...")
    sim = load_sim(args.mc_dir)
    obs25 = load_obs(args.obs_2025, args.obs_exclude) if args.obs_2025 else None
    obs24 = load_obs(args.obs_2024, args.obs_exclude) if args.obs_2024 else None

    print("Splitting stool categories by order code...")
    simv = with_stool_split(sim, "sim")
    obs25v = with_stool_split(obs25, "obs")
    obs24v = with_stool_split(obs24, "obs")

    print(f"Generating individual ECDF figures in {OUT}/...")
    generate_individual_ecdgs(simv, obs25v, obs24v)
    print(f"\nDone. All figures saved in {OUT}/")


if __name__ == "__main__":
    main()