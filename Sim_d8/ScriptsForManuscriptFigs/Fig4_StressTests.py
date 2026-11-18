#!/usr/bin/env python3

"""
Figure 4: Stress-test scenario comparison.

Top row: Baseline TAT (hours, mean and 95% CI across replications).
Subsequent rows: Change in TAT (scenario minus baseline), paired by replication,
mean and 95% CI, for both 95th percentile (03a) and median (03b).
"""

from pathlib import Path
import textwrap

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from scipy import stats

import fig_common as fc


# ============================================================
# SETTINGS
# ============================================================

OUTPUT_DIR = Path("manuscript_png/Fig4_StressTest")

PNG_WIDTH = 4.5
LEFT_MARGIN_IN = 1.5
PNG_HEIGHT = None
DPI = 300

SCENARIO_DIR = Path("results_experiments")

BASELINE = "baseline"

INCLUDE_MEDIA_SHORTAGE = True

SCENARIOS = {
    "baseline":                   SCENARIO_DIR / "scn_baseline",
    "all_x1.25":                  SCENARIO_DIR / "scn_all_x1.25",
    "all_x1.5":                   SCENARIO_DIR / "scn_all_x1.5",
    "all_x2":                     SCENARIO_DIR / "scn_all_x2",
    "all_x2.5":                   SCENARIO_DIR / "scn_all_x2.5",
    "Volume_all_1pt5x":           SCENARIO_DIR / "scn_Volume_all_1pt5x",
    "Volume_all_2pt0x":           SCENARIO_DIR / "scn_Volume_all_2pt0x",
    "BCx_x1.25":                  SCENARIO_DIR / "scn_BCx_x1.25",
    "BCx_x1.5":                   SCENARIO_DIR / "scn_BCx_x1.5",
    "BCx_x2":                     SCENARIO_DIR / "scn_BCx_x2",
    "BCx_Vol_double":             SCENARIO_DIR / "scn_BCx_Vol_double",
    "Urine_Vol_1pt5x":            SCENARIO_DIR / "scn_Urine_Vol_1pt5x",
    "Stool_Vol_1pt5x":            SCENARIO_DIR / "scn_Stool_Vol_1pt5x",
    "BCx_Bottle_Shortage":        SCENARIO_DIR / "scn_BCx_Bottle_Shortage",
    "BloodAgar__Shortage":        SCENARIO_DIR / "scn_BloodAgar__Shortage",
    "Accessioning_tech_day_0pt5": SCENARIO_DIR / "scn_Accessioning_tech_day_0pt5",
    "Routine_day_0pt5":           SCENARIO_DIR / "scn_Routine_day_0pt5",
}

SCENARIO_ORDER = [
    "baseline",
    "all_x1.25",
    "all_x1.5",
    "all_x2",
    "all_x2.5",
    "Volume_all_1pt5x",
    "Volume_all_2pt0x",
    "BCx_x1.25",
    "BCx_x1.5",
    "BCx_x2",
    "BCx_Vol_double",
    "Urine_Vol_1pt5x",
    "Stool_Vol_1pt5x",
    "BCx_Bottle_Shortage",
    "BloodAgar__Shortage",
    "Accessioning_tech_day_0pt5",
    "Routine_day_0pt5",
]

SPECIMEN_ORDER = [
    "Blood culture",
    "Body fluid",
    "Bone",
    "Tissue",
    "Tissue (FNA)",
    "Tissue (genital)",
    "Wound",
    "Wound (genital)",
    "Stool",
    "Respiratory (non-CF)",
    "Respiratory (CF)",
    "Urine_nonInv",
    "Urine_Inv",
]

SPECIMEN_COLORS = {
    "Blood culture": "#d62728",
    "Body fluid": "#ff7f0e",
    "Bone": "#8c564b",
    "Tissue": "#9467bd",
    "Tissue (FNA)": "#e377c2",
    "Tissue (genital)": "#f7b6d2",
    "Wound": "#1f77b4",
    "Wound (genital)": "#6baed6",
    "Stool": "#7f7f7f",
    "Respiratory (non-CF)": "#2ca02c",
    "Respiratory (CF)": "#17becf",
    "Urine_nonInv": "#eda100",
    "Urine_Inv": "#bcbd22",
}

