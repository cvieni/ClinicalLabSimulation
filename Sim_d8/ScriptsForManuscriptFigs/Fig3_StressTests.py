
#!/usr/bin/env python3

"""
Figure 4: Stress-test scenario comparison.

Change in TAT (scenario minus baseline), paired by replication,
mean and 95% CI.

Produces:
    03a_stress_delta_p95.png / .pdf
    03b_stress_delta_p50.png / .pdf
    table4_stress_scenarios.csv

Media shortage experiments are excluded by default.
Enable them only after running the ML pipeline on the real simulator.

Run:
    python Fig3_Scenario.py
"""

from pathlib import Path
import textwrap

import numpy as np
import pandas as pd
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
BARE = False

SCENARIO_DIR = Path("results_experiments/StressTest")

BASELINE = "baseline"

# Include media shortage experiments only after the ML pipeline
# has been run on the real simulator.
INCLUDE_MEDIA_SHORTAGE = True

SCENARIOS = {
    "baseline": Path(SCENARIO_DIR, "mc_A"),

    # Volume stress tests
    "Volume_all_1pt5x": Path(SCENARIO_DIR, "mc_B"),
    "Volume_all_2pt0x": Path(SCENARIO_DIR, "mc_C"),
    "BCx_Vol_double": Path(SCENARIO_DIR, "mc_D"),
    "Urine_Vol_1pt5x": Path(SCENARIO_DIR, "mc_E"),
    "Stool_Vol_1pt5x": Path(SCENARIO_DIR, "mc_F"),

    # Media shortages (optional)
    "BCx_Bottle_Shortage": Path(SCENARIO_DIR, "mc_G"),
    "BloodAgar__Shortage": Path(SCENARIO_DIR, "mc_H"),

    # Staffing stress tests
    "Accessioning_tech_day_0pt5": Path(SCENARIO_DIR, "mc_I"),
    "Routine_day_0pt5": Path(SCENARIO_DIR, "mc_J"),
}

