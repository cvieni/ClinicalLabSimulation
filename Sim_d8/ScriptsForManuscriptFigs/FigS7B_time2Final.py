#!/usr/bin/env python3
"""Figure S7B: Time-to-finalization ECDF by individual specimen type, combined ECDF_GROUPS,
and multi-curve overlay plots showing the combined total + constituent subtypes on the same panel.
Run: python FigS7B_time2Final.py"""
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
from matplotlib.lines import Line2D

import fig_common as fc

# =========================================================== SETTINGS (edit these) ===========================================================
BASE_DIR = Path(__file__).resolve().parent.parent.parent
SIM_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = SIM_DIR / "manuscript_png/FigS7B_time2Final"
MC_DIR = SIM_DIR / "results_experiments/scn_baseline"

PNG_WIDTH = 4.2
PNG_HEIGHT = 4.5
LEGEND_COLUMNS = 3
DPI = 300

# Fixed X and Y axis bounds & ticks for all figures (set to None for automatic scaling)
X_LIM = (0, 851)
X_TICKS = np.arange(0, 850, 100)

Y_LIM = (0, 1.0)
Y_TICKS = np.arange(0, 1.01, 0.2)

# Palette for constituent subtype lines in the overlay plots
SUBTYPE_PALETTE = [
    "#eb6834", "#1baf7a", "#9467bd", "#eda100", "#d62728", "#8c564b", "#17becf", "#e377c2"
]

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
    "Wound & Tissue": [
        "Tissue", "Tissue_FNA", "Tissue_genital", "Wound", "Wound_Genital", "Bone_Cx",
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

SIM_TO_GROUP = {s: g for g, ss in ECDF_GROUPS.items() for s in ss}

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
    "urine": "Urine",
}

STOOL_SPLIT = {
    "60134": "Stool 60134 (E. coli)", "60135": "Stool 60135 (Campylobacter)",
    "60136": "Stool 60136 (Vibrio)", "60137": "Stool 60137 (Yersinia)",
}
SIM_STOOL_CODE = {
    "Stool_Ecoli": "60134", "Stool_EcoliRoutine": "60134", "Stool_Campy": "60135",
    "Stool_Vibrio": "60136", "Stool_Yersinia": "60137",
}

INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SIM_C, OBS_C, OBS24_C = "#2a78d6", "#0b0b0b", "#eb6834"
# ==============================================================================================================================================