LEGEND_COLUMNS = 2

OBSERVED_2024 = Path("data/observed_2024.csv")
OBSERVED_2025 = Path("data/observed_2025.csv")


# ============================================================
# SPECIMEN GROUPS
# ============================================================

GROUPS = {
    "Blood culture": ["BCx"],
    "Body fluid": ["BodyFluid"],
    "Bone": ["Bone_Cx"],
    "Tissue": ["Tissue"],
    "Tissue (FNA)": ["Tissue_FNA"],
    "Tissue (genital)": ["Tissue_genital"],
    "Wound": ["Wound"],
    "Wound (genital)": ["Wound_Genital"],
    "Stool": [
        "Stool",
        "Stool_Ecoli",
        "Stool_EcoliRoutine",
        "Stool_Campy",
        "Stool_Vibrio",
        "Stool_Yersinia",
    ],
    "Respiratory (non-CF)": ["Respiratory", "Resp_NonCF"],
    "Respiratory (CF)": ["Resp_CystFibrosis", "Resp_CF"],
    "Urine_nonInv": ["Urine_NonInvasive"],
    "Urine_Inv": ["Urine_Invasive"],
}


def save_both(fig, stem, out_dir=OUTPUT_DIR, dpi=DPI):
    """Save <stem>_labelled.png (white bg, visible axes & labels) and <stem>_unlabelled.png (transparent bg, tight crop around axes & ticks)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Labelled version: solid white background, visible axes, tick labels, titles, and legends
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


def selected_scenarios():
    scenarios = SCENARIOS.copy()
    if not INCLUDE_MEDIA_SHORTAGE:
        scenarios.pop("BCx_Bottle_Shortage", None)
        scenarios.pop("BloodAgar__Shortage", None)
    return scenarios


def scenario_frames():
    out = []
    scenarios = selected_scenarios()
    for name, folder in scenarios.items():
        if not folder.exists():
            print(f"  WARNING: skipping missing scenario directory: {folder}")
            continue
        print(f"Loading '{name}' from {folder}")
        s, _, _ = fc.load_sim(folder, fc.invert(GROUPS))
        if s.empty:
            raise ValueError(f"No simulation data found in {folder}")
        r = (
            s.groupby(["group", "rep"])["tat_h"]
            .agg(
                p50=lambda x: np.percentile(x, 50),
                p95=lambda x: np.percentile(x, 95),
                n="size",
            )
            .reset_index()
        )
        r["scenario"] = name
        out.append(r)
    return pd.concat(out, ignore_index=True)


def observed_tat_summary():
    files = {"2024": OBSERVED_2024, "2025": OBSERVED_2025}
    rows = []
    for year, path in files.items():
        if not path.exists():
            continue
        df = pd.read_csv(path)
        for column, metric in [("tat_median", "p50"), ("tat_95", "p95")]:
            if column in df.columns:
                rows.append({
                    "year": year,
                    "metric": metric,
                    "observed_mean": df[column].mean(),
                    "n": df[column].notna().sum(),
                })
    observed = pd.DataFrame(rows)
    if not observed.empty:
        observed.to_csv(OUTPUT_DIR / "table_observed_TAT.csv", index=False, float_format="%.3f")
    return observed


def calculate_scenario_differences(scn):
    base = scn[scn.scenario == BASELINE].copy()
    if base.empty:
        raise SystemExit(f"SCENARIOS has no entry named '{BASELINE}'")

    allrows = []

    # Baseline summary rows (absolute TAT in hours, mean and 95% CI across replications)
    for metric in ["p50", "p95"]:
        g_base = base.groupby(["group"])[metric]
        s_base = pd.DataFrame({"mean": g_base.mean(), "se": g_base.sem(), "n": g_base.count()}).reset_index()
        s_base["ci"] = stats.t.ppf(0.975, (s_base["n"] - 1).clip(lower=1)) * s_base["se"]
        s_base["scenario"] = BASELINE
        s_base["metric"] = metric
        allrows.append(s_base)

    # Paired differences (scenario minus baseline)
    for scenario in scn.scenario.unique():
        if scenario == BASELINE:
            continue
        current = scn[scn.scenario == scenario]
        m = current.merge(
            base[["group", "rep", "p50", "p95"]].rename(columns={"p50": "p50_base", "p95": "p95_base"}),
            on=["group", "rep"],
            how="inner",
            validate="one_to_one",
        )
        if m.empty:
            raise ValueError(f"No paired replications for scenario: {scenario}")

        for metric in ["p50", "p95"]:
            m_metric = m.copy()
            m_metric["delta"] = m_metric[metric] - m_metric[f"{metric}_base"]
            g = m_metric.groupby(["group"])["delta"]
            s = pd.DataFrame({"mean": g.mean(), "se": g.sem(), "n": g.count()}).reset_index()
            s["ci"] = stats.t.ppf(0.975, (s["n"] - 1).clip(lower=1)) * s["se"]
            s["scenario"] = scenario
            s["metric"] = metric
            allrows.append(s)
    return pd.concat(allrows, ignore_index=True)


def scenario_plot(s, metric, xlabel, stem, scens):
    groups = fc.ordered(SPECIMEN_ORDER, s["group"])
    colors = {g_: SPECIMEN_COLORS.get(g_, fc.FALLBACK_PALETTE[i % 8]) for i, g_ in enumerate(groups)}
    top_in = fc.legend_height_in(len(groups), LEGEND_COLUMNS)
    h_in = PNG_HEIGHT if PNG_HEIGHT else 0.7 * len(scens) + 0.8 + top_in

    fig, ax = fc.new_fig(
        PNG_WIDTH,
        h_in,
        left_in=LEFT_MARGIN_IN,
        right_in=0.2,
        bottom_in=0.6,
        top_in=top_in,
    )

    step = 0.8 / max(len(groups), 1)
    for i, scenario in enumerate(scens):
        for j, group in enumerate(groups):
            r = s[(s.scenario == scenario) & (s.group == group)]
            if r.empty:
                continue
            r = r.iloc[0]
            ax.errorbar(
                r["mean"],
                i - 0.4 + step * (j + 0.5),
                xerr=r["ci"],
                fmt="o",
                markersize=3.4,
                color=colors[group],
                ecolor=colors[group],
                elinewidth=0.9,
                markeredgecolor="white",
                markeredgewidth=0.4,
            )

    ax.axvline(0, color=fc.INK, linewidth=0.8)
    if BASELINE in scens and len(scens) > 1:
        base_idx = scens.index(BASELINE)
        ax.axhspan(base_idx - 0.5, base_idx + 0.5, color="#f2f2f2", zorder=0)
        ax.axhline(base_idx + 0.5, color=fc.INK, linewidth=0.6, linestyle="--", alpha=0.5)

    ylabels = [
        "Baseline TAT (h)" if x == BASELINE else textwrap.fill(x.replace("_", " "), 22)
        for x in scens
    ]
    ax.set_yticks(range(len(scens)))
    ax.set_yticklabels(ylabels)
    ax.set_ylim(-0.6, len(scens) - 0.4)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Stress-test scenario")

    handles = [Line2D([0], [0], marker="o", color="w", markerfacecolor=colors[g_], markersize=5, label=g_) for g_ in groups]
    fc.top_legend(ax, handles, ncol=LEGEND_COLUMNS)
    save_both(fig, stem, OUTPUT_DIR, DPI)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fc.apply_style()
    plt.rcParams.update({"figure.facecolor": "white", "axes.facecolor": "white"})

    scn = scenario_frames()
    results = calculate_scenario_differences(scn)
    available = [x for x in SCENARIO_ORDER if x in results["scenario"].unique()]

    results.to_csv(OUTPUT_DIR / "table4_stress_scenarios.csv", index=False, float_format="%.3f")

    for metric, xlabel, stem in [
        ("p95", "95th percentile TAT: baseline (h) & Δ vs baseline (h)", "03a_stress_delta_p95"),
        ("p50", "Median TAT: baseline (h) & Δ vs baseline (h)", "03b_stress_delta_p50"),
    ]:
        s = results[results.metric == metric]
        scenario_plot(s, metric, xlabel, stem, available)

    observed_tat_summary()


if __name__ == "__main__":
    main()