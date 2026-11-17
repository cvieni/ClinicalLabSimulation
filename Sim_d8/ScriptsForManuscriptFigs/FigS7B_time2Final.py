#!/usr/bin/env python3
"""Figure S7B: Time-to-finalization ECDF by specimen group/type (with median & 95th percentile).
Run: python FigS7B_time2Final_2.py"""
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
PNG_HEIGHT = 3.4
LEGEND_COLUMNS = 3
DPI = 300
GROUP_BY_VALIDATION_GROUPS = False   # False = every individual Type in specimens_*.csv.gz; True = fc.GROUPS_VALIDATION
# ==============================================================================================================================================


def save_both(fig, stem, out_dir: Path = OUTPUT_DIR, dpi: int = DPI):
    """Save <stem>_labelled.png (white bg, visible axes) and <stem>_unlabelled.png (transparent bg, tick marks only) on an identical canvas."""
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


def fig_time_to_finalization(sim):
    rows = []
    group_col = "group" if (GROUP_BY_VALIDATION_GROUPS and "group" in sim.columns) else "Type"

    for specimen_type, d in sim.groupby(group_col, sort=True):
        x = pd.to_numeric(d["tat_h"], errors="coerce").dropna().to_numpy()
        x = x[np.isfinite(x) & (x >= 0)]

        if len(x) == 0:
            continue

        rep_rows = []
        for rep, dr in d.groupby("rep"):
            xr = pd.to_numeric(dr["tat_h"], errors="coerce").dropna().to_numpy()
            xr = xr[np.isfinite(xr) & (xr >= 0)]
            if len(xr):
                rep_rows.append({
                    "Type": specimen_type,
                    "rep": rep,
                    "n": len(xr),
                    "median_h": np.percentile(xr, 50),
                    "p95_h": np.percentile(xr, 95),
                })

        rep_tab = pd.DataFrame(rep_rows)
        rows.append({
            "Type": specimen_type,
            "n_total": len(x),
            "n_reps": len(rep_tab),
            "median_h_mean_reps": rep_tab["median_h"].mean(),
            "p95_h_mean_reps": rep_tab["p95_h"].mean(),
        })

        xs, ys = (np.sort(x), np.arange(1, len(x) + 1) / len(x))
        fig, ax = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
        fig.subplots_adjust(left=0.15, right=0.97, bottom=0.15, top=0.78)

        ax.step(xs, ys, where="post", color=fc.SIM_C, linewidth=1.6)

        p50, p95 = np.percentile(x, [50, 95])
        ax.axvline(p50, color=fc.INK2, linewidth=0.9, linestyle="--")
        ax.axvline(p95, color=fc.OBS24_C, linewidth=0.9, linestyle=":")

        ax.text(
            0.97, 0.05,
            f"n = {len(x):,}\nMedian = {p50:.1f} h\nP95 = {p95:.1f} h",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=7, color=fc.INK2,
        )

        ax.set_xlim(left=0)
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("Receipt to final report (h)")
        ax.set_ylabel("Cumulative proportion")

        fig.suptitle(str(specimen_type), x=0.15, y=0.96, ha="left", va="top", fontsize=9, fontweight="bold", color=fc.INK)

        handles = [
            Line2D([0], [0], color=fc.SIM_C, lw=1.6, label="Simulated"),
            Line2D([0], [0], color=fc.INK2, lw=0.9, ls="--", label="Median"),
            Line2D([0], [0], color=fc.OBS24_C, lw=0.9, ls=":", label="95th pct"),
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

        safe_type = re.sub(r"[^A-Za-z0-9]+", "_", str(specimen_type)).strip("_")
        save_both(fig, f"FigS7B_time_to_finalization_{safe_type}", OUTPUT_DIR, DPI)

    if rows:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(
            OUTPUT_DIR / "table_time_to_finalization_by_type.csv",
            index=False,
            float_format="%.2f",
        )


def main():
    fc.apply_style()
    sim, _, _ = fc.load_sim(MC_DIR, fc.invert(fc.GROUPS_VALIDATION))
    fig_time_to_finalization(sim)


if __name__ == "__main__":
    main()