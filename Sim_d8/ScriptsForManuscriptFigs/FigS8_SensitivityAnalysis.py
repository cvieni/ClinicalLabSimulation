#!/usr/bin/env python3
"""
Parameter sensitivity analysis: Tornado plots for median and 95th percentile TAT.

Reads one-at-a-time sensitivity runs produced by run_sensitivity.py
(results_experiments/sens/<param>__lo and <param>__hi, plus manifest.csv),
compared against the common baseline paired by Monte Carlo replication.

Outputs (in Sim_d8/manuscript_png/FigS8_SensiAnalysis):
    FigS8A_tornado_median_tat_labelled.png & _unlabelled.png
    FigS8B_tornado_p95_tat_labelled.png & _unlabelled.png
    table_parameter_sensitivity.csv

Run:
    python FigS8_SensitivityAnalysis.py
"""
import json
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
SENS_DIR = SIM_DIR / "results_experiments/sens"
BASELINE_DIR = SIM_DIR / "results_experiments/scn_baseline"

OBSERVED_2024 = SIM_DIR / "data/observed_2024.csv"
OBSERVED_2025 = SIM_DIR / "data/observed_2025.csv"

OBSERVED_COLORS = {
    "2024 observed average": "#2166AC",
    "2025 observed average": "#B2182B",
}

LEVELS = ["lo", "hi"]

LEVEL_LABELS = {
    "lo": "Low (-)",
    "hi": "High (+)",
}

LEVEL_COLORS = {
    "lo": "#2166AC",
    "hi": "#B2182B",
}

# Fixed X-axis limits & ticks (set to None for automatic scaling)
P50_XLIM = (-1.5, 1.5)
P50_XTICKS = np.arange(-1.50, 1.5, 0.5)

P95_XLIM = (-1.5, 1.5)
P95_XTICKS = np.arange(-1.50, 1.5, 0.5)

# Optional display names for parameters (falls back to formatted parameter name)
PARAMETER_LABELS = {
    "positive_specimen_rate": "Culture positivity rate",
    "phoenix_run_time_hours": "Phoenix AST run time",
}

# Optional filter: list parameter names to include, or None to include all found in SENS_DIR
ONLY_PARAMETERS = None

# Optional explicit top-to-bottom parameter order shared across both plots, or None to rank by RANK_BY_METRIC
PARAMETER_ORDER = None
RANK_BY_METRIC = "p50"       # "p50" or "p95" — determines shared parameter ordering when PARAMETER_ORDER is None

# Figure dimensions
PNG_WIDTH = 6.5
PNG_HEIGHT = 3.0
LEFT_MARGIN_IN = 0.0
RIGHT_MARGIN_IN = 0.0
BOTTOM_MARGIN_IN = 0.00
TOP_MARGIN_IN = 0.0
DPI = 300
LEGEND_COLUMNS = 2

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
    """Save <stem>_labelled.png (white bg, visible axes) and <stem>_unlabelled.png (transparent bg, tight crop around axes & ticks)."""
    out_dir.mkdir(parents=True, exist_ok=True)

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


def replication_metrics(folder: Path) -> pd.DataFrame:
    """Load simulation data and calculate median and p95 TAT for each Monte Carlo replication."""
    print(f"Loading: {folder}")
    if not folder.exists():
        raise FileNotFoundError(f"Missing simulation folder: {folder}")

    s, _, _ = fc.load_sim(folder, fc.invert(GROUPS))
    if s.empty:
        raise ValueError(f"No simulation data found in {folder}")

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
    return {
        "p50": {
            "2024 observed average": obs24["tat_median"].mean(),
            "2025 observed average": obs25["tat_median"].mean(),
        },
        "p95": {
            "2024 observed average": obs24["tat_95"].mean(),
            "2025 observed average": obs25["tat_95"].mean(),
        },
    }


def discover_sensitivity_runs():
    """Find (parameter, level, folder) runs from SENS_DIR/manifest.csv or <param>__lo|hi folders."""
    if not SENS_DIR.exists():
        raise SystemExit(
            f"Sensitivity folder not found: {SENS_DIR}\n"
            f"Run: python run_sensitivity.py --iterations 30 --sim-days 60 --seed 42 --baseline-dir results_experiments/scn_baseline"
        )

    runs = []
    base_dir = BASELINE_DIR if BASELINE_DIR.exists() else (SENS_DIR / "_baseline")
    manifest_path = SENS_DIR / "manifest.csv"

    if manifest_path.exists():
        mf = pd.read_csv(manifest_path)
        for _, row in mf.iterrows():
            param = str(row["param"])
            lev = str(row["level"])
            folder = Path(row["folder"])
            if not folder.is_absolute():
                folder = (SIM_DIR / folder).resolve()
            if param == "baseline" or lev == "base":
                if folder.exists():
                    base_dir = folder
                continue
            if ONLY_PARAMETERS and param not in ONLY_PARAMETERS:
                continue
            if (folder / "run_table.csv").exists():
                runs.append((param, lev, folder))
    else:
        for d in sorted(SENS_DIR.iterdir()):
            if not d.is_dir() or "__" not in d.name:
                continue
            param, lev = d.name.rsplit("__", 1)
            if lev not in LEVELS:
                continue
            if ONLY_PARAMETERS and param not in ONLY_PARAMETERS:
                continue
            if (d / "run_table.csv").exists():
                runs.append((param, lev, d))

    return base_dir, runs


