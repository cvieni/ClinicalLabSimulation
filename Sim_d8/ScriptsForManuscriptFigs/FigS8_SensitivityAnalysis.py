
# Sensi_Analysis/
# │
# ├── mc_A/                         # Baseline
# │
# ├── mc_B/                         # BCx culture positivity
# │   ├── set1/
# │   ├── set2/
# │   ├── set3/
# │   └── set4/
# │
# ├── mc_C/                         # Urine culture positivity
# │   ├── set1/
# │   ├── set2/
# │   ├── set3/
# │   └── set4/
# │
# ├── mc_D/                         # Stool culture positivity
# │   ├── set1/
# │   ├── set2/
# │   ├── set3/
# │   └── set4/
# │
# └── ... mc_I/

#!/usr/bin/env python3

#!/usr/bin/env python3
"""
Parameter sensitivity analysis: Tornado plots for median and 95th percentile TAT.

Each parameter has four subdirectories (set1, set2, set3, set4), compared against
the common baseline (mc_A) paired by Monte Carlo replication.

Outputs (in Sim_d8/manuscript_png/FigS8_SensiAnalysis):
    FigS8A_tornado_median_tat_labelled.png & _unlabelled.png
    FigS8B_tornado_p95_tat_labelled.png & _unlabelled.png
    table_parameter_sensitivity.csv

Run:
    python FigS8_SensitivityAnalysis.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from scipy import stats

import fig_common as fc

# =========================================================== SETTINGS (edit these) ===========================================================
BASE_DIR = Path(__file__).resolve().parent.parent.parent
SIM_DIR = Path(__file__).resolve().parent.parent

OUTPUT_DIR = SIM_DIR / "manuscript_png/FigS8_SensiAnalysis"
SCENARIO_DIR = SIM_DIR / "results_experiments/Sensi_Analysis"
BASELINE_DIR = SCENARIO_DIR / "mc_A"

OBSERVED_2024 = SIM_DIR / "data/observed_2024.csv"
OBSERVED_2025 = SIM_DIR / "data/observed_2025.csv"

OBSERVED_COLORS = {
    "2024 observed average": "#2166AC",
    "2025 observed average": "#B2182B",
}

PARAMETER_SWEEPS = {
    "BCx_culture_positivity": SCENARIO_DIR / "mc_B",
    "Urine_culture_positivity": SCENARIO_DIR / "mc_C",
    "Stool_culture_positivity": SCENARIO_DIR / "mc_D",
    "Routines_culture_positivity": SCENARIO_DIR / "mc_E",
    "Routines_MultipleIsolatePercent": SCENARIO_DIR / "mc_F",
    "Plating_time": SCENARIO_DIR / "mc_G",
    "Subculture_EvalTime": SCENARIO_DIR / "mc_H",
    "Repeat_ReadTime": SCENARIO_DIR / "mc_I",
}

SETTINGS = ["set1", "set2", "set3", "set4"]

PARAMETER_LABELS = {
    "BCx_culture_positivity": "Blood culture positivity",
    "Urine_culture_positivity": "Urine culture positivity",
    "Stool_culture_positivity": "Stool culture positivity",
    "Routines_culture_positivity": "Routine culture positivity",
    "Routines_MultipleIsolatePercent": "Multiple isolate percentage",
    "Plating_time": "Plating time",
    "Subculture_EvalTime": "Subculture evaluation time",
    "Repeat_ReadTime": "Repeat read time",
}

SETTING_LABELS = {
    "set1": "Setting 1",
    "set2": "Setting 2",
    "set3": "Setting 3",
    "set4": "Setting 4",
}

# Colors for the four parameter settings
SETTING_COLORS = {
    "set1": "#2166AC",
    "set2": "#67A9CF",
    "set3": "#EF8A62",
    "set4": "#B2182B",
}

# Figure dimensions
PNG_WIDTH = 6.5
PNG_HEIGHT = 5.4
LEFT_MARGIN_IN = 1.85
RIGHT_MARGIN_IN = 0.25
BOTTOM_MARGIN_IN = 0.60
TOP_MARGIN_IN = 0.72
DPI = 300
LEGEND_COLUMNS = 4

# Specimen mapping used by fig_common
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
        "Stool", "Stool_Ecoli", "Stool_EcoliRoutine",
        "Stool_Campy", "Stool_Vibrio", "Stool_Yersinia",
    ],
    "Respiratory (non-CF)": ["Respiratory", "Resp_NonCF"],
    "Respiratory (CF)": ["Resp_CystFibrosis", "Resp_CF"],
    "Urine_nonInv": ["Urine_NonInvasive"],
    "Urine_Inv": ["Urine_Invasive"],
}
# ==============================================================================================================================================


def save_both(fig, stem, out_dir: Path = OUTPUT_DIR, dpi: int = DPI):
    """Save <stem>_labelled.png (white bg, visible axes) and <stem>_unlabelled.png (transparent bg, tick marks only) on an identical canvas."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Labelled version: solid white background, visible axes, tick labels, titles, and legend
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


