"""Plot sensitivity-scan summaries for the local tuning workflow.

This script reads the CSV files produced by tune_parameters_sequentially.py and creates
quick summary plots showing how each parameter affects the validation error metrics.

Examples:
    python visualize_parameter_scan.py --csv results_experiments/parameter_tuning/multi_grid_joint_calibration_20261010_150424.csv
    python visualize_parameter_scan.py --csv results_experiments/parameter_tuning/positive_specimen_rate_local_tuning_full_20261010_141207.csv
    python visualize_parameter_scan.py --csv results_experiments/parameter_tuning/polymicrobial_workup_required_rate_repeat_workup_20261023_132325.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = PROJECT_ROOT / "output_pngs" / "parameter_scan_summary.png"


def _resolve_default_csv() -> Path:
    tuning_dir = PROJECT_ROOT / "results_experiments" / "parameter_tuning"
    if not tuning_dir.exists():
        return tuning_dir / "missing.csv"

    csv_files = sorted(tuning_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in csv_files:
        try:
            head = pd.read_csv(path, nrows=3)
        except Exception:
            continue
        if {"mean_p50_error_pct", "mean_p95_error_pct", "overall_map_pct"}.intersection(head.columns):
            return path
        if {"parameter", "value"}.issubset(head.columns):
            return path
    if not csv_files:
        raise FileNotFoundError(f"No tuning CSV files found under {tuning_dir}.")
    return csv_files[0]


DEFAULT_CSV = _resolve_default_csv()


def _detect_metric_columns(df: pd.DataFrame) -> list[str]:
    metric_names = {"mean_p50_error_pct", "mean_p95_error_pct", "overall_map_pct", "ks_stat", "p_value"}
    return [c for c in df.columns if c in metric_names]


def _detect_param_columns(df: pd.DataFrame, metric_names: list[str]) -> list[str]:
    protected = {"combo_label", "parameter_values", "best_value", "parameter", "value", "month"}
    protected.update(metric_names)
    return [c for c in df.columns if c not in protected and pd.api.types.is_numeric_dtype(df[c])]


def plot_single_parameter_scan(df: pd.DataFrame, output_path: Path) -> None:
    """Create a single-parameter line plot for 1D sweeps."""
    if "parameter" not in df.columns or "value" not in df.columns:
        raise ValueError("Single-parameter scan CSV must contain 'parameter' and 'value' columns.")

    param_name = df["parameter"].dropna().iloc[0]
    ordered = df.sort_values("value", kind="mergesort").reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(ordered["value"], ordered["mean_p50_error_pct"], marker="o", linewidth=2, label="Mean P50 error (%)")
    ax.plot(ordered["value"], ordered["mean_p95_error_pct"], marker="s", linewidth=2, label="Mean P95 error (%)")
    ax.plot(ordered["value"], ordered["overall_map_pct"], marker="^", linewidth=2, label="Overall MAP (%)")

    ax.set_xlabel(param_name)
    ax.set_ylabel("Percent error")
    ax.set_title(f"Parameter scan for {param_name}")
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(frameon=False)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=300)
    plt.close(fig)


def plot_multi_parameter_scan(df: pd.DataFrame, output_path: Path) -> None:
    """Summary plot for multi-parameter grid results with non-overlapping layout."""
    metric_names = _detect_metric_columns(df)
    param_cols = _detect_param_columns(df, metric_names)
    if not param_cols:
        raise ValueError("Multi-parameter scan CSV does not contain numeric parameter columns to plot.")

    # Create a 3-column grid layout: 2 columns for line plots, 1 wide column for the bar chart
    fig = plt.figure(figsize=(16, 8))
    gs = fig.add_gridspec(2, 3, width_ratios=[1, 1, 1.2])

    line_axes = [
        fig.add_subplot(gs[0, 0]),
        fig.add_subplot(gs[0, 1]),
        fig.add_subplot(gs[1, 0]),
        fig.add_subplot(gs[1, 1]),
    ]

    # Plot parameter trends
    for ax, param in zip(line_axes, param_cols[:4]):
        summary = df.groupby(param, as_index=False)[["overall_map_pct"]].mean().sort_values(param)
        ax.plot(summary[param], summary["overall_map_pct"], marker="o", linewidth=2, color="steelblue")
        ax.set_title(f"{param} vs overall MAP", fontsize=10, fontweight="bold")
        ax.set_xlabel(param, fontsize=9)
        ax.set_ylabel("Overall MAP (%)", fontsize=9)
        ax.grid(True, linestyle=":", alpha=0.5)

    # Hide extra unused line axes if fewer than 4 parameters exist
    for ax in line_axes[len(param_cols[:4]):]:
        ax.axis("off")

    # Dedicated right axis for top-ranked combinations bar chart
    bar_ax = fig.add_subplot(gs[:, 2])

    top = df.sort_values("overall_map_pct", kind="mergesort").head(8).copy().reset_index(drop=True)
    
    # Truncate labels cleanly so they don't overlap bars
    labels = [str(x)[:45] + "..." if len(str(x)) > 45 else str(x) for x in top["combo_label"]]
    values = top["overall_map_pct"].to_numpy()

    bar_ax.barh(labels[::-1], values[::-1], color="steelblue", height=0.6)
    bar_ax.invert_yaxis()
    bar_ax.set_xlabel("Overall MAP (%)", fontsize=9)
    bar_ax.set_title("Top-Ranked Combinations", fontsize=11, fontweight="bold")
    bar_ax.grid(True, axis="x", linestyle=":", alpha=0.4)
    bar_ax.tick_params(axis="y", labelsize=8)

    fig.suptitle("Parameter Scan Summary", fontsize=14, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.96])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=300)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a quick parameter-scan summary plot from tuning CSV output.")
    parser.add_argument("--csv", type=str, default=str(DEFAULT_CSV), help="CSV file from tune_parameters_sequentially.py")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT), help="PNG output path")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    output_path = Path(args.output)

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    metric_names = _detect_metric_columns(df)

    if "parameter" in df.columns and "value" in df.columns:
        plot_single_parameter_scan(df, output_path)
        print(f"Saved single-parameter scan figure to: {output_path}")
        return

    if metric_names:
        plot_multi_parameter_scan(df, output_path)
        print(f"Saved multi-parameter scan figure to: {output_path}")
        return

    raise ValueError("CSV does not look like a tuning result file.")


if __name__ == "__main__":
    main()
