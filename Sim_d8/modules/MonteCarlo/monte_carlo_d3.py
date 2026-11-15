# modules/monte_carlo.py

import os
import warnings
import concurrent.futures
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from modules.simulation_d4 import run_simulation
from modules.run_metrics import compute_tat_metrics
from modules.param_overrides import validate_overrides
from params_config.config_d2 import Instrument_resources

WINDOW_DIAG_KEYS = ("n_in_window", "n_rejected", "n_aborted", "n_incomplete_in_window")


# ==================================================================================
# == Single Worker Iteration =======================================================
# ==================================================================================
def _run_single_iteration(args: tuple) -> Dict[str, Any]:
    """Top-level helper for multiprocessing: one DES replication -> metrics dict.

    Overrides are applied (and rolled back) inside run_simulation, so a reused worker process
    never carries one scenario's parameters into the next.
    """
    (
        i,
        seed_base,
        sim_days,
        instrument_resources,
        shift_staffing_profile,
        proposed_policy,
        initial_conditions_json,
        parameter_overrides,
    ) = args

    iteration_seed = seed_base + i
    temp_dir = os.path.join(os.getcwd(), "temp")
    os.makedirs(temp_dir, exist_ok=True)
    worker_log_path = os.path.join(temp_dir, f"labsim_mc_{iteration_seed}.log")

    df_pivot, df_state, media_usage, _, stochastic_stats = run_simulation(
        sim_days=sim_days,
        seed=iteration_seed,
        instrument_resources=instrument_resources,
        shift_staffing_profile=shift_staffing_profile,
        initial_conditions_json=initial_conditions_json,
        parameter_overrides=parameter_overrides,
        set_progress=None,
        save_plots=False,
        log_filename=worker_log_path,
        export_diagnostics=False,          # per-process time-series CSVs are a single-run tool
    )

    # Compute stockouts and delays against proposed inventory caps
    run_delays = 0
    stockout_per_item = {}
    for item_type, cap in proposed_policy.items():
        consumed = media_usage.get(item_type, 0)
        deficit = max(0, consumed - cap)
        run_delays += deficit
        stockout_per_item[item_type] = deficit

    total_specimens = len(df_pivot) if not df_pivot.empty else 0

    plating_delays = (
        int((df_pivot["Wait_For_Plating_Mins"] > 120).sum())
        if "Wait_For_Plating_Mins" in df_pivot.columns
        else 0
    )

    # P50/P95 overall, by type, by arrival shift, by type x shift; measurement window only.
    tat_metrics, tat_summary, tat_values = compute_tat_metrics(df_pivot)

    window_diag = {k: stochastic_stats.get(k, 0) for k in WINDOW_DIAG_KEYS} if isinstance(stochastic_stats, dict) else {}

    return {
        "iteration": i,
        "seed": iteration_seed,
        "param_BCx_positivity": stochastic_stats.get("param_BCx_positivity", 0.0),
        "param_rejection_percent": stochastic_stats.get("param_rejection_percent", 0.0),
        "delays": run_delays,
        "plating_delays": plating_delays,
        "total_specimens": total_specimens,
        "media_usage": media_usage,
        "stockout_per_item": stockout_per_item,
        "tat_summary": tat_summary,
        "tat_values": tat_values,
        "tat_metrics": tat_metrics,
        "window_diag": window_diag,
    }