# ============================================================
# LOAD AND SUMMARIZE SIMULATION DATA
# ============================================================
def replication_metrics(folder: Path) -> pd.DataFrame:
    """Load simulation data and calculate median and p95 TAT for each Monte Carlo replication."""
    print(f"Loading: {folder}")

    if not folder.exists():
        raise FileNotFoundError(f"Missing simulation folder: {folder}")

    s, _, _ = fc.load_sim(folder, fc.invert(GROUPS))
    if s.empty:
        raise ValueError(f"No simulation data found in {folder}")

    missing = {"rep", "tat_h"} - set(s.columns)
    if missing:
        raise ValueError(f"Missing columns {missing} in {folder}")

    return (
        s.groupby("rep")["tat_h"]
        .agg(
            p50=lambda x: np.percentile(x, 50),
            p95=lambda x: np.percentile(x, 95),
            n="size",
        )
        .reset_index()
    )


def load_observed_tat():
    """Load optional observed TAT reference summary if files exist."""
    if not OBSERVED_2024.exists() or not OBSERVED_2025.exists():
        print("\nObserved summary files not found; skipping observed reference lines.")
        return None

    obs24 = pd.read_csv(OBSERVED_2024)
    obs25 = pd.read_csv(OBSERVED_2025)

    observed = {
        "p50": {
            "2024 observed average": obs24["tat_median"].mean(),
            "2025 observed average": obs25["tat_median"].mean(),
        },
        "p95": {
            "2024 observed average": obs24["tat_95"].mean(),
            "2025 observed average": obs25["tat_95"].mean(),
        },
    }

    print("\nObserved average TAT:")
    print(f"  2024 median: {observed['p50']['2024 observed average']:.2f} h")
    print(f"  2025 median: {observed['p50']['2025 observed average']:.2f} h")
    print(f"  2024 p95:    {observed['p95']['2024 observed average']:.2f} h")
    print(f"  2025 p95:    {observed['p95']['2025 observed average']:.2f} h")
    return observed


# ============================================================
# PAIRED PARAMETER SENSITIVITY ANALYSIS
# ============================================================
def sensitivity_frames() -> pd.DataFrame:
    print("\nLoading baseline simulations...")
    base = replication_metrics(BASELINE_DIR)
    if base.empty:
        raise ValueError("Baseline contains no replications.")
    print(f"Baseline replications: {len(base)}")

    results = []
    for parameter, folder in PARAMETER_SWEEPS.items():
        print(f"\nParameter: {parameter}")
        for setting in SETTINGS:
            setting_dir = folder / setting
            current = replication_metrics(setting_dir)

            paired = current.merge(
                base[["rep", "p50", "p95"]].rename(columns={"p50": "p50_base", "p95": "p95_base"}),
                on="rep",
                how="inner",
                validate="one_to_one",
            )

            if paired.empty:
                raise ValueError(f"No paired replications for {parameter}/{setting}")

            if len(paired) != len(current) or len(paired) != len(base):
                print(
                    f"  WARNING: {parameter}/{setting}: {len(paired)} paired replications "
                    f"(baseline={len(base)}, setting={len(current)})"
                )

            for metric in ["p50", "p95"]:
                delta = paired[metric] - paired[f"{metric}_base"]
                n = delta.count()
                mean = delta.mean()
                se = delta.sem()
                ci = stats.t.ppf(0.975, n - 1) * se if n > 1 else np.nan

                results.append({
                    "parameter": parameter,
                    "setting": setting,
                    "metric": metric,
                    "mean_delta": mean,
                    "se": se,
                    "ci95": ci,
                    "n_rep": n,
                })

                print(
                    f"  {setting} | {metric}: {mean:+.3f} h (95% CI: {mean - ci:+.3f}, {mean + ci:+.3f})"
                    if np.isfinite(ci)
                    else f"  {setting} | {metric}: {mean:+.3f} h"
                )

    return pd.DataFrame(results)