def sensitivity_frames() -> pd.DataFrame:
    base_dir, runs = discover_sensitivity_runs()
    if not runs:
        raise SystemExit(
            f"No completed sensitivity runs found in {SENS_DIR}.\n"
            f"Run: python run_sensitivity.py --iterations 30 --sim-days 60 --seed 42 --baseline-dir results_experiments/scn_baseline"
        )

    print(f"\nLoading baseline simulations from {base_dir}...")
    base = replication_metrics(base_dir)
    print(f"Baseline replications: {len(base)}")

    results = []
    for parameter, level, folder in runs:
        current = replication_metrics(folder)
        paired = current.merge(
            base[["rep", "p50", "p95"]].rename(columns={"p50": "p50_base", "p95": "p95_base"}),
            on="rep",
            how="inner",
            validate="one_to_one",
        )
        if paired.empty:
            raise ValueError(f"No paired replications for {parameter}__{level}")

        for metric in ["p50", "p95"]:
            delta = paired[metric] - paired[f"{metric}_base"]
            n = delta.count()
            mean = delta.mean()
            se = delta.sem()
            ci = stats.t.ppf(0.975, n - 1) * se if n > 1 else np.nan

            results.append({
                "parameter": parameter,
                "level": level,
                "metric": metric,
                "mean_delta": mean,
                "se": se,
                "ci95": ci,
                "n_rep": n,
            })

    return pd.DataFrame(results)


def resolve_parameter_order(data: pd.DataFrame) -> list[str]:
    """Determine a single consistent parameter ordering shared across all tornado plots."""
    available = list(dict.fromkeys(data["parameter"].tolist()))
    if PARAMETER_ORDER:
        ordered = [p for p in PARAMETER_ORDER if p in available]
        remaining = [p for p in available if p not in ordered]
        return ordered + remaining

    ref = data[data["metric"] == RANK_BY_METRIC]
    if ref.empty:
        ref = data
    ranking = (
        ref.groupby("parameter")["mean_delta"]
        .apply(lambda x: x.abs().max())
        .sort_values(ascending=False)
    )
    return ranking.index.tolist()


def tornado_plot(
    data: pd.DataFrame,
    metric: str,
    parameter_order: list[str],
    xlabel: str,
    filename: str,
    xlim=None,
    xticks=None,
    observed=None,
):
    s = data[data["metric"] == metric].copy()
    if s.empty:
        raise ValueError(f"No data available for {metric}")

    h_in = PNG_HEIGHT if PNG_HEIGHT else max(3.2, 0.42 * len(parameter_order) + 1.4)

    fig, ax = fc.new_fig(
        PNG_WIDTH,
        h_in,
        left_in=LEFT_MARGIN_IN,
        right_in=RIGHT_MARGIN_IN,
        bottom_in=BOTTOM_MARGIN_IN,
        top_in=TOP_MARGIN_IN,
    )

    offsets = np.linspace(-0.18, 0.18, len(LEVELS))

    for i, parameter in enumerate(parameter_order):
        for j, level in enumerate(LEVELS):
            r = s[(s["parameter"] == parameter) & (s["level"] == level)]
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
                height=0.30,
                color=LEVEL_COLORS[level],
                edgecolor="white",
                linewidth=0.4,
                error_kw={
                    "elinewidth": 0.9,
                    "capsize": 2,
                    "capthick": 0.8,
                },
            )

    ax.axvline(0, color=fc.INK, linewidth=0.9, linestyle="-", zorder=0)

    labels = [PARAMETER_LABELS.get(p, p.replace("_", " ").capitalize()) for p in parameter_order]
    ax.set_yticks(range(len(parameter_order)))
    ax.set_yticklabels(labels)
    ax.set_ylim(-0.6, len(parameter_order) - 0.4)
    ax.invert_yaxis()

    if xlim is not None:
        ax.set_xlim(*xlim)
    else:
        extent = np.abs(s["mean_delta"].to_numpy())
        ci_extent = s["ci95"].fillna(0).to_numpy()
        max_extent = np.max(extent + ci_extent)
        if not np.isfinite(max_extent) or max_extent == 0:
            max_extent = 1.0
        max_extent *= 1.12
        ax.set_xlim(-max_extent, max_extent)

    if xticks is not None:
        ax.set_xticks(xticks)

    ax.set_xlabel(xlabel)
    ax.set_ylabel("Parameter")
    ax.grid(axis="x", alpha=0.25, linewidth=0.6)
    ax.grid(axis="y", visible=False)

    handles = [
        Patch(facecolor=LEVEL_COLORS[lv], edgecolor="none", label=LEVEL_LABELS.get(lv, lv))
        for lv in LEVELS
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


def main():
    fc.apply_style()
    plt.rcParams.update({"figure.facecolor": "white", "axes.facecolor": "white"})
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = sensitivity_frames()
    results.to_csv(
        OUTPUT_DIR / "table_parameter_sensitivity.csv",
        index=False,
        float_format="%.4f",
    )

    observed = load_observed_tat()
    shared_order = resolve_parameter_order(results)

    tornado_plot(
            results,
            metric="p50",
            parameter_order=shared_order,
            xlabel="Change in median TAT vs baseline (hours)",
            filename="FigS8A_tornado_median_tat",
            xlim=P50_XLIM,
            xticks=P50_XTICKS,
            observed=observed,
    )

    tornado_plot(
        results,
        metric="p95",
        parameter_order=shared_order,
        xlabel="Change in 95th percentile TAT vs baseline (hours)",
        filename="FigS8B_tornado_p95_tat",
        xlim=P95_XLIM,
        xticks=P95_XTICKS,
        observed=observed,
    )

    print(f"\nParameter sensitivity analysis complete. Saved in {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()