# ==================================================================================
# Replication statistics
# ==================================================================================
def _replication_stats(values) -> Dict[str, float]:
    """Summaries of one metric across replications.

    ci95_*  : t-based 95% CI for the MEAN of the metric (how precisely the model's expected value
              is known; shrinks with more replications).
    pi95_*  : empirical 2.5-97.5 percentile band of the replications (where ONE simulated month
              falls; this, not the CI, is what a single observed real month should be compared to).
    The old code used 1.96*sd/sqrt(iterations): a z-interval (too narrow for ~30 runs) of the mean,
    mislabelled as the comparison band, and divided by `iterations` rather than the number of
    runs that actually produced the metric.
    """
    arr = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    n = len(arr)
    if n == 0:
        warnings.warn("No replication produced this metric; reporting NaN instead of 0.")
        nan = float("nan")
        return dict(n=0, mean=nan, sd=nan, ci_lo=nan, ci_hi=nan, pi_lo=nan, pi_hi=nan)
    mean = float(arr.mean())
    sd = float(arr.std(ddof=1)) if n > 1 else 0.0
    half = float(sp_stats.t.ppf(0.975, n - 1) * sd / np.sqrt(n)) if n > 1 else 0.0
    pi_lo, pi_hi = (float(x) for x in np.percentile(arr, [2.5, 97.5]))
    return dict(n=n, mean=mean, sd=sd, ci_lo=mean - half, ci_hi=mean + half, pi_lo=pi_lo, pi_hi=pi_hi)


def summarize_run_table(run_table: pd.DataFrame) -> pd.DataFrame:
    """Per-metric summary across replications for every TAT column (overall, per type, per shift,
    per type x shift): the table to line up against the observed LIS month."""
    rows = []
    for col in run_table.columns:
        if col.startswith("tat_") and pd.api.types.is_numeric_dtype(run_table[col]):
            rows.append({"metric": col, **_replication_stats(run_table[col].tolist())})
    return pd.DataFrame(rows)


