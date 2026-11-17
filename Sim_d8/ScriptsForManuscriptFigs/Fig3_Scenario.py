#!/usr/bin/env python3
"""Figure 3: scenario comparison. Change in TAT (scenario minus baseline, paired by replication, mean and 95% CI) for the
95th percentile (03a) and the median (03b), one row per scenario, one dot per specimen type.
Run:  python Fig3_Scenario.py     Also writes table4_scenarios.csv to OUTPUT_DIR."""
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from scipy import stats

import fig_common as fc

# =========================================================== SETTINGS (edit these) ===========================================================
OUTPUT_DIR = Path("manuscript_png")
PNG_WIDTH = 4.2                              # inches
LEFT_MARGIN_IN = 1.1                         # room for the scenario names (inches)
PNG_HEIGHT = None                            # inches; None = automatic (0.7 in per scenario + 1.6)
DPI = 300
BARE = False

figure_margin_size = 0.0
set_background_transparent = True

BASELINE = "baseline"
SCENARIOS = {                                # name -> Monte Carlo folder. Same seeds in every folder (paired by replication)
    "baseline":   "results_experiments/mc_A",
    "no_biochem": "results_experiments/mc_B",
    "no_float":   "results_experiments/mc_C",
}
# y-axis order of the scenarios, TOP to BOTTOM (baseline is the reference and is not drawn)
SCENARIO_ORDER = ["no_biochem", "no_float"]
# order of the dots WITHIN each scenario row (top to bottom) and of the legend
SPECIMEN_ORDER = ["Blood culture", "Body fluid", "Bone", "Tissue", "Tissue (FNA)", "Tissue (genital)", "Wound", "Wound (genital)",
                  "Stool", "Respiratory (non-CF)", "Respiratory (CF)", "Urine_nonInv", "Urine_Inv"]
SPECIMEN_COLORS = {                          # edit hex codes here
    "Blood culture": "#d62728", "Body fluid": "#ff7f0e", "Bone": "#8c564b", "Tissue": "#9467bd", "Tissue (FNA)": "#e377c2",
    "Tissue (genital)": "#f7b6d2", "Wound": "#1f77b4", "Wound (genital)": "#6baed6", "Stool": "#7f7f7f",
    "Respiratory (non-CF)": "#2ca02c", "Respiratory (CF)": "#17becf", "Urine_nonInv": "#eda100", "Urine_Inv": "#bcbd22",
}
LEGEND_COLUMNS = 2
# ==============================================================================================================================================

GROUPS = {                                   # display group -> simulation types pooled into it
    "Blood culture": ["BCx"], "Body fluid": ["BodyFluid"], "Bone": ["Bone_Cx"], "Tissue": ["Tissue"], "Tissue (FNA)": ["Tissue_FNA"],
    "Tissue (genital)": ["Tissue_genital"], "Wound": ["Wound"], "Wound (genital)": ["Wound_Genital"],
    "Stool": ["Stool", "Stool_Ecoli", "Stool_EcoliRoutine", "Stool_Campy", "Stool_Vibrio", "Stool_Yersinia"],
    "Respiratory (non-CF)": ["Respiratory", "Resp_NonCF"], "Respiratory (CF)": ["Resp_CystFibrosis", "Resp_CF"],
    "Urine_nonInv": ["Urine_NonInvasive"], "Urine_Inv": ["Urine_Invasive"],
}


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


def scenario_frames():
    out = []
    for name, folder in SCENARIOS.items():
        print(f"Loading '{name}' from {folder}")
        s, _, _ = fc.load_sim(folder, fc.invert(GROUPS))
        r = s.groupby(["group", "rep"])["tat_h"].agg(p50=lambda x: np.percentile(x, 50), p95=lambda x: np.percentile(x, 95),
                                                      n="size").reset_index()
        r["scenario"] = name
        out.append(r)
    return pd.concat(out, ignore_index=True)


def main():
    fc.apply_style()
    if set_background_transparent:
        plt.rcParams.update({"figure.facecolor": "none", "axes.facecolor": "none"})

    scn = scenario_frames()
    base = scn[scn.scenario == BASELINE]
    if base.empty:
        raise SystemExit(f"SCENARIOS has no entry named '{BASELINE}'")
    scens = fc.ordered(SCENARIO_ORDER, [s for s in scn.scenario.unique() if s != BASELINE])
    allrows = []
    for metric, xlabel, stem in (("p95", "Δ 95th percentile TAT vs baseline (h)", "03a_scenarios_delta_p95"),
                                 ("p50", "Δ median TAT vs baseline (h)", "03b_scenarios_delta_p50")):
        m = scn[scn.scenario != BASELINE].merge(base[["group", "rep", metric]].rename(columns={metric: "b"}), on=["group", "rep"])
        m["delta"] = m[metric] - m["b"]
        g = m.groupby(["scenario", "group"])["delta"]
        s = pd.DataFrame({"mean": g.mean(), "se": g.sem(), "n": g.count()}).reset_index()
        s["ci"] = stats.t.ppf(0.975, (s["n"] - 1).clip(lower=1)) * s["se"]
        s["metric"] = metric
        allrows.append(s)

        groups = fc.ordered(SPECIMEN_ORDER, s["group"])
        colors = {g_: SPECIMEN_COLORS.get(g_, fc.FALLBACK_PALETTE[i % 8]) for i, g_ in enumerate(groups)}
        top_in = fc.legend_height_in(len(groups), LEGEND_COLUMNS)
        h_in = PNG_HEIGHT if PNG_HEIGHT else 0.7 * len(scens) + 0.8 + top_in
        fig, ax = fc.new_fig(PNG_WIDTH, h_in, left_in=LEFT_MARGIN_IN, right_in=0.2, bottom_in=0.6, top_in=top_in)
        step = 0.8 / max(len(groups), 1)
        for i, sc in enumerate(scens):
            for j, g_ in enumerate(groups):
                r = s[(s.scenario == sc) & (s.group == g_)]
                if r.empty:
                    continue
                ax.errorbar(r["mean"].iloc[0], i - 0.4 + step * (j + 0.5), xerr=r["ci"].iloc[0], fmt="o", markersize=3.4,
                            color=colors[g_], ecolor=colors[g_], elinewidth=0.9, markeredgecolor="white", markeredgewidth=0.4)
        ax.axvline(0, color=fc.INK, linewidth=0.8)
        ax.set_yticks(range(len(scens)))
        ax.set_yticklabels([textwrap.fill(x.replace("_", " "), 18) for x in scens])
        ax.set_ylim(-0.6, len(scens) - 0.4)
        ax.invert_yaxis()                                  # first scenario in SCENARIO_ORDER at the top
        ax.grid(axis="y", visible=False)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Scenario")
        h = [Line2D([0], [0], marker="o", color="w", markerfacecolor=colors[g_], markersize=5, label=g_) for g_ in groups]
        fc.top_legend(ax, h, ncol=LEGEND_COLUMNS)
        save_both(fig, stem, OUTPUT_DIR, DPI, BARE)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.concat(allrows).to_csv(OUTPUT_DIR / "table4_scenarios.csv", index=False, float_format="%.3f")


if __name__ == "__main__":
    main()