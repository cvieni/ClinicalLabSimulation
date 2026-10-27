# modules/monte_carlo.py

import os
import tempfile
import concurrent.futures
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd

# Import different modules
from Sim_d6.deprecated.simulation_d3 import run_simulation

# Import parameter configuration
import params_config.params_d3 as p
from params_config.config_d2 import Instrument_resources


def _apply_parameter_overrides(parameter_overrides: Optional[Dict[str, Any]] = None) -> None:
    """Apply runtime overrides before each DES run so tuning values reach spawned worker processes."""
    if not parameter_overrides:
        return

    from params_config.specimen_config_d2 import apply_specimen_shift_tuning

    for name, value in parameter_overrides.items():
        # Normalize hyphens to underscores
        attr_name = name.replace("-", "_")

        # Case 1: Structured route override dictionary payload
        if attr_name.startswith("specimen_override_") and isinstance(value, dict):
            stype = value.get("specimen_type")
            shift = value.get("shift_label", "Day")
            ckey = value.get("config_key")
            val = value.get("value")

            # Set dynamic attribute directly on module p for worker processes
            setattr(p, attr_name, val)

            # Route setting into SPECIMEN_TYPES tuning matrix
            if stype and ckey:
                apply_specimen_shift_tuning(stype, shift, ckey, val)

        # Case 2: Standard parameter on p OR standard spec-override key name
        elif hasattr(p, attr_name) or attr_name.startswith("specimen_override_"):
            setattr(p, attr_name, value)

        # Case 3: Unknown parameter fallback exception
        else:
            raise ValueError(f"Unknown tuning override '{name}' for params_config.params_d2")

