#!/usr/bin/env python3
"""Figure S2: Agreement scatter plot (Simulated vs. Observed LIS 2025 TAT, median & 95th percentile).
Run: python FigS2_MAPE.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, FixedFormatter, NullLocator

import fig_common as fc

# =========================================================== SETTINGS ===========================================================
PNG_WIDTH = 3.5      # inches
PNG_HEIGHT = 3.5     # inches
DPI = 300

figure_margin_size = 0.1
set_background_clear = True

# Research/ClinicalLabSimulation
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# Research/ClinicalLabSimulation/Sim_d8
SIM_DIR = Path(__file__).resolve().parent.parent
# Research/ClinicalLabSimulation/Sim_d8/manuscript_png/FigS2_MAPE
OUTPUT_DIR = Path(SIM_DIR, "manuscript_png/FigS2_MAPE")
MC_DIR = Path(SIM_DIR, "results_experiments/scn_baseline")

OBS_2025 = [Path(SIM_DIR, "data/observed_2025_lis_clean.csv")]
OBS_2024 = [Path(SIM_DIR, "data/observed_2024_lis_clean.csv")]
OBS_EXCLUDE = None   # drop LIS rows whose source file name contains this text
# ================================================================================================================================


def save_both(fig, stem, out_dir: Path, dpi: int = 300):
    """Save <stem>_labelled.png and <stem>_unlabelled.png on an identical canvas (tick marks kept, all text removed)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / f"{stem}_labelled.png", dpi=dpi, facecolor="white")

    for ax in fig.axes:
        ax.set_title("")
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(
            which="both",
            bottom=True, left=True,
            labelbottom=False, labelleft=False, labelright=False, labeltop=False,
        )
        ax.xaxis.set_minor_formatter(plt.NullFormatter())
        ax.yaxis.set_minor_formatter(plt.NullFormatter())
        if ax.get_legend():
            ax.get_legend().remove()
        for t in ax.texts:
            t.set_visible(False)

    for lg in list(fig.legends):
        lg.remove()
    if fig._suptitle is not None:
        fig._suptitle.set_visible(False)

    fig.savefig(out_dir / f"{stem}_unlabelled.png", dpi=dpi, facecolor="white")
    plt.close(fig)
    print(f"  wrote {stem}_labelled.png & {stem}_unlabelled.png")


def fig_agreement(tab):
    fig, ax = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
    fig.subplots_adjust(left=0.16, right=0.97, bottom=0.15, top=0.88)
    lo, hi = 20, 500
    xs = np.array([lo, hi])
    ax.plot(xs, xs, color=fc.INK, linewidth=0.8)
    ax.fill_between(xs, xs * 0.8, xs * 1.2, color=fc.GRID, alpha=0.6, lw=0, zorder=0)
    txt = []
    for stat, filled, mk in (("p50", True, "o"), ("p95", False, "s")):
        c = f"obs2025_{stat}"
        if c not in tab:
            continue
        d = tab.dropna(subset=[c])
        ax.scatter(
            d[c], d[f"sim_{stat}"], s=26, marker=mk,
            color=fc.SIM_C if filled else "white",
            edgecolor=fc.SIM_C, linewidth=1.1, zorder=3,
        )
        mape = (100 * (d[f"sim_{stat}"] - d[c]).abs() / d[c]).mean()
        r2 = np.corrcoef(np.log(d[c]), np.log(d[f"sim_{stat}"]))[0, 1] ** 2
        txt.append(f"{stat.upper()}: MAPE {mape:.0f}%, R² {r2:.2f}")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal")
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_locator(FixedLocator([20, 50, 100, 200, 500]))
        axis.set_major_formatter(FixedFormatter(["20", "50", "100", "200", "500"]))
        axis.set_minor_locator(NullLocator())

    ax.text(0.04, 0.96, "\n".join(txt), transform=ax.transAxes, va="top", fontsize=7, color=fc.INK2)
    ax.set_xlabel("Observed TAT, LIS 2025 (h, log scale)")
    ax.set_ylabel("Simulated TAT (h, log scale)")

    h = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=fc.SIM_C, markersize=5, label="Median"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="white", markeredgecolor=fc.SIM_C, markersize=5, label="95th percentile"),
        Line2D([0], [0], color=fc.GRID, linewidth=6, label="±20%"),
    ]
    fc.top_legend(ax, h, ncol=3)
    save_both(fig, "FigS2_agreement_obs_vs_sim", OUTPUT_DIR, dpi=DPI)


def main():
    fc.apply_style()
    sim, _, n_days = fc.load_sim(MC_DIR, fc.invert(fc.GROUPS_VALIDATION))
    obs25 = fc.load_obs(OBS_2025, OBS_EXCLUDE) if OBS_2025 else None
    obs24 = fc.load_obs(OBS_2024, OBS_EXCLUDE) if OBS_2024 else None

    sim = fc.with_stool_split(sim, "sim")
    obs25 = fc.with_stool_split(obs25, "obs")
    obs24 = fc.with_stool_split(obs24, "obs")

    tab = fc.validation_table(sim, obs25, obs24, n_days)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tab.to_csv(OUTPUT_DIR / "table_s2_agreement.csv", index=False)
    fig_agreement(tab)


if __name__ == "__main__":
    main()