# ============================================================
# TORNADO PLOT
# ============================================================
def tornado_plot(data: pd.DataFrame, metric: str, xlabel: str, filename: str, observed=None):
    s = data[data["metric"] == metric].copy()
    if s.empty:
        raise ValueError(f"No data available for {metric}")

    ranking = (
        s.groupby("parameter")["mean_delta"]
        .apply(lambda x: x.abs().max())
        .sort_values(ascending=False)
    )
    parameter_order = ranking.index.tolist()

    fig, ax = fc.new_fig(
        PNG_WIDTH,
        PNG_HEIGHT,
        left_in=LEFT_MARGIN_IN,
        right_in=RIGHT_MARGIN_IN,
        bottom_in=BOTTOM_MARGIN_IN,
        top_in=TOP_MARGIN_IN,
    )

    offsets = np.linspace(-0.30, 0.30, len(SETTINGS))

    for i, parameter in enumerate(parameter_order):
        for j, setting in enumerate(SETTINGS):
            r = s[(s["parameter"] == parameter) & (s["setting"] == setting)]
            if r.empty:
                continue
            r = r.iloc[0]
            mean = r["mean_delta"]
            ci = r["ci95"]
            xerr = ci if np.isfinite(ci) else None

            ax.barh(
                i + offsets[j],
                mean,
                xerr=xerr,
                height=0.15,
                color=SETTING_COLORS[setting],
                edgecolor="white",
                linewidth=0.4,
                error_kw={
                    "elinewidth": 0.9,
                    "capsize": 2,
                    "capthick": 0.8,
                },
            )

    ax.axvline(0, color=fc.INK, linewidth=0.9, linestyle="-", zorder=0)

    labels = [PARAMETER_LABELS.get(p, p.replace("_", " ")) for p in parameter_order]
    ax.set_yticks(range(len(parameter_order)))
    ax.set_yticklabels(labels)
    ax.set_ylim(-0.6, len(parameter_order) - 0.4)
    ax.invert_yaxis()

    extent = np.abs(s["mean_delta"].to_numpy())
    ci_extent = s["ci95"].fillna(0).to_numpy()
    max_extent = np.max(extent + ci_extent)
    if not np.isfinite(max_extent) or max_extent == 0:
        max_extent = 1.0
    max_extent *= 1.12

    ax.set_xlim(-max_extent, max_extent)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Parameter")
    ax.grid(axis="x", alpha=0.25, linewidth=0.6)
    ax.grid(axis="y", visible=False)

    handles = [
        Patch(facecolor=SETTING_COLORS[st], edgecolor="none", label=SETTING_LABELS.get(st, st))
        for st in SETTINGS
    ]
    if observed and metric in observed:
        for label in observed[metric]:
            handles.append(
                Line2D([0], [0], color=OBSERVED_COLORS[label], linestyle="--", linewidth=1.3, label=label)
            )

    ax.legend(
        handles=handles,
        loc="lower left",
        bbox_to_anchor=(0.0, 1.01),
        ncol=LEGEND_COLUMNS,
        frameon=False,
        fontsize=7.0,
        columnspacing=1.2,
        handlelength=1.4,
    )

    save_both(fig, filename, OUTPUT_DIR, DPI)


# ============================================================
# MAIN
# ============================================================
def main():
    fc.apply_style()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = sensitivity_frames()
    results.to_csv(
        OUTPUT_DIR / "table_parameter_sensitivity.csv",
        index=False,
        float_format="%.4f",
    )

    observed = load_observed_tat()

    tornado_plot(
        results,
        metric="p50",
        xlabel="Change in median TAT vs baseline (hours)",
        filename="FigS8A_tornado_median_tat",
        observed=observed,
    )

    tornado_plot(
        results,
        metric="p95",
        xlabel="Change in 95th percentile TAT vs baseline (hours)",
        filename="FigS8B_tornado_p95_tat",
        observed=observed,
    )

    print(f"\nParameter sensitivity analysis complete. Saved in {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()