def save_both(fig, stem, out_dir: Path = OUTPUT_DIR, dpi: int = DPI):
    """Save <stem>_labelled.png (white bg, tight crop) and <stem>_unlabelled.png (transparent bg, tight crop around axes & ticks)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Labelled version: solid white background, visible axes, tick labels, text box, title, and legend
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
        edgecolor="none",
        bbox_inches="tight",
        pad_inches=0.04,
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

    # 3. Unlabelled version: transparent background, tight crop around axes & tick marks
    fig.patch.set_facecolor("none")
    fig.patch.set_alpha(0.0)
    for ax in fig.axes:
        ax.set_facecolor("none")
        ax.patch.set_alpha(0.0)

    fig.savefig(
        out_dir / f"{stem}_unlabelled.png",
        dpi=dpi,
        transparent=True,
        facecolor="none",
        edgecolor="none",
        bbox_inches="tight",
        pad_inches=0.02,
    )
    plt.close(fig)
    print(f"  wrote {stem}_labelled.png & {stem}_unlabelled.png")


def _apply_axes_bounds(ax):
    if X_LIM is not None:
        ax.set_xlim(*X_LIM)
    else:
        ax.set_xlim(left=0)
    if X_TICKS is not None:
        ax.set_xticks(X_TICKS)

    if Y_LIM is not None:
        ax.set_ylim(*Y_LIM)
    else:
        ax.set_ylim(0, 1.02)
    if Y_TICKS is not None:
        ax.set_yticks(Y_TICKS)

    ax.set_xlabel("Receipt to final report (h)")
    ax.set_ylabel("Cumulative proportion")


def _plot_ecdf_subset(df_sub: pd.DataFrame, label: str, stem: str) -> dict | None:
    x = pd.to_numeric(df_sub["tat_h"], errors="coerce").dropna().to_numpy()
    x = x[np.isfinite(x) & (x >= 0)]
    if len(x) == 0:
        return None

    rep_rows = []
    for rep, dr in df_sub.groupby("rep"):
        xr = pd.to_numeric(dr["tat_h"], errors="coerce").dropna().to_numpy()
        xr = xr[np.isfinite(xr) & (xr >= 0)]
        if len(xr):
            rep_rows.append({
                "Label": label,
                "rep": rep,
                "n": len(xr),
                "median_h": np.percentile(xr, 50),
                "p95_h": np.percentile(xr, 95),
            })

    rep_tab = pd.DataFrame(rep_rows)
    summary_row = {
        "Category": label,
        "n_total": len(x),
        "n_reps": len(rep_tab),
        "median_h_mean_reps": rep_tab["median_h"].mean(),
        "p95_h_mean_reps": rep_tab["p95_h"].mean(),
    }

    xs, ys = (np.sort(x), np.arange(1, len(x) + 1) / len(x))
    fig, ax = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
    fig.subplots_adjust(left=0.15, right=0.97, bottom=0.15, top=0.78)

    ax.step(xs, ys, where="post", color=SIM_C, linewidth=1.6)

    p50, p95 = np.percentile(x, [50, 95])
    ax.axvline(p50, color=INK2, linewidth=0.9, linestyle="--")
    ax.axvline(p95, color=OBS24_C, linewidth=0.9, linestyle=":")

    ax.text(
        0.97, 0.05,
        f"n = {len(x):,}\nMedian = {p50:.1f} h\nP95 = {p95:.1f} h",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=7, color=INK2,
    )

    _apply_axes_bounds(ax)
    fig.suptitle(str(label), x=0.15, y=0.96, ha="left", va="top", fontsize=9, fontweight="bold", color=INK)

    handles = [
        Line2D([0], [0], color=SIM_C, lw=1.6, label="Simulated"),
        Line2D([0], [0], color=INK2, lw=0.9, ls="--", label="Median"),
        Line2D([0], [0], color=OBS24_C, lw=0.9, ls=":", label="95th pct"),
    ]
    fig.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0.15, 0.90),
        ncol=LEGEND_COLUMNS,
        frameon=False,
        fontsize=7.0,
        columnspacing=1.2,
        handlelength=1.6,
    )

    save_both(fig, stem, OUTPUT_DIR, DPI)
    return summary_row


def _plot_group_overlay(df_grp: pd.DataFrame, grp_name: str, member_order: list[str], stem: str):
    """Plot combined group total ECDF (with Total Median & P95 lines) + each constituent subtype ECDF on the same panel."""
    x_all = pd.to_numeric(df_grp["tat_h"], errors="coerce").dropna().to_numpy()
    x_all = x_all[np.isfinite(x_all) & (x_all >= 0)]
    if len(x_all) == 0:
        return

    present_types = [t for t in member_order if t in set(df_grp["Type"].astype(str))]
    for t in sorted(df_grp["Type"].astype(str).unique()):
        if t not in present_types:
            present_types.append(t)

    ncol = 2 if len(present_types) > 1 else 3
    n_legend_rows = max(1, math.ceil((3 + len(present_types)) / ncol))
    top_frac = max(0.60, 0.84 - 0.045 * n_legend_rows)

    fig, ax = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
    fig.subplots_adjust(left=0.15, right=0.97, bottom=0.15, top=top_frac)

    # 1. Combined Total curve + Total Median and 95th percentile vertical lines
    xs_tot, ys_tot = np.sort(x_all), np.arange(1, len(x_all) + 1) / len(x_all)
    ax.step(xs_tot, ys_tot, where="post", color=SIM_C, linewidth=2.0, zorder=4)

    p50_tot, p95_tot = np.percentile(x_all, [50, 95])
    ax.axvline(p50_tot, color=INK2, linewidth=0.9, linestyle="--", zorder=5)
    ax.axvline(p95_tot, color=OBS24_C, linewidth=0.9, linestyle=":", zorder=5)

    handles = [
        Line2D([0], [0], color=SIM_C, lw=2.0, label=f"Total ({grp_name})"),
        Line2D([0], [0], color=INK2, lw=0.9, ls="--", label="Median (Total)"),
        Line2D([0], [0], color=OBS24_C, lw=0.9, ls=":", label="95th pct (Total)"),
    ]

    # 2. Constituent subtype curves in distinct colors (no separate median/P95 lines)
    for idx, sub_type in enumerate(present_types):
        sub_df = df_grp[df_grp["Type"].astype(str) == sub_type]
        x_sub = pd.to_numeric(sub_df["tat_h"], errors="coerce").dropna().to_numpy()
        x_sub = x_sub[np.isfinite(x_sub) & (x_sub >= 0)]
        if len(x_sub) == 0:
            continue
        col = SUBTYPE_PALETTE[idx % len(SUBTYPE_PALETTE)]
        xs_s, ys_s = np.sort(x_sub), np.arange(1, len(x_sub) + 1) / len(x_sub)
        ax.step(xs_s, ys_s, where="post", color=col, linewidth=1.35, alpha=0.92, zorder=3)
        handles.append(Line2D([0], [0], color=col, lw=1.35, label=sub_type))

    # Summary text box for Total only
    ax.text(
        0.97, 0.05,
        f"n = {len(x_all):,}\nMedian = {p50_tot:.1f} h\nP95 = {p95_tot:.1f} h",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=7, color=INK2,
    )

    _apply_axes_bounds(ax)
    fig.suptitle(f"{grp_name} (Total & Subtypes)", x=0.15, y=0.96, ha="left", va="top", fontsize=9, fontweight="bold", color=INK)
    fig.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0.15, 0.90),
        ncol=ncol,
        frameon=False,
        fontsize=6.6,
        columnspacing=1.1,
        handlelength=1.5,
    )

    save_both(fig, stem, OUTPUT_DIR, DPI)


def fig_time_to_finalization(sim: pd.DataFrame):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Individual specimen types
    indiv_rows = []
    for specimen_type, d in sim.groupby("Type", sort=True):
        safe_type = re.sub(r"[^A-Za-z0-9]+", "_", str(specimen_type)).strip("_")
        row = _plot_ecdf_subset(d, str(specimen_type), f"FigS7B_time_to_finalization_{safe_type}")
        if row:
            indiv_rows.append(row)

    if indiv_rows:
        pd.DataFrame(indiv_rows).to_csv(
            OUTPUT_DIR / "table_time_to_finalization_by_type.csv",
            index=False,
            float_format="%.2f",
        )

    # 2. Grouped specimen categories (ECDF_GROUPS) + Multi-line overlay figures
    sim_grp = sim.copy()
    sim_grp["ecdf_group"] = sim_grp["Type"].map(lambda t: SIM_TO_GROUP.get(str(t), str(t)))

    group_rows = []
    ordered_groups = list(ECDF_GROUPS.keys()) + [
        g for g in sorted(sim_grp["ecdf_group"].unique()) if g not in ECDF_GROUPS
    ]
    for grp_name in ordered_groups:
        d = sim_grp[sim_grp["ecdf_group"] == grp_name]
        if d.empty:
            continue
        safe_grp = re.sub(r"[^A-Za-z0-9]+", "_", str(grp_name)).strip("_")
        row = _plot_ecdf_subset(d, str(grp_name), f"FigS7B_time_to_finalization_grouped_{safe_grp}")
        if row:
            group_rows.append(row)

        # Overlay plot with Total (plus Total Median & P95) + constituent types in different colors
        member_order = ECDF_GROUPS.get(grp_name, [])
        _plot_group_overlay(
            d,
            str(grp_name),
            member_order,
            f"FigS7B_time_to_finalization_grouped_overlay_{safe_grp}",
        )

    if group_rows:
        pd.DataFrame(group_rows).to_csv(
            OUTPUT_DIR / "table_time_to_finalization_by_group.csv",
            index=False,
            float_format="%.2f",
        )


def main():
    fc.apply_style()
    sim, _, _ = fc.load_sim(MC_DIR, fc.invert(ECDF_GROUPS))
    fig_time_to_finalization(sim)


if __name__ == "__main__":
    main()