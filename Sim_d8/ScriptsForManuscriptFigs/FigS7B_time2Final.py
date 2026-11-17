from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import fig_common as fc

# =========================================================== SETTINGS (edit these) ===========================================================
OUTPUT_DIR = Path("manuscript_png/FigS7B_time2Final")
PNG_WIDTH = 4.2
PNG_HEIGHT = 4.2
LEGEND_COLUMNS = 1
DPI = 300
BARE = False
figure_margin_size = 0.0
set_background_transparent = True

# Research/ClinicalLabSimulation
BASE_DIR = Path(__file__).resolve().parent.parent.parent
SIM_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(SIM_DIR, "manuscript_png")         
MC_DIR = Path(SIM_DIR, "results_experiments/scn_baseline")

OBS_2025 = [Path(SIM_DIR, "data/observed_2025_lis_clean.csv")]
OBS_2024 = [Path(SIM_DIR, "data/observed_2024_lis_clean.csv")]
OBS_EXCLUDE = None                                             


def save_both(fig, stem, out_dir: Path = OUTPUT_DIR, dpi: int = DPI, bare: bool = BARE):
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


def fig_time_to_finalization(sim):
    rows = []

    for specimen_type, d in sim.groupby("Type", sort=True):
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
        fig, ax = plt.subplots(figsize=(3.6, 2.8))
        fig.subplots_adjust(left=0.17, right=0.97, bottom=0.17, top=0.84)

        ax.step(xs, ys, where="post", color=fc.SIM_C, linewidth=1.6)

        p50, p95 = np.percentile(x, [50, 95])
        ax.axvline(p50, color=fc.INK2, linewidth=0.9, linestyle="--")
        ax.axvline(p95, color=fc.OBS24_C, linewidth=0.9, linestyle=":")

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
            Line2D([0], [0], color=fc.SIM_C, lw=1.6, label="Simulated specimens"),
            Line2D([0], [0], color=fc.INK2, lw=0.9, ls="--", label="Median"),
            Line2D([0], [0], color=fc.OBS24_C, lw=0.9, ls=":", label="95th percentile"),
        ]
        fc.top_legend(ax, handles, ncol=1)

        safe_type = re.sub(r"[^A-Za-z0-9]+", "_", str(specimen_type)).strip("_")
        save_both(fig, f"16_time_to_finalization_{safe_type}")

    if rows:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(
            OUTPUT_DIR / "table_time_to_finalization_by_type.csv",
            index=False,
            float_format="%.2f",
        )


def main():
    fc.apply_style()
    if set_background_transparent:
        plt.rcParams.update({"figure.facecolor": "none", "axes.facecolor": "none"})

    sim, _, _ = fc.load_sim(MC_DIR)
    fig_time_to_finalization(sim)


if __name__ == "__main__":
    main()