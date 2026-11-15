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
import numpy as np

from scipy.stats import ks_2samp

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

    fig = plt.figure(figsize=(16, 8))
    gs = fig.add_gridspec(2, 3, width_ratios=[1, 1, 1.2])

    line_axes = [
        fig.add_subplot(gs[0, 0]),
        fig.add_subplot(gs[0, 1]),
        fig.add_subplot(gs[1, 0]),
        fig.add_subplot(gs[1, 1]),
    ]

    for ax, param in zip(line_axes, param_cols[:4]):
        summary = df.groupby(param, as_index=False)[["overall_map_pct"]].mean().sort_values(param)
        ax.plot(summary[param], summary["overall_map_pct"], marker="o", linewidth=2, color="steelblue")
        ax.set_title(f"{param} vs Overall MAP", fontsize=10, fontweight="bold")
        ax.set_xlabel(param, fontsize=9)
        ax.set_ylabel("Overall MAP (%)", fontsize=9)
        ax.grid(True, linestyle=":", alpha=0.5)

    for ax in line_axes[len(param_cols[:4]):]:
        ax.axis("off")

    bar_ax = fig.add_subplot(gs[:, 2])
    top = df.sort_values("overall_map_pct", kind="mergesort").head(8).copy().reset_index(drop=True)

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

def compute_continuous_ks_analysis(raw_sim_csv: Path, raw_obs_csv: Path):
    """Loads raw individual specimen TATs and computes a continuous 2-sample KS test."""
    df_sim = pd.read_csv(raw_sim_csv)
    df_obs = pd.read_csv(raw_obs_csv)

    # Extract clean TAT continuous vectors
    sim_tats = df_sim["Total_TAT_Hours"].dropna().to_numpy()
    
    obs_tat_col = next((c for c in ["TAT_Hours", "tat_hours", "Turnaround_Hours"] if c in df_obs.columns), None)
    obs_tats = df_obs[obs_tat_col].dropna().to_numpy()

    # Perform continuous 2-sample Kolmogorov-Smirnov test
    ks_result = ks_2samp(sim_tats, obs_tats)
    
    return {
        "sim_tats": sim_tats,
        "obs_tats": obs_tats,
        "ks_stat": ks_result.statistic,
        "p_value": ks_result.pvalue,
    }

def plot_ks_ecdf_overlay(sim_tats: np.ndarray, obs_tats: np.ndarray, ks_stat: float, p_value: float, ax: plt.Axes):
    """Plots empirical CDFs of observed vs simulated TATs with KS distance callout."""
    # Compute sorted arrays for eCDF calculation
    sim_sorted = np.sort(sim_tats)
    obs_sorted = np.sort(obs_tats)
    
    sim_ecdf = np.arange(1, len(sim_sorted) + 1) / len(sim_sorted)
    obs_ecdf = np.arange(1, len(obs_sorted) + 1) / len(obs_sorted)

    ax.step(sim_sorted, sim_ecdf, label="Simulated eCDF", color="steelblue", linewidth=2)
    ax.step(obs_sorted, obs_ecdf, label="Observed LIS eCDF", color="darkorange", linestyle="--", linewidth=2)

    ax.set_xlabel("Turnaround Time (Hours)", fontsize=9)
    ax.set_ylabel("Cumulative Probability", fontsize=9)
    ax.set_title(f"Continuous KS Test (D = {ks_stat:.3f}, p = {p_value:.3e})", fontsize=10, fontweight="bold")
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(frameon=False, fontsize=8)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create parameter scan or continuous KS distribution plots.")
    parser.add_argument("--csv", type=str, default=str(DEFAULT_CSV), help="Tuning summary CSV file")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT), help="PNG output path")
    parser.add_argument("--raw-sim-csv", type=str, default=None, help="Raw simulation run CSV containing Total_TAT_Hours")
    parser.add_argument("--raw-obs-csv", type=str, default=None, help="Raw historical LIS CSV containing TAT_Hours")
    args = parser.parse_args()

    output_path = Path(args.output)

    # Pathway A: Raw Continuous KS Analysis
    if args.raw_sim_csv and args.raw_obs_csv:
        print("Computing continuous 2-sample Kolmogorov-Smirnov distribution test...")
        ks_data = compute_continuous_ks_analysis(Path(args.raw_sim_csv), Path(args.raw_obs_csv))

        fig, ax = plt.subplots(figsize=(8, 6))
        plot_ks_ecdf_overlay(
            ks_data["sim_tats"],
            ks_data["obs_tats"],
            ks_data["ks_stat"],
            ks_data["p_value"],
            ax,
        )
        fig.tight_layout()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=300)
        plt.close(fig)

        print(f"Continuous KS Stat: {ks_data['ks_stat']:.4f}")
        print(f"Continuous p-value: {ks_data['p_value']:.4e}")
        print(f"Saved eCDF comparison figure to: {output_path}")
        return

    # Pathway B: Pre-aggregated Parameter Tuning Summaries
    csv_path = Path(args.csv)
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

    raise ValueError("CSV structure does not match a recognizable parameter sweep output.")


if __name__ == "__main__":
    main()

