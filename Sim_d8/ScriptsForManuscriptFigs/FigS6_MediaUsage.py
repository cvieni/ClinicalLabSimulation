#!/usr/bin/env python3
"""Figure S6: media in the simulation over time: plates used per day, cumulative use, plates expired per day and stock on hand,
one line per media (mean over replications, optional band). Needs replications/media_###.csv.gz in MC_DIR: copy the new
modules/inventory.py, run  python apply_media_export.py <simulation_d4.py> <run_montecarlo_and_plot.py>  once, and re-run the Monte Carlo.
Run:  python FigS6_MediaUsage.py     Also writes tableS6_media_summary.csv and one daily table per panel."""
import glob
import re
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import fig_common as fc

# =========================================================== SETTINGS (edit these) ===========================================================
SIM_DIR = Path(__file__).resolve().parent.parent                 # project folder (contains results_experiments/)
OUTPUT_DIR = SIM_DIR / "manuscript_png/FigS6_Media"
MC_DIR = SIM_DIR / "results_experiments/scn_baseline"
PNG_WIDTH = 4.6                              # inches
PNG_HEIGHT = 7.2                             # inches (all panels + legend); about 1.5 in per panel is comfortable
DPI = 300
BARE = False                                 # True: the unlabelled version also loses the legend and panel titles
LEGEND_COLUMNS = 3

REPLICATION = "mean"                         # "mean" = average over all replications, or a replication number (e.g. 0) for one run
SHOW_BAND = True                             # "mean" only: shade the 2.5-97.5 percentile range across replications (needs >= 5 replications)
SHOW_ORDERS = True                           # single replication only: dashed vertical line on each day any media was ordered
SHADE_OUTSIDE_WINDOW = True                  # grey out warm-up and cool-down (from run_table.csv window_start_min/window_end_min)
HIDE_UNUSED = True                           # drop media that are never used

figure_margin_size = 0.0
set_background_transparent = True

# panels, TOP to BOTTOM: any of  used | cumulative | expired | on_hand | ordered | delivered
PANELS = ["used", "cumulative", "expired", "on_hand"]
# media order = line/legend order. Media in the data but not listed here are added at the end.
MEDIA_ORDER = ["Blood_Agar", "Chocolate_Agar", "MacConkey", "CNA_Agar", "GN_Broth", "ChromeAgar", "BCSA_Agar", "ThayerMartin",
               "MTM", "HE_Agar", "Campy_CVA", "CT-SMAC", "TCBS"]
MEDIA_COLORS = {}                            # optional {"Blood_Agar": "#d62728"}; others come from the palette
PALETTE = ["#2a78d6", "#d62728", "#1baf7a", "#eda100", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#17becf", "#bcbd22",
           "#ff7f0e", "#1f4e9c", "#2ca02c", "#98df8a", "#c5b0d5"]
# ==============================================================================================================================================

PANEL_DEFS = {   # key: (column, y label, title, linestyle, linewidth)
    "used":       ("Used", "Plates used / day", "Daily media consumption", "-", 1.2),
    "cumulative": ("Used", "Cumulative plates used", "Cumulative media consumption", "-", 1.4),
    "expired":    ("Expired", "Plates expired / day", "Daily media expiration", "--", 1.2),
    "on_hand":    ("On_Hand", "Plates on hand", "Stock on hand (start of day)", "-", 1.2),
    "ordered":    ("Ordered", "Plates ordered / day", "Daily media orders", "-", 1.2),
    "delivered":  ("Delivered", "Plates delivered / day", "Daily media deliveries", "-", 1.2),
}


def save_both(fig, stem, out_dir: Path, dpi: int = 300, bare: bool = False):
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


def load_media(mc_dir):
    files = sorted(glob.glob(str(Path(mc_dir) / "replications" / "media_*.csv.gz")))
    if not files:
        raise SystemExit(f"No replications/media_*.csv.gz in {mc_dir}.\nCopy the new modules/inventory.py, run "
                         f"apply_media_export.py on simulation_d4.py and run_montecarlo_and_plot.py, then re-run the Monte Carlo.")
    d = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    if "rep" not in d.columns:
        raise SystemExit("media files have no 'rep' column")
    return d


def window_days(mc_dir):
    try:
        rt = pd.read_csv(Path(mc_dir) / "run_table.csv")
        return float(rt["window_start_min"].iloc[0]) / 1440.0, float(rt["window_end_min"].iloc[0]) / 1440.0
    except Exception:                                          # noqa: BLE001
        return None


