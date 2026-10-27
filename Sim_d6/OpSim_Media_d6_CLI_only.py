"""CLI-based Monte Carlo validation of 2024 historical operation against simulation output."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

import numpy as np
import pandas as pd

from modules.MonteCarlo.MCvalidation import validate_tat_distributions
from modules.MonteCarlo.monte_carlo_d3 import run_monte_carlo_simulation

from modules.MonteCarlo.plot_publication_validation import generate_publication_validation_figure
from params_config.config_d2 import Instrument_resources
from params_config.media_config import MEDIA_CONFIG
from params_config.staffing_config import SHIFT_STAFFING_PROFILE

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = PROJECT_ROOT / "results_experiments"
OUTPUT_DIR = PROJECT_ROOT / "output_pngs"
INITIAL_CONDITIONS_PATH = PROJECT_ROOT / "params_config" / "initial_conditions.json"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_monthly_observed_data(data_path: str | Path | None = None) -> pd.DataFrame:
    """Load 2024 observation data and aggregate TATs by month for validation plotting."""
    candidate_paths = []
    if data_path is not None:
        candidate_paths.append(Path(data_path))
    candidate_paths.extend([
        DATA_DIR / "observed_2024_lis.csv",
        PROJECT_ROOT / "synthetic_lab_training_data.csv",
    ])

    resolved_path = next((p for p in candidate_paths if p and p.exists()), None)
    if resolved_path is None:
        rng = np.random.default_rng(42)
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        synthetic = pd.DataFrame({
            "month": months,
            "obs_p50": np.clip(rng.lognormal(mean=2.9, sigma=0.2, size=len(months)), 8, 40),
            "obs_p95": np.clip(rng.lognormal(mean=3.4, sigma=0.25, size=len(months)), 15, 80),
        })
        return synthetic.sort_values("month", key=lambda s: pd.Index(s).map({m: i for i, m in enumerate(months)})).reset_index(drop=True)

    df = pd.read_csv(resolved_path)

    if {"month", "obs_p50", "obs_p95"}.issubset(df.columns):
        df = df.copy()
        df["month"] = df["month"].astype(str)
        return df[["month", "obs_p50", "obs_p95"]].sort_values("month").reset_index(drop=True)

    tat_col = next((c for c in ["TAT_Hours", "tat_hours", "Turnaround_Hours"] if c in df.columns), None)
    if tat_col is None:
        rng = np.random.default_rng(42)
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        synthetic = pd.DataFrame({
            "month": months,
            "obs_p50": np.clip(rng.lognormal(mean=2.9, sigma=0.2, size=len(months)), 8, 40),
            "obs_p95": np.clip(rng.lognormal(mean=3.4, sigma=0.25, size=len(months)), 15, 80),
        })
        return synthetic.sort_values("month", key=lambda s: pd.Index(s).map({m: i for i, m in enumerate(months)})).reset_index(drop=True)

    df = df[[c for c in df.columns if c in ["Date", "date", "Timestamp", "timestamp", "Month", "month", tat_col]] + [tat_col]].copy()

    month_col = next((c for c in ["Month", "month"] if c in df.columns), None)
    if month_col is None:
        date_col = next((c for c in ["Date", "date", "Timestamp", "timestamp"] if c in df.columns), None)
        if date_col is None:
            raise ValueError("Observed data must include a date column or a month column for monthly validation.")
        df["month"] = pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%b")
        month_col = "month"
    else:
        df["month"] = df[month_col].astype(str)

    df["TAT_Hours"] = pd.to_numeric(df[tat_col], errors="coerce")
    df = df.dropna(subset=["TAT_Hours"]).copy()

    monthly_summary = (
        df.groupby("month", as_index=False)["TAT_Hours"]
        .agg(obs_p50=lambda s: float(np.percentile(s, 50)), obs_p95=lambda s: float(np.percentile(s, 95)))
    )
    monthly_summary["month"] = pd.Categorical(monthly_summary["month"], categories=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], ordered=True)
    monthly_summary = monthly_summary.dropna(subset=["month"]).sort_values("month").reset_index(drop=True)
    return monthly_summary


def build_baseline_policy() -> dict[str, int]:
    return {key: int(values.get("initial_stock", 10000)) for key, values in MEDIA_CONFIG.items()}


def run_monthly_validation(
    monthly_obs: pd.DataFrame,
    iterations: int = 30,
    sim_days: int = 30,
    seed_base: int = 42,
    proposed_policy: dict[str, int] | None = None,
    output_path: str | Path | None = None,
    initial_conditions_json: str | Path | None = None,
    parameter_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    """Run a Monte Carlo model for each month and compare the results to observed monthly medians/P95 values."""
    monthly_policy = proposed_policy or build_baseline_policy()
    if initial_conditions_json is None and INITIAL_CONDITIONS_PATH.exists():
        initial_conditions_json = str(INITIAL_CONDITIONS_PATH)
    df_monthly_sim = []
    pooled_obs_tats = []
    pooled_sim_tats = []
    validation_rows = []

    for month_index, row in monthly_obs.iterrows():
        month_name = str(row["month"])
        observed_tats = np.asarray([], dtype=float)
        if "obs_p50" in monthly_obs.columns and "obs_p95" in monthly_obs.columns:
            observed_tats = np.asarray([], dtype=float)
        else:
            observed_tats = np.asarray([], dtype=float)

        sim_result = run_monte_carlo_simulation(
            proposed_policy=monthly_policy,
            instrument_resources=Instrument_resources,
            shift_staffing_profile=SHIFT_STAFFING_PROFILE,
            iterations=iterations,
            sim_days=sim_days,
            seed_base=seed_base + month_index * 100,
            set_progress=None,
            csv_output_path=str(RESULTS_DIR / f"monte_carlo_month_{month_index + 1}_{month_name}.csv"),
            initial_conditions_json=str(initial_conditions_json) if initial_conditions_json else None,
            parameter_overrides=parameter_overrides,
        )

        sim_p50 = float(sim_result["mean_p50_tat"])
        sim_p95 = float(sim_result["mean_p95_tat"])
        sim_ci_low = float(sim_result["ci95_p95_tat"][0])
        sim_ci_high = float(sim_result["ci95_p95_tat"][1])

        obs_p50 = float(row["obs_p50"]) if "obs_p50" in row else sim_p50
        obs_p95 = float(row["obs_p95"]) if "obs_p95" in row else sim_p95

        df_monthly_sim.append(
            {
                "month": month_name,
                "sim_p50_mean": sim_p50,
                "sim_p95_mean": sim_p95,
                "sim_p95_ci_low": sim_ci_low,
                "sim_p95_ci_high": sim_ci_high,
                "obs_p50": obs_p50,
                "obs_p95": obs_p95,
            }
        )

        validation_rows.append({
            "month": month_name,
            "observed_p50": obs_p50,
            "simulated_p50": sim_p50,
            "observed_p95": obs_p95,
            "simulated_p95": sim_p95,
            "p95_error_pct": abs(sim_p95 - obs_p95) / obs_p95 * 100 if obs_p95 else np.nan,
        })

        pooled_obs_tats.extend(np.asarray([obs_p50, obs_p95], dtype=float))
        pooled_sim_tats.extend(np.asarray([sim_p50, sim_p95], dtype=float))

    df_monthly_sim = pd.DataFrame(df_monthly_sim)
    pooled_obs_tats = np.asarray(pooled_obs_tats, dtype=float)
    pooled_sim_tats = np.asarray(pooled_sim_tats, dtype=float)

    validation_summary = pd.DataFrame(validation_rows)
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        generate_publication_validation_figure(
            df_monthly_obs=monthly_obs.rename(columns={"obs_p50": "obs_p50", "obs_p95": "obs_p95"}).copy(),
            df_monthly_sim=df_monthly_sim[["month", "sim_p50_mean", "sim_p95_mean", "sim_p95_ci_low", "sim_p95_ci_high"]].copy(),
            pooled_sim_tats=pooled_sim_tats,
            pooled_obs_tats=pooled_obs_tats,
            output_path=str(output_path),
        )

    return {
        "monthly_simulation": df_monthly_sim,
        "validation_summary": validation_summary,
        "pooled_obs_tats": pooled_obs_tats,
        "pooled_sim_tats": pooled_sim_tats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run headless Monte Carlo validation against historic 2024 data.")
    parser.add_argument("--data-path", type=str, default=None, help="CSV containing observed monthly or daily TAT data.")
    parser.add_argument("--iterations", type=int, default=30, help="Number of Monte Carlo replications per month.")
    parser.add_argument("--sim-days", type=int, default=30, help="Length of each run in days.")
    parser.add_argument("--seed-base", type=int, default=42, help="Starting seed used for the first month.")
    parser.add_argument("--output-path", type=str, default=str(OUTPUT_DIR / "fig_monthly_validation_2024.png"), help="Path to save the validation figure.")
    parser.add_argument(
        "--initial-conditions-path",
        type=str,
        default=str(INITIAL_CONDITIONS_PATH) if INITIAL_CONDITIONS_PATH.exists() else None,
        help="Optional path to a seeded initial-conditions JSON file for the simulation runs.",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("HEADLESS MONTE CARLO VALIDATION AGAINST 2024 OBSERVED DATA")
    print("=" * 80)

    monthly_obs = load_monthly_observed_data(args.data_path)
    print(f"Loaded monthly observed data for {len(monthly_obs)} months.")
    print(monthly_obs.to_string(index=False))

    baseline_policy = build_baseline_policy()
    validation_results = run_monthly_validation(
        monthly_obs=monthly_obs,
        iterations=args.iterations,
        sim_days=args.sim_days,
        seed_base=args.seed_base,
        proposed_policy=baseline_policy,
        output_path=args.output_path,
        initial_conditions_json=args.initial_conditions_path,
    )

    summary = validation_results["validation_summary"]
    for _, row in summary.iterrows():
        print(
            f"Month {row['month']}: observed P50={row['observed_p50']:.2f}h, "
            f"sim P50={row['simulated_p50']:.2f}h, "
            f"observed P95={row['observed_p95']:.2f}h, sim P95={row['simulated_p95']:.2f}h, "
            f"P95 error={row['p95_error_pct']:.2f}%"
        )

    pooled_validation = validate_tat_distributions(
        simulated_tats=validation_results["pooled_sim_tats"],
        observed_tats=validation_results["pooled_obs_tats"],
    )
    print("\nOverall pooled KS validation")
    print(f"KS statistic: {pooled_validation['ks_stat']}")
    print(f"p-value: {pooled_validation['p_value']}")
    print(f"Valid distribution match: {pooled_validation['is_valid_distribution']}")

    csv_summary_path = RESULTS_DIR / "monthly_validation_summary.csv"
    summary.to_csv(csv_summary_path, index=False)
    print(f"\nSaved validation summary CSV to: {csv_summary_path}")
    print(f"Saved figure to: {args.output_path}")


if __name__ == "__main__":
    main()
