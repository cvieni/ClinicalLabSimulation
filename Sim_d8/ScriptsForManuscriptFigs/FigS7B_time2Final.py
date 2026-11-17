# Sim_d8/ScriptsForManuscriptFigs/FigS6_SpecimenCounts.py

output_direct = "manuscript_pngs/FigS7_time2Final"

Add in separate figures for each specimen type that show the time to final

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import fig_common as fc

# =========================================================== SETTINGS (edit these) ===========================================================
OUTPUT_DIR = Path("manuscript_png/FigS7B_time2Final")          # where the PNGs (and table2_validation.csv) go
PNG_WIDTH = 4.2                              # inches
PNG_HEIGHT = 4.2
LEGEND_COLUMNS = 1
PNG_HEIGHT = None                            # inches; None = automatic from the number of rows (0.3 in per row + 1.4)
DPI = 300
BARE = False                                 # True: the unlabelled version also loses the legend and in-plot text
figure_margin_size = 0.1
set_background_transparent = True

# Research/ClinicalLabSimulation
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# Research/ClinicalLabSimulation/Sim_d8
SIM_DIR = Path(__file__).resolve().parent.parent
# Research/ClinicalLabSimulation/Sim_d8/manuscript_png
OUTPUT_DIR = Path(SIM_DIR, "manuscript_png")         
MC_DIR = Path(SIM_DIR, "results_experiments/scn_baseline")

OBS_2025 = [Path(SIM_DIR, "data/observed_2025_lis_clean.csv")]
OBS_2024 = [Path(SIM_DIR, "data/observed_2024_lis_clean.csv")]

OBS_EXCLUDE = None                                             


# ==============================================================================================================================================



def fig_time_to_finalization(sim):
    """
    One receipt-to-final-report ECDF per simulation specimen Type.
    Uses all in-window specimens and the existing tat_h field.
    """
    rows = []

    for specimen_type, d in sim.groupby("Type", sort=True):
        x = pd.to_numeric(d["tat_h"], errors="coerce").dropna().to_numpy()
        x = x[np.isfinite(x) & (x >= 0)]

        if len(x) == 0:
            print(f"  NOTE: no finalization times for {specimen_type}; skipped")
            continue

        # Replication-level summaries, so the table reflects Monte Carlo variation.
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
            "median_h_ci95": tci(rep_tab["median_h"])[1],
            "p95_h_mean_reps": rep_tab["p95_h"].mean(),
            "p95_h_ci95": tci(rep_tab["p95_h"])[1],
        })

        # Individual ECDF for this specimen type.
        xs, ys = _ecdf(x)
        fig, ax = plt.subplots(figsize=(3.6, 2.8))
        fig.subplots_adjust(left=0.17, right=0.97, bottom=0.17, top=0.84)

        ax.step(xs, ys, where="post", color=SIM_C, linewidth=1.6)

        p50, p95 = np.percentile(x, [50, 95])
        ax.axvline(p50, color=INK2, linewidth=0.9, linestyle="--")
        ax.axvline(p95, color=OBS24_C, linewidth=0.9, linestyle=":")

        ax.text(
            0.97, 0.05,
            f"n = {len(x):,}\nMedian = {p50:.1f} h\nP95 = {p95:.1f} h",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=7,
        )

        ax.set_xlim(left=0)
        ax.set_ylim(0, 1.01)
        ax.set_xlabel("Receipt to final report (h)")
        ax.set_ylabel("Cumulative proportion")
        ax.set_title(str(specimen_type), loc="left", fontsize=8, fontweight="bold")

        handles = [
            Line2D([0], [0], color=SIM_C, lw=1.6, label="Simulated specimens"),
            Line2D([0], [0], color=INK2, lw=0.9, ls="--", label="Median"),
            Line2D([0], [0], color=OBS24_C, lw=0.9, ls=":", label="95th percentile"),
        ]
        top_legend(ax, handles, ncol=1)

        safe_type = re.sub(r"[^A-Za-z0-9]+", "_", str(specimen_type)).strip("_")
        save_both(fig, f"16_time_to_finalization_{safe_type}")

    if rows:
        pd.DataFrame(rows).to_csv(
            TAB / "table_time_to_finalization_by_type.csv",
            index=False,
            float_format="%.2f",
        )