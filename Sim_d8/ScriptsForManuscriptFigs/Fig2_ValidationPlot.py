#!/usr/bin/env python3
"""Figure 2: validation. Simulated TAT (mean of replications, 95% CI) against the LIS, one dumbbell figure for the
median (02a) and one for the 95th percentile (02b). Run from anywhere:  python Fig2_ValidationPlot.py
Also writes table2_validation.csv to OUTPUT_DIR."""
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import fig_common as fc

# =========================================================== SETTINGS (edit these) ===========================================================
OUTPUT_DIR = Path("manuscript_png")          # where the PNGs (and table2_validation.csv) go
PNG_WIDTH = 4.2                              # inches
LEFT_MARGIN_IN = 1.75                        # room for the y-axis labels (inches); raise it if a label is cut off
LEGEND_COLUMNS = 1
PNG_HEIGHT = None                            # inches; None = automatic from the number of rows (0.3 in per row + 1.4)
DPI = 300
BARE = False                                 # True: the unlabelled version also loses the legend and in-plot text

figure_margin_size = 0.0
set_background_transparent = True

MC_DIR = "results_experiments/mc_gerada_gram"                       # Monte Carlo folder (has replications/ and run_table.csv)
OBS_2025 = ["data/observed_2025_lis_clean.csv"]                     # list of RAW LIS files (tuned / calibration year)
OBS_2024 = []                                                       # list of RAW LIS files (held-out validation year); [] = none
OBS_EXCLUDE = None                                                  # drop LIS rows whose source file name contains this text
LABEL_2025 = "LIS 2025 (tuned)"
LABEL_2024 = "LIS 2024 (validation)"
LABEL_SIM = "Simulated (mean, 95% CI)"

# y-axis order, TOP to BOTTOM. Names not in the data are skipped; names you leave out are added at the bottom.
SPECIMEN_ORDER = [
    "Blood culture", "Body fluid", "Bone", "Tissue", "Tissue (FNA)", "Tissue (genital)", "Wound", "Wound (genital)",
    "Stool", "Stool 60134 (E. coli)", "Stool 60135 (Campylobacter)", "Stool 60136 (Vibrio)", "Stool 60137 (Yersinia)",
    "Respiratory (non-CF)", "Respiratory (CF)", "Urine",
]
# ==============================================================================================================================================


def save_both(fig, stem, out_dir=OUTPUT_DIR, dpi=DPI, bare=BARE):
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


def main():
    fc.apply_style()
    if set_background_transparent:
        plt.rcParams.update({"figure.facecolor": "none", "axes.facecolor": "none"})

    sim, rt, n_days = fc.load_sim(MC_DIR, fc.invert(fc.GROUPS_VALIDATION))
    obs25 = fc.load_obs(OBS_2025, OBS_EXCLUDE) if OBS_2025 else None
    obs24 = fc.load_obs(OBS_2024, OBS_EXCLUDE) if OBS_2024 else None
    print(f"sim: {len(sim):,} in-window specimens, {sim.rep.nunique()} replications, {n_days:.0f} measured days")
    simv, o25, o24 = fc.with_stool_split(sim, "sim"), fc.with_stool_split(obs25, "obs"), fc.with_stool_split(obs24, "obs")
    tab = fc.validation_table(simv, o25, o24, n_days)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tab.to_csv(OUTPUT_DIR / "table2_validation.csv", index=False, float_format="%.2f")

    order = fc.ordered(SPECIMEN_ORDER, tab["group"])
    h_in = PNG_HEIGHT if PNG_HEIGHT else 0.3 * len(order) + 1.6
    for stat, ttl, stem in (("p50", "Median TAT (h)", "02a_validation_p50"), ("p95", "95th percentile TAT (h)", "02b_validation_p95")):
        n_leg = 1 + (obs25 is not None) + ("obs2024_p50" in tab)
        fig, ax = fc.new_fig(PNG_WIDTH, h_in, left_in=LEFT_MARGIN_IN, right_in=0.15, bottom_in=0.6, top_in=fc.legend_height_in(n_leg, LEGEND_COLUMNS))
        for k, g in enumerate(order):
            r = tab[tab.group == g].iloc[0]
            if f"obs2025_{stat}" in r and pd.notna(r.get(f"obs2025_{stat}")):
                ax.plot([r[f"sim_{stat}"], r[f"obs2025_{stat}"]], [k, k], color=fc.GRID, linewidth=2.2, zorder=1)
                ax.scatter(r[f"obs2025_{stat}"], k, marker="D", s=26, color=fc.OBS_C, zorder=4)
            if f"obs2024_{stat}" in r and pd.notna(r.get(f"obs2024_{stat}")):
                ax.scatter(r[f"obs2024_{stat}"], k, marker="D", s=26, facecolor="white", edgecolor=fc.OBS24_C, linewidth=1.0, zorder=3)
            ci = r[f"sim_{stat}_ci"]
            ax.errorbar(r[f"sim_{stat}"], k, xerr=ci if pd.notna(ci) else 0, fmt="o", markersize=4.6, color=fc.SIM_C,
                        ecolor=fc.SIM_C, elinewidth=1, markeredgecolor="white", markeredgewidth=0.6, zorder=5)
        ax.set_yticks(range(len(order)))
        ax.set_yticklabels(order)
        ax.set_ylim(-0.6, len(order) - 0.4)
        ax.invert_yaxis()                                  # first name in SPECIMEN_ORDER is at the top
        ax.set_xlim(left=0)
        ax.grid(axis="y", visible=False)
        ax.set_xlabel(ttl)
        ax.set_ylabel("Specimen type")
        h = [Line2D([0], [0], marker="o", color="w", markerfacecolor=fc.SIM_C, markersize=5, label=LABEL_SIM)]
        if obs25 is not None:
            h.append(Line2D([0], [0], marker="D", color="w", markerfacecolor=fc.OBS_C, markersize=5, label=LABEL_2025))
        if "obs2024_p50" in tab:
            h.append(Line2D([0], [0], marker="D", color="w", markerfacecolor="white", markeredgecolor=fc.OBS24_C, markersize=5, label=LABEL_2024))
        fc.top_legend(ax, h, ncol=LEGEND_COLUMNS)
        save_both(fig, stem, OUTPUT_DIR, DPI, BARE)


if __name__ == "__main__":
    main()