# ==================================================================================
# Function to actually run the simulation
# ==================================================================================
def run_monte_carlo_simulation(
    proposed_policy: Dict[str, int],
    instrument_resources: Dict[str, Any],
    shift_staffing_profile: Dict[str, Any],
    iterations: int = 30,
    sim_days: int = 30,
    seed_base: int = 42,
    set_progress=None,
    max_workers: Optional[int] = None,
    csv_output_path: str = "monte_carlo_results.csv",
    initial_conditions_json: Optional[str] = None,
    parameter_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Executes a Monte Carlo study across independent stochastic replications.

    NOTE sim_days must cover warmup_days + cooldown_days + the period you want measured
    (see params_d3.warmup_days / cooldown_days).
    """
    # Fail fast in the parent. Overrides are NOT applied here: that used to leak scenario
    # parameters into the calling process (e.g. a dashboard session). Workers apply them per run.
    validate_overrides(parameter_overrides)

    if instrument_resources is None:
        raise ValueError("instrument_resources cannot be None. Pass Instrument_resources explicitly.")
    if shift_staffing_profile is None:
        raise ValueError("shift_staffing_profile cannot be None. Pass shift_staffing_profile explicitly.")

    task_args = [
        (
            i,
            seed_base,
            sim_days,
            instrument_resources,
            shift_staffing_profile,
            proposed_policy,
            initial_conditions_json,
            parameter_overrides,
        )
        for i in range(iterations)
    ]

    results = []
    completed_count = 0
    workers = max_workers or min(os.cpu_count() or 4, iterations)

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_run_single_iteration, arg) for arg in task_args]

        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            results.append(res)
            completed_count += 1

            if callable(set_progress):
                percent = int((completed_count / iterations) * 100)
                set_progress((percent, f"{percent}%", f"Completed {completed_count} of {iterations} runs..."))

    # Deterministic ordering even though workers finish asynchronously.
    results.sort(key=lambda x: x["iteration"])

    delays_per_run: List[int] = []
    total_stockout_incidents: int = 0
    media_consumption_history: Dict[str, List[int]] = {k: [] for k in proposed_policy.keys()}
    csv_records = []
    p50_tats = []
    p95_tats = []
    pooled_tat_values = []

    for res in results:
        delays = res["delays"]
        delays_per_run.append(delays)
        if delays > 0:
            total_stockout_incidents += 1

        record = {
            "run_id": res["iteration"],
            "seed": res["seed"],
            "param_BCx_positivity": res["param_BCx_positivity"],
            "param_rejection_percent": res["param_rejection_percent"],
            "total_specimens": res["total_specimens"],
            "plating_delays": res["plating_delays"],
            "total_delays": delays,
        }
        record.update(res.get("window_diag", {}))
        record.update(res["tat_metrics"])
        if "tat_overall_p50" in res["tat_metrics"]:
            p50_tats.append(float(res["tat_metrics"]["tat_overall_p50"]))
        if "tat_overall_p95" in res["tat_metrics"]:
            p95_tats.append(float(res["tat_metrics"]["tat_overall_p95"]))

        if res["tat_values"]:
            pooled_tat_values.extend(float(x) for x in res["tat_values"])

        record.update(res["tat_summary"])

        for item in proposed_policy.keys():
            consumed = res["media_usage"].get(item, 0)
            media_consumption_history[item].append(consumed)
            record[f"consumed_{item}"] = consumed
            record[f"cap_{item}"] = proposed_policy.get(item, 0)
            record[f"stockout_{item}"] = res["stockout_per_item"].get(item, 0)

        csv_records.append(record)

    df_export = pd.DataFrame(csv_records)

    if csv_output_path:
        output_dir = os.path.dirname(os.path.abspath(csv_output_path))
        os.makedirs(output_dir, exist_ok=True)
        df_export.to_csv(csv_output_path, index=False)
        print(f"Saved Monte Carlo run output to: {csv_output_path}")

    risk_rate = (total_stockout_incidents / iterations) * 100.0 if iterations > 0 else 0.0
    avg_delays = float(np.mean(delays_per_run)) if delays_per_run else 0.0

    s50 = _replication_stats(p50_tats)
    s95 = _replication_stats(p95_tats)
    replication_summary = summarize_run_table(df_export)

    summary_table = pd.DataFrame([
        {
            "iterations_executed": iterations,
            "risk_rate": risk_rate,
            "avg_delays": avg_delays,
            "mean_p50_tat": s50["mean"],
            "mean_p95_tat": s95["mean"],
            "ci95_p50_tat_low": s50["ci_lo"],
            "ci95_p50_tat_high": s50["ci_hi"],
            "ci95_p95_tat_low": s95["ci_lo"],
            "ci95_p95_tat_high": s95["ci_hi"],
            "pi95_p50_tat_low": s50["pi_lo"],
            "pi95_p50_tat_high": s50["pi_hi"],
            "pi95_p95_tat_low": s95["pi_lo"],
            "pi95_p95_tat_high": s95["pi_hi"],
        }
    ])

    metrics = {
        "risk_rate": risk_rate,
        "avg_delays": avg_delays,
        "iterations_executed": iterations,
        "mean_p50_tat": s50["mean"],
        "ci95_p50_tat": (s50["ci_lo"], s50["ci_hi"]),      # CI of the mean (t-based)
        "pi95_p50_tat": (s50["pi_lo"], s50["pi_hi"]),      # where a single simulated month falls
        "mean_p95_tat": s95["mean"],
        "ci95_p95_tat": (s95["ci_lo"], s95["ci_hi"]),
        "pi95_p95_tat": (s95["pi_lo"], s95["pi_hi"]),
    }

    return {
        "run_table": df_export,
        "summary_table": summary_table,
        "replication_summary": replication_summary,
        "metrics": metrics,
        "risk_rate": risk_rate,
        "avg_delays": avg_delays,
        "delays_per_run": delays_per_run,
        "media_consumption_history": media_consumption_history,
        "iterations_executed": iterations,
        "mean_p50_tat": s50["mean"],
        "ci95_p50_tat": metrics["ci95_p50_tat"],
        "pi95_p50_tat": metrics["pi95_p50_tat"],
        "mean_p95_tat": s95["mean"],
        "ci95_p95_tat": metrics["ci95_p95_tat"],
        "pi95_p95_tat": metrics["pi95_p95_tat"],
        "pooled_tat_values": np.asarray(pooled_tat_values, dtype=float),
        "export_dataframe": df_export,
    }