# ==================================================================================
# == Single Worker Iteration =======================================================
# ==================================================================================
def _run_single_iteration(args: tuple) -> Dict[str, Any]:
    """
    Top-level helper function for multiprocessing. 
    Executes a single DES iteration and returns metric results.
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

    _apply_parameter_overrides(parameter_overrides)

    iteration_seed = seed_base + i
    # worker_log_path = os.path.join(tempfile.gettempdir(), f"labsim_mc_{iteration_seed}.log")
    # 1. Define the relative 'temp' directory path
    TEMP_DIR = os.path.join(os.getcwd(), "temp")
    # 2. Ensure the directory exists (creates it if missing)
    os.makedirs(TEMP_DIR, exist_ok=True)
    # 3. Create your log file path inside the local 'temp' folder
    worker_log_path = os.path.join(TEMP_DIR, f"labsim_mc_{iteration_seed}.log")

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
        (df_pivot["Wait_For_Plating_Mins"] > 120).sum()
        if "Wait_For_Plating_Mins" in df_pivot.columns
        else 0
    )

    # ----- Initialize TAT summary and metrics ------------
    # Extract average TAT per specimen type for this run
    tat_summary = {}
    tat_metrics = {}
    tat_values = []

    # ---- Calculate TAT metrics ------------
    if df_pivot is not None and not df_pivot.empty and "Total_TAT_Hours" in df_pivot.columns:
        # 1. Coerce Total_TAT_Hours to numeric float to prevent invalid object types
        df_pivot["Total_TAT_Hours"] = pd.to_numeric(df_pivot["Total_TAT_Hours"], errors="coerce")
        valid_df = df_pivot.dropna(subset=["Total_TAT_Hours"])
        valid_tat = valid_df["Total_TAT_Hours"]
        tat_values = valid_tat.tolist()

        # valid_tat = df_pivot["Total_TAT_Hours"].dropna()
        # tat_values = valid_tat.astype(float).tolist()

        if not valid_tat.empty:
            tat_metrics["tat_overall_mean"] = round(float(valid_tat.mean()), 2)
            tat_metrics["tat_overall_p50"] = round(float(np.percentile(valid_tat, 50)), 2)
            tat_metrics["tat_overall_p95"] = round(float(np.percentile(valid_tat, 95)), 2)

        # 2. Safely resolve specimen category column
        candidate_cols = ["Type", "Specimen_Type", "specimen_type", "type"]
        type_col = next((col for col in candidate_cols if col in df_pivot.columns), None)
        # type_col = "Type" if "Type" in df_pivot.columns else df_pivot.columns[0]

        if type_col:
            # Calculate mean TAT grouped by specimen type on valid numeric rows
            avg_tats = valid_df.groupby(type_col)["Total_TAT_Hours"].mean()

            for spec_type, avg_tat in avg_tats.items():
                if pd.notna(avg_tat):
                    # Sanitize column name (e.g., 'Blood Culture' -> 'tat_Blood_Culture')
                    clean_key = f"tat_{str(spec_type).strip().replace(' ', '_')}"
                    tat_summary[clean_key] = round(float(avg_tat), 2)

        # Calculate mean TAT grouped by specimen type
        # avg_tats = df_pivot.groupby(type_col)["Total_TAT_Hours"].mean()

        # for spec_type, avg_tat in avg_tats.items():
        #     # Sanitize column name (e.g., 'Blood Culture' -> 'tat_Blood_Culture')
        #     clean_key = f"tat_{str(spec_type).replace(' ', '_')}"
        #     tat_summary[clean_key] = round(avg_tat, 2)

    # Return unified dictionary matching the main function consumer
    return {
        "iteration": i,
        "seed": iteration_seed,
        # Captured stochastic parameters for this run:
        "param_BCx_positivity": stochastic_stats.get("param_BCx_positivity", 0.0),
        "param_rejection_percent": stochastic_stats.get("param_rejection_percent", 0.0),
        # Metrics and usage data:
        "delays": run_delays,
        "plating_delays": plating_delays,
        "total_specimens": total_specimens,
        "media_usage": media_usage,
        "stockout_per_item": stockout_per_item,
        "tat_summary": tat_summary,
        "tat_values": tat_values,
        "tat_metrics": tat_metrics,
    }

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
    """
    Executes a Monte Carlo stress test across multiple stochastic simulation runs.
    """

    _apply_parameter_overrides(parameter_overrides)

    # Validation
    if instrument_resources is None:
        raise ValueError("instrument_resources cannot be None. Pass Instrument_resources explicitly.")
    if shift_staffing_profile is None:
        raise ValueError("shift_staffing_profile cannot be None. Pass shift_staffing_profile explicitly.")

    # Step 1: build one independent task per Monte Carlo replication. Each task gets a
    # unique seed so the stochastic lab behavior can vary between runs while keeping the
    # simulation setup identical across iterations.
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

    # Step 2: run the DES workload in parallel across worker processes. Each worker returns
    # the run-level metrics for a single replication, which are later aggregated into the
    # Monte Carlo summary statistics and exported CSV.
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        # Line that actually runs the script --------------
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        futures = [executor.submit(_run_single_iteration, arg) for arg in task_args]
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        # Line that actually runs the script --------------
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            results.append(res)
            completed_count += 1

            if callable(set_progress):
                percent = int((completed_count / iterations) * 100)
                set_progress((percent, f"{percent}%", f"Completed {completed_count} of {iterations} runs..."))

    # Step 3: reorder the completed jobs by run number so the Monte Carlo output remains
    # deterministic even though the worker processes finish asynchronously.
    results.sort(key=lambda x: x["iteration"])

    delays_per_run: List[int] = []
    total_stockout_incidents: int = 0
    media_consumption_history: Dict[str, List[int]] = {k: [] for k in proposed_policy.keys()}
    csv_records = []
    p50_tats = []
    p95_tats = []
    pooled_tat_values = []

    # Step 4: aggregate the per-iteration outputs into a single Monte Carlo summary. This
    # is the point where the model turns many independent stochastic runs into the mean,
    # confidence interval, and distribution summaries used for validation.
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
            "total_delays": delays
        }
        if "tat_metrics" in res:
            record.update(res["tat_metrics"])
            if "tat_overall_p50" in res["tat_metrics"]:
                p50_tats.append(float(res["tat_metrics"]["tat_overall_p50"]))
            if "tat_overall_p95" in res["tat_metrics"]:
                p95_tats.append(float(res["tat_metrics"]["tat_overall_p95"]))

        if "tat_values" in res and res["tat_values"]:
            pooled_tat_values.extend(float(x) for x in res["tat_values"])

        # Dynamic expansion of specimen TAT columns (e.g. tat_Blood, tat_Urine)
        if "tat_summary" in res and res["tat_summary"]:
            record.update(res["tat_summary"])

        # Media consumption breakdowns
        for item in proposed_policy.keys():
            consumed = res["media_usage"].get(item, 0)
            media_consumption_history[item].append(consumed)
            record[f"consumed_{item}"] = consumed
            record[f"cap_{item}"] = proposed_policy.get(item, 0)
            record[f"stockout_{item}"] = res["stockout_per_item"].get(item, 0)

        csv_records.append(record)

    df_export = pd.DataFrame(csv_records)
    
    # Step 5: export the detailed per-run record so analysts can inspect the underlying
    # stochastic runs and follow a single iteration back to its seed, metrics, and delays.
    if csv_output_path:
        output_dir = os.path.dirname(os.path.abspath(csv_output_path))
        os.makedirs(output_dir, exist_ok=True)
        df_export.to_csv(csv_output_path, index=False)
        print(f"Saved Monte Carlo run output to: {csv_output_path}")

    risk_rate = (total_stockout_incidents / iterations) * 100.0 if iterations > 0 else 0.0
    avg_delays = float(np.mean(delays_per_run)) if delays_per_run else 0.0

    # Step 6: summarize the replications into mean and 95% uncertainty bands. These values
    # are the ones compared directly against the observed monthly LIS summaries.
    mean_p50 = float(np.mean(p50_tats)) if p50_tats else 0.0
    std_p50 = float(np.std(p50_tats, ddof=1)) if len(p50_tats) > 1 else 0.0
    ci95_margin_p50 = 1.96 * (std_p50 / np.sqrt(iterations)) if iterations > 0 else 0.0

    mean_p95 = float(np.mean(p95_tats)) if p95_tats else 0.0
    std_p95 = float(np.std(p95_tats, ddof=1)) if len(p95_tats) > 1 else 0.0
    ci95_margin = 1.96 * (std_p95 / np.sqrt(iterations)) if iterations > 0 else 0.0

    # Canonical Monte Carlo output contract used by both the CLI validation layer and the
    # dashboard app. We retain the legacy keys for backward compatibility while adding a
    # clearer summary table and standardized metrics container.
    summary_table = pd.DataFrame([
        {
            "iterations_executed": iterations,
            "risk_rate": risk_rate,
            "avg_delays": avg_delays,
            "mean_p50_tat": mean_p50,
            "mean_p95_tat": mean_p95,
            "ci95_p50_tat_low": mean_p50 - ci95_margin_p50,
            "ci95_p50_tat_high": mean_p50 + ci95_margin_p50,
            "ci95_p95_tat_low": mean_p95 - ci95_margin,
            "ci95_p95_tat_high": mean_p95 + ci95_margin,
        }
    ])

    metrics = {
        "risk_rate": risk_rate,
        "avg_delays": avg_delays,
        "iterations_executed": iterations,
        "mean_p50_tat": mean_p50,
        "ci95_p50_tat": (mean_p50 - ci95_margin_p50, mean_p50 + ci95_margin_p50),
        "mean_p95_tat": mean_p95,
        "ci95_p95_tat": (mean_p95 - ci95_margin, mean_p95 + ci95_margin),
    }

    return {
        "run_table": df_export,
        "summary_table": summary_table,
        "metrics": metrics,
        "risk_rate": risk_rate,
        "avg_delays": avg_delays,
        "delays_per_run": delays_per_run,
        "media_consumption_history": media_consumption_history,
        "iterations_executed": iterations,
        "mean_p50_tat": mean_p50,
        "ci95_p50_tat": (mean_p50 - ci95_margin_p50, mean_p50 + ci95_margin_p50),
        "mean_p95_tat": mean_p95,
        "ci95_p95_tat": (mean_p95 - ci95_margin, mean_p95 + ci95_margin),
        "pooled_tat_values": np.asarray(pooled_tat_values, dtype=float),
        "export_dataframe": df_export,
    }