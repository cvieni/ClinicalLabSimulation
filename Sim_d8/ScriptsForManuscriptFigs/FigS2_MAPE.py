# ScriptsForManuscriptFigs/FigS2_MAPE.py

#!/usr/bin/env python3
"""Figure 2: validation. Simulated TAT (mean of replications, 95% CI) against the LIS, one dumbbell figure for the
median (02a) and one for the 95th percentile (02b). Run from anywhere:  python Fig2_ValidationPlot.py
Also writes table2_validation.csv to OUTPUT_DIR."""
from pathlib import Path

import numpy as np
import pandas as pd
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

MC_DIR = "results_experiments/mc_gerada_gram"                       # Monte Carlo folder (has replications/ and run_table.csv)
OBS_2025 = ["data/observed_2025_lis_clean.csv"]                     # list of RAW LIS files (tuned / calibration year)
OBS_2024 = ["data/observed_2024_lis_clean.csv"]                                                       # list of RAW LIS files (held-out validation year); [] = none
OBS_EXCLUDE = None                                                  # drop LIS rows whose source file name contains this text

# ==============================================================================================================================================



def fig_agreement(tab):
    fig, ax = plt.subplots(figsize=(3.5, 3.5))
    fig.subplots_adjust(left=0.16, right=0.97, bottom=0.15, top=0.88)
    lo, hi = 20, 500
    xs = np.array([lo, hi])
    ax.plot(xs, xs, color=INK, linewidth=0.8)
    ax.fill_between(xs, xs * 0.8, xs * 1.2, color=GRID, alpha=0.6, lw=0, zorder=0)
    txt = []
    for stat, filled, mk in (("p50", True, "o"), ("p95", False, "s")):
        c = f"obs2025_{stat}"
        if c not in tab:
            continue
        d = tab.dropna(subset=[c])
        ax.scatter(d[c], d[f"sim_{stat}"], s=26, marker=mk, color=SIM_C if filled else "white",
                   edgecolor=SIM_C, linewidth=1.1, zorder=3)
        mape = (100 * (d[f"sim_{stat}"] - d[c]).abs() / d[c]).mean()
        r2 = np.corrcoef(np.log(d[c]), np.log(d[f"sim_{stat}"]))[0, 1] ** 2
        txt.append(f"{stat.upper()}: MAPE {mape:.0f}%, R² {r2:.2f}")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal")
    ax.text(0.04, 0.96, "\n".join(txt), transform=ax.transAxes, va="top", fontsize=7, color=INK2)
    ax.set_xlabel("Observed TAT, LIS 2025 (h, log scale)")
    ax.set_ylabel("Simulated TAT (h, log scale)")
    h = [Line2D([0], [0], marker="o", color="w", markerfacecolor=SIM_C, markersize=5, label="Median"),
         Line2D([0], [0], marker="s", color="w", markerfacecolor="white", markeredgecolor=SIM_C, markersize=5,
                label="95th percentile"),
         Line2D([0], [0], color=GRID, linewidth=6, label="±20%")]
    top_legend(ax, h, ncol=3)
    save_both(fig, "02_agreement_obs_vs_sim")