# Plot order: top to bottom
SCENARIO_ORDER = [
    "Volume_all_1pt5x",
    "Volume_all_2pt0x",
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

# Observed annual data (absolute TAT benchmarks).
# These are saved separately because scenario plots show
# differences relative to baseline, not absolute TAT.
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


# ============================================================
# SCENARIO SELECTION
# ============================================================

def selected_scenarios():

    scenarios = SCENARIOS.copy()

    if not INCLUDE_MEDIA_SHORTAGE:
        scenarios.pop("BCx_Bottle_Shortage", None)
        scenarios.pop("BloodAgar__Shortage", None)

    return scenarios


# ============================================================
# LOAD SIMULATION DATA
# ============================================================

def scenario_frames():

    out = []

    scenarios = selected_scenarios()

    for name, folder in scenarios.items():

        print(f"\nLoading '{name}' from {folder}")

        if not folder.exists():
            raise FileNotFoundError(
                f"Missing scenario directory: {folder}"
            )

        s, _, _ = fc.load_sim(
            folder,
            fc.invert(GROUPS)
        )

        if s.empty:
            raise ValueError(
                f"No simulation data found in {folder}"
            )

        required = {"group", "rep", "tat_h"}
        missing = required - set(s.columns)

        if missing:
            raise ValueError(
                f"Missing columns {missing} in {folder}"
            )

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

        print(
            f"  Loaded {len(r)} group/replication combinations"
        )

    return pd.concat(out, ignore_index=True)


# ============================================================
# OBSERVED ANNUAL TAT BENCHMARKS
# ============================================================

def observed_tat_summary():

    files = {
        "2024": OBSERVED_2024,
        "2025": OBSERVED_2025,
    }

    rows = []

    for year, path in files.items():

        if not path.exists():
            print(
                f"WARNING: Observed data not found: {path}"
            )
            continue

        df = pd.read_csv(path)

        for column, metric in [
            ("tat_median", "p50"),
            ("tat_95", "p95"),
        ]:

            if column not in df.columns:
                raise ValueError(
                    f"Missing {column} in {path}"
                )

            rows.append({
                "year": year,
                "metric": metric,
                "observed_mean": df[column].mean(),
                "n": df[column].notna().sum(),
            })

    observed = pd.DataFrame(rows)

    if not observed.empty:

        observed.to_csv(
            OUTPUT_DIR / "table_observed_TAT.csv",
            index=False,
            float_format="%.3f",
        )

        print("\nObserved annual TAT benchmarks:")

        print(
            observed.pivot(
                index="year",
                columns="metric",
                values="observed_mean",
            ).round(2)
        )

    return observed


# ============================================================
# PAIRED SCENARIO ANALYSIS
# ============================================================

def calculate_scenario_differences(scn):

    base = scn[scn.scenario == BASELINE].copy()

    if base.empty:
        raise SystemExit(
            f"SCENARIOS has no entry named '{BASELINE}'"
        )

    allrows = []

    for scenario in scn.scenario.unique():

        if scenario == BASELINE:
            continue

        current = scn[scn.scenario == scenario]

        # Pair by specimen group and Monte Carlo replication
        m = current.merge(
            base[
                ["group", "rep", "p50", "p95"]
            ].rename(
                columns={
                    "p50": "p50_base",
                    "p95": "p95_base",
                }
            ),
            on=["group", "rep"],
            how="inner",
            validate="one_to_one",
        )

        if m.empty:
            raise ValueError(
                f"No paired replications for scenario: {scenario}"
            )

        # Detect missing or unmatched replications
        if len(m) != len(current):
            print(
                f"WARNING: {scenario}: "
                f"{len(m)} paired observations out of "
                f"{len(current)} scenario observations"
            )

        for metric in ["p50", "p95"]:

            m_metric = m.copy()
            m_metric["delta"] = (
                m_metric[metric] -
                m_metric[f"{metric}_base"]
            )

            g = m_metric.groupby(
                ["group"]
            )["delta"]

            s = pd.DataFrame({
                "mean": g.mean(),
                "se": g.sem(),
                "n": g.count(),
            }).reset_index()

            s["ci"] = (
                stats.t.ppf(
                    0.975,
                    (s["n"] - 1).clip(lower=1)
                ) * s["se"]
            )

            s["scenario"] = scenario
            s["metric"] = metric

            allrows.append(s)

    return pd.concat(allrows, ignore_index=True)


# ============================================================
# SCENARIO FIGURES
# ============================================================

def scenario_plot(s, metric, xlabel, stem, scens):

    groups = fc.ordered(
        SPECIMEN_ORDER,
        s["group"]
    )

    colors = {
        g_: SPECIMEN_COLORS.get(
            g_,
            fc.FALLBACK_PALETTE[i % 8]
        )
        for i, g_ in enumerate(groups)
    }

    top_in = fc.legend_height_in(
        len(groups),
        LEGEND_COLUMNS
    )

    h_in = (
        PNG_HEIGHT
        if PNG_HEIGHT
        else 0.7 * len(scens) + 0.8 + top_in
    )

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

            r = s[
                (s.scenario == scenario) &
                (s.group == group)
            ]

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

    # Baseline reference
    ax.axvline(
        0,
        color=fc.INK,
        linewidth=0.8
    )

    ax.set_yticks(range(len(scens)))

    ax.set_yticklabels([
        textwrap.fill(
            x.replace("_", " "),
            22
        )
        for x in scens
    ])

    ax.set_ylim(
        -0.6,
        len(scens) - 0.4
    )

    ax.invert_yaxis()

    ax.grid(axis="y", visible=False)

    ax.set_xlabel(xlabel)
    ax.set_ylabel("Stress-test scenario")

    handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=colors[g_],
            markersize=5,
            label=g_,
        )
        for g_ in groups
    ]

    fc.top_legend(
        ax,
        handles,
        ncol=LEGEND_COLUMNS
    )

    fc.save_both(
        fig,
        stem,
        OUTPUT_DIR,
        DPI,
        BARE
    )

    plt.close(fig)


# ============================================================
# MAIN
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    fc.apply_style()

    print("\n======================================")
    print("STRESS TEST SCENARIO ANALYSIS")
    print("======================================")

    if INCLUDE_MEDIA_SHORTAGE:
        print("Media shortage experiments: ENABLED")
    else:
        print("Media shortage experiments: DISABLED")

    # Load simulation data
    scn = scenario_frames()

    # Calculate paired scenario differences
    results = calculate_scenario_differences(scn)

    # Determine scenario plotting order
    available = [
        x for x in SCENARIO_ORDER
        if x in results["scenario"].unique()
    ]

    # Save complete results
    results.to_csv(
        OUTPUT_DIR / "table4_stress_scenarios.csv",
        index=False,
        float_format="%.3f",
    )

    # Median and 95th percentile plots
    for metric, xlabel, stem in [
        (
            "p95",
            "Δ 95th percentile TAT vs baseline (h)",
            "03a_stress_delta_p95",
        ),
        (
            "p50",
            "Δ median TAT vs baseline (h)",
            "03b_stress_delta_p50",
        ),
    ]:

        s = results[
            results.metric == metric
        ]

        scenario_plot(
            s,
            metric,
            xlabel,
            stem,
            available,
        )

    # Observed annual averages are absolute TAT values.
    # Save them separately rather than mixing them with
    # scenario-minus-baseline differences.
    observed_tat_summary()

    print("\n======================================")
    print("STRESS TEST ANALYSIS COMPLETE")
    print(f"Output: {OUTPUT_DIR}")
    print("======================================")


if __name__ == "__main__":
    main()