def main():
    fc.apply_style()
    if set_background_transparent:
        plt.rcParams.update({"figure.facecolor": "none", "axes.facecolor": "none"})

    d = load_media(MC_DIR)
    reps = sorted(d["rep"].unique())
    media = fc.ordered(MEDIA_ORDER, d["Media"].unique())
    if HIDE_UNUSED:
        tot = d.groupby("Media")["Used"].sum()
        media = [m for m in media if tot.get(m, 0) > 0]
    single = REPLICATION != "mean"
    if single:
        if REPLICATION not in reps:
            raise SystemExit(f"replication {REPLICATION} not in {reps[:10]}...")
        d = d[d["rep"] == REPLICATION]
    d = d.sort_values(["rep", "Media", "Day"]).copy()
    d["Cumulative"] = d.groupby(["rep", "Media"])["Used"].cumsum()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    colors = {m: MEDIA_COLORS.get(m, PALETTE[i % len(PALETTE)]) for i, m in enumerate(media)}
    handles = [Line2D([0], [0], color=colors[m], linewidth=1.5, label=m) for m in media]
    order_days = []
    if single and SHOW_ORDERS:
        order_days = sorted(d.loc[d["Ordered"] > 0, "Day"].unique())
        if order_days:
            handles.append(Line2D([0], [0], color=fc.OBS24_C, linestyle="--", linewidth=1, label="Media order placed"))

    top_in = fc.legend_height_in(len(handles), LEGEND_COLUMNS)
    n = len(PANELS)
    fig, axes = plt.subplots(n, 1, figsize=(PNG_WIDTH, PNG_HEIGHT), sharex=True, squeeze=False)
    axes = axes[:, 0]
    fig.subplots_adjust(left=1.75 / PNG_WIDTH, right=1 - 0.2 / PNG_WIDTH, bottom=0.65 / PNG_HEIGHT,
                        top=1 - (top_in + 0.3) / PNG_HEIGHT, hspace=0.5)
    win = window_days(MC_DIR) if SHADE_OUTSIDE_WINDOW else None
    for k, (ax, key) in enumerate(zip(axes, PANELS)):
        col, ylab, ttl, ls, lw = PANEL_DEFS[key]
        col = "Cumulative" if key == "cumulative" else col
        piv = d.pivot_table(index="Day", columns=["Media", "rep"], values=col, aggfunc="sum")
        for m in media:
            if m not in piv.columns.get_level_values(0):
                continue
            sub = piv[m]
            mean = sub.mean(axis=1)
            ax.plot(mean.index, mean.to_numpy(), color=colors[m], linewidth=lw, linestyle=ls)
            if SHOW_BAND and not single and sub.shape[1] >= 5:
                ax.fill_between(mean.index, sub.quantile(0.025, axis=1), sub.quantile(0.975, axis=1), color=colors[m], alpha=0.12, lw=0)
        tab = pd.DataFrame({m: piv[m].mean(axis=1) for m in media if m in piv.columns.get_level_values(0)})
        tab.index.name = "Day"
        tab.round(2).to_csv(OUTPUT_DIR / f"tableS6_media_{key}_daily_{'rep%d' % REPLICATION if single else 'mean'}.csv")
        for od in order_days:
            ax.axvline(od, color=fc.OBS24_C, linestyle="--", alpha=0.25, linewidth=0.8)
        if win:
            ax.axvspan(0, win[0], color=fc.GRID, alpha=0.5, lw=0)
            ax.axvspan(win[1], max(d["Day"].max(), win[1]), color=fc.GRID, alpha=0.5, lw=0)
        ax.set_xlim(0, d["Day"].max())
        ax.set_ylim(bottom=0)
        ax.set_ylabel(ylab)
        ax.set_title(f"{chr(65 + k)}. {ttl}", loc="left", fontsize=8, fontweight="bold")
        ax.grid(axis="y", linestyle=":", alpha=0.6)
    axes[-1].set_xlabel("Simulation day")
    fc.top_legend(axes[0], handles=handles, ncol=LEGEND_COLUMNS)
    save_both(fig, "S6_media_usage", OUTPUT_DIR, DPI, BARE)

    # ---- per-media summary over all replications (measured window only if known)
    full = load_media(MC_DIR)
    w = window_days(MC_DIR)
    if w:
        full = full[(full["Day"] >= w[0]) & (full["Day"] < w[1])]
    g = full.groupby(["Media", "rep"]).agg(used=("Used", "sum"), expired=("Expired", "sum"), orders=("Ordered", lambda x: int((x > 0).sum())),
                                           min_on_hand=("On_Hand", "min")).reset_index()
    s = g.groupby("Media").agg(used_mean=("used", "mean"), expired_mean=("expired", "mean"), orders_mean=("orders", "mean"),
                               min_on_hand_mean=("min_on_hand", "mean"), min_on_hand_lowest=("min_on_hand", "min"),
                               n_reps=("rep", "nunique"))
    s["expired_pct_of_removed"] = 100 * s["expired_mean"] / (s["used_mean"] + s["expired_mean"]).replace(0, np.nan)
    s["days_with_zero_stock_mean"] = full[full["On_Hand"] <= 0].groupby(["Media", "rep"]).size().groupby("Media").sum().div(s["n_reps"]).reindex(s.index).fillna(0)
    s.reindex([m for m in fc.ordered(MEDIA_ORDER, s.index)]).round(2).to_csv(OUTPUT_DIR / "tableS6_media_summary.csv")


if __name__ == "__main__":
    main()