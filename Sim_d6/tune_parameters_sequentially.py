"""Run a one-parameter-at-a-time sensitivity sweep against the 2024 LIS validation data.

Set a single parameter to a grid of candidate values, compare each candidate against the
observed monthly TAT benchmarks, and save a timestamped result file for tracking.

Examples:
    python tune_parameters_sequentially.py --param positive_specimen_rate --values 0.05 0.08 0.12 0.16 --iterations 1 --sim-days 7 --run-tag positivity
    python tune_parameters_sequentially.py --param avg_incubation_time_Other --values 12 18 24 30 --iterations 3 --sim-days 14 --run-tag incubation
    python tune_parameters_sequentially.py --param workup_required_rate --values 0.15 0.25 0.35 0.45 --iterations 2 --sim-days 10 --run-tag repeat_workup
    python tune_parameters_sequentially.py --param polymicrobial_workup_required_rate --values 0.15 0.25 0.35 0.45 --iterations 2 --sim-days 10 --run-tag repeat_workup

    # Phase 1
    python tune_parameters_sequentially.py --preset focused_tail_targets --iterations 3 --sim-days 10 --run-tag focused_routes

    # Phase 2:
    python tune_parameters_sequentially.py --preset joint_calibration --iterations 3 --sim-days 14 --run-tag joint_sweep    
    
    # Run downstream workup parameter interaction scan
    python tune_parameters_sequentially.py --preset downstream_workup_sweep --iterations 3 --sim-days 14 --run-tag workup_sweep



"""


from __future__ import annotations

import argparse
from datetime import datetime
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

import params_config.params_d3 as p
from OpSim_Media_d6_CLI_only import build_baseline_policy, load_monthly_observed_data, run_monthly_validation
from modules.MonteCarlo.MCvalidation import validate_tat_distributions
from params_config.specimen_config_d2 import SPECIMEN_TYPES, apply_specimen_shift_tuning, clear_specimen_shift_tuning


# -----------------------------------------------------------------------------
# Core tuning outputs
# -----------------------------------------------------------------------------
# All scans write here so the workflow remains auditable and comparable across runs.
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results_experiments" / "parameter_tuning"
DEFAULT_MANIFEST_PATH = DEFAULT_RESULTS_DIR / "manifest.csv"

# -----------------------------------------------------------------------------
# Focused specimen x shift tuning matrix
# -----------------------------------------------------------------------------
# This is the route-specific calibration set for the longest-tailed and most sensitive
# operational strata identified in the LIS validation workflow.
# The idea is to keep staffing fixed and vary only the timing overrides for the
# bottleneck specimen routes at the relevant time-of-day.
FOCUSED_TUNING_MATRIX = {
    "Tissue": {
        "Evening": {
            "avg_incubation_time_Other": [14.0, 16.0, 18.0, 20.0, 22.0],
            "pre_accession_hold_multiplier": [1.1, 1.25, 1.35, 1.5],
        },
        "Night": {
            "avg_incubation_time_Other": [12.0, 14.0, 16.0, 18.0],
            "pre_accession_hold_multiplier": [1.0, 1.15, 1.3, 1.45],
        },
    },
    "Bone_Cx": {
        "Evening": {
            "avg_incubation_time_Other": [16.0, 18.0, 20.0, 22.0],
            "pre_accession_hold_multiplier": [1.2, 1.35, 1.45, 1.6],
        },
        "Day": {
            "avg_incubation_time_Other": [14.0, 16.0, 18.0, 20.0],
            "pre_accession_hold_multiplier": [1.0, 1.15, 1.25, 1.4],
        },
    },
    "BodyFluid": {
        "Evening": {
            "avg_incubation_time_Other": [14.0, 16.0, 18.0, 20.0],
            "pre_accession_hold_multiplier": [1.1, 1.3, 1.5, 1.7],
        },
    },
    "Wound": {
        "Evening": {
            "avg_incubation_time_Other": [14.0, 16.0, 18.0, 20.0],
            "pre_accession_hold_multiplier": [1.1, 1.25, 1.35, 1.5],
        },
    },
}

# -----------------------------------------------------------------------------
# Global parameter sweep presets
# -----------------------------------------------------------------------------
# These are broader, model-level sweeps. They are useful before route-specific tuning,
# but they will not isolate specimen-type behavior the way the focused matrix does.
DEFAULT_PARAMETER_SEQUENCE = {
    "repeat_workup": [
        ("multiple_organism_rate", [0.10, 0.18, 0.22, 0.30]),
        ("workup_required_rate", [0.15, 0.25, 0.35, 0.45]),
        ("monomicrobial_additional_workup_rate", [0.05, 0.10, 0.20, 0.30]),
        ("polymicrobial_workup_required_rate", [0.20, 0.35, 0.45, 0.60]),
        ("polymicrobial_all_organisms_worked_rate", [0.40, 0.60, 0.70, 0.85]),
    ],
    "incubation": [
        ("avg_incubation_time_Other", [12.0, 18.0, 24.0, 30.0]),
        ("incubation_1_time_avg", [12.0, 18.0, 24.0, 30.0]),
        ("incubation_2_time_avg", [12.0, 18.0, 24.0, 30.0]),
    ],
    "other": [
        ("positive_specimen_rate", [0.04, 0.08, 0.12, 0.16]),
        ("reincubation_percent", [0.03, 0.08, 0.12, 0.18]),
        ("additional_workup_percent", [0.01, 0.02, 0.05, 0.10]),
    ],
    "joint_calibration": [
        ("avg_incubation_time_Other", [12.0, 18.0, 24.0]),
        ("polymicrobial_workup_required_rate", [0.20, 0.35, 0.45]),
        ("positive_specimen_rate", [0.08, 0.12, 0.16]),
        ("polymicrobial_all_organisms_worked_rate", [0.60, 0.70, 0.85]),
    ],
    "tail_focused": [
        ("positive_specimen_rate", [0.10, 0.12, 0.14, 0.16]),
        ("avg_incubation_time_Other", [10.0, 12.0, 14.0, 16.0]),
        ("polymicrobial_workup_required_rate", [0.25, 0.35, 0.45]),
        ("polymicrobial_all_organisms_worked_rate", [0.60, 0.70, 0.85]),
    ],
    "full": [
        ("multiple_organism_rate", [0.10, 0.18, 0.22, 0.30]),
        ("workup_required_rate", [0.15, 0.25, 0.35, 0.45]),
        ("monomicrobial_additional_workup_rate", [0.05, 0.10, 0.20, 0.30]),
        ("polymicrobial_workup_required_rate", [0.20, 0.35, 0.45, 0.60]),
        ("polymicrobial_all_organisms_worked_rate", [0.40, 0.60, 0.70, 0.85]),
        ("avg_incubation_time_Other", [12.0, 18.0, 24.0, 30.0]),
        ("incubation_1_time_avg", [12.0, 18.0, 24.0, 30.0]),
        ("incubation_2_time_avg", [12.0, 18.0, 24.0, 30.0]),
        ("positive_specimen_rate", [0.04, 0.08, 0.12, 0.16]),
        ("reincubation_percent", [0.03, 0.08, 0.12, 0.18]),
        ("additional_workup_percent", [0.01, 0.02, 0.05, 0.10]),
    ],
    "downstream_workup_sweep": [
    ("maldi_testing_percent", [0.50, 0.65, 0.80]),
    ("colony_workup_time_factor", [1.25, 1.50, 1.75]),
    ("second_colony_percent", [0.20, 0.30, 0.40]),
    # ("touch_time_max", [4.0, 6.0, 8.0]),
    ]
}


def _coerce_value(raw: str):
    """Parse CLI values into int/float if possible; keep strings otherwise."""
    try:
        if any(ch in raw.lower() for ch in [".", "e"]):
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


# -----------------------------------------------------------------------------
# Helper functions for route-specific tuning
# -----------------------------------------------------------------------------
# These functions apply and remove specimen/shift overrides without altering the
# broader staffing configuration. They make the targeted scan explicit rather than
# silently relying on a default or a global parameter change.
def _apply_specimen_shift_override(specimen_type: str | None, shift_label: str | None, tuning_key: str | None, value):
    """Apply a specimen-specific, time-of-day tuning override before a scan run."""
    if specimen_type is None or tuning_key is None:
        return
    if shift_label is None:
        shift_label = "Day"
    apply_specimen_shift_tuning(specimen_type, shift_label, tuning_key, value)


def _restore_specimen_shift_override(specimen_type: str | None, shift_label: str | None, tuning_key: str | None, previous_value):
    """Revert a specimen-specific, time-of-day override after a scan run."""
    if specimen_type is None or tuning_key is None:
        return
    if shift_label is None:
        shift_label = "Day"
    if previous_value is None:
        clear_specimen_shift_tuning(specimen_type, shift_label, tuning_key)
    else:
        apply_specimen_shift_tuning(specimen_type, shift_label, tuning_key, previous_value)


def _backup_parameter_state(param_names: list[str]) -> dict[str, object]:
    return {name: getattr(p, name) for name in param_names}


def _restore_parameter_state(state: dict[str, object]) -> None:
    for name, value in state.items():
        setattr(p, name, value)


def _default_scan_path(param_name: str, results_dir: str | Path = DEFAULT_RESULTS_DIR, run_tag: str | None = None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{run_tag}" if run_tag else ""
    return Path(results_dir) / f"{param_name}{suffix}_{stamp}.csv"


def _write_manifest_row(results_path: Path, param_name: str, values: list[float | int], scan_df: pd.DataFrame, manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    if scan_df.empty:
        best_value = None
        best_overall_map_pct = None
    else:
        best_mask = scan_df["best_value"] if "best_value" in scan_df.columns else pd.Series([True] * len(scan_df), index=scan_df.index)
        best_row = scan_df.loc[best_mask].iloc[0]
        best_value = best_row.get("value", best_row.get("combo_label", best_row.get("parameter_values", None)))
        best_overall_map_pct = best_row.get("overall_map_pct", None)

    run_row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "parameter": param_name,
        "values_tested": str(values),
        "results_csv": str(results_path),
        "best_value": None if best_value is None else best_value,
        "best_overall_map_pct": None if best_overall_map_pct is None else float(best_overall_map_pct),
    }

    if manifest_path.exists():
        manifest = pd.read_csv(manifest_path)
        manifest = pd.concat([manifest, pd.DataFrame([run_row])], ignore_index=True)
    else:
        manifest = pd.DataFrame([run_row])
    manifest.to_csv(manifest_path, index=False)


def run_single_parameter_scan(
    param_name: str,
    values: list[float | int],
    data_path: str | Path | None = None,
    iterations: int = 3,
    sim_days: int = 14,
    seed_base: int = 42,
    initial_conditions_path: str | Path | None = None,
    output_csv: str | Path | None = None,
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
    run_tag: str | None = None,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    specimen_type: str | None = None,
    shift_label: str | None = None,
    config_key: str | None = None,
) -> pd.DataFrame:
    """Evaluate one parameter at multiple values and return the comparison summary.

    If specimen_type + config_key are supplied, the parameter is tuned as a specimen- and
    shift-specific override instead of a global module parameter. This keeps staffing fixed
    while allowing targeted calibration for a particular specimen route and time of day.
    """

    is_route_tuning = specimen_type is not None and config_key is not None

    if is_route_tuning:
        if specimen_type not in SPECIMEN_TYPES:
            raise ValueError(f"Specimen type '{specimen_type}' is not defined in SPECIMEN_TYPES.")
        if shift_label is None:
            shift_label = "Day"
        param_name = param_name or f"{specimen_type}_{shift_label}_{config_key}"
    else:
        if param_name is None:
            raise ValueError("Either 'param_name' or 'specimen_type' + 'config_key' must be provided.")
        if not hasattr(p, param_name):
            raise ValueError(f"Parameter '{param_name}' does not exist in params_config.params_d2")

    monthly_obs = load_monthly_observed_data(data_path)
    baseline_policy = build_baseline_policy()
    original_state = _backup_parameter_state([param_name]) if hasattr(p, param_name) else {}

    if output_csv is None:
        output_csv = _default_scan_path(param_name, results_dir=results_dir, run_tag=run_tag)

    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(manifest_path)

    row_list: list[dict[str, object]] = []
    try:
        # Step 1: apply the route-specific override for the chosen specimen + shift.
        # Step 2: run the validation model once for each candidate value.
        # Step 3: summarize the model error versus observed LIS data.
        # Step 4: remove the override so subsequent values are evaluated independently.
        for value in values:
            if is_route_tuning:
                previous_value = SPECIMEN_TYPES[specimen_type].get("tuning_overrides", {}).get(shift_label, {}).get(config_key)
                _apply_specimen_shift_override(specimen_type, shift_label, config_key, value)
                active_override = SPECIMEN_TYPES[specimen_type].get("tuning_overrides", {}).get(shift_label, {}).get(config_key)
                if active_override != value:
                    raise RuntimeError(
                        f"Route override failed to apply: {specimen_type} / {shift_label} / {config_key} -> "
                        f"expected {value}, active {active_override}"
                    )
                print(f"DEBUG OVERRIDE ACTIVE: {specimen_type} / {shift_label} / {config_key} = {active_override}")
                
                # Pass structured route override down to multi-process workers
                route_override_key = f"specimen_override_{specimen_type}_{shift_label}_{config_key}"
                overrides_payload = {
                    route_override_key: {
                        "specimen_type": specimen_type,
                        "shift_label": shift_label,
                        "config_key": config_key,
                        "value": value,
                    }
                }
            else:
                setattr(p, param_name, value)
                overrides_payload = {param_name: value}

            validation = run_monthly_validation(
                monthly_obs=monthly_obs,
                iterations=iterations,
                sim_days=sim_days,
                seed_base=seed_base,
                proposed_policy=baseline_policy,
                output_path=None,
                initial_conditions_json=initial_conditions_path,
                parameter_overrides=overrides_payload,
            )
            summary = validation["validation_summary"]
            if is_route_tuning:
                print(f"VERIFYING SPECIMEN TUNING: {specimen_type} / {shift_label} / {config_key} = {value}")
            else:
                print(f"VERIFYING STATE: {param_name} is set to {getattr(p, param_name)}")


            if summary.empty:
                row_list.append(
                    {
                        "parameter": param_name,
                        "value": value,
                        "mean_p50_error_pct": np.nan,
                        "mean_p95_error_pct": np.nan,
                        "overall_map_pct": np.nan,
                        "ks_stat": np.nan,
                        "p_value": np.nan,
                        "best_value": False,
                        "specimen_type": specimen_type,
                        "shift_label": shift_label,
                        "config_key": config_key,
                    }
                )

                if is_route_tuning:
                    _restore_specimen_shift_override(specimen_type, shift_label, config_key, previous_value)
                continue

            summary["pct_err_p50"] = np.abs((summary["simulated_p50"] - summary["observed_p50"]) / summary["observed_p50"]) * 100.0
            summary["pct_err_p95"] = np.abs((summary["simulated_p95"] - summary["observed_p95"]) / summary["observed_p95"]) * 100.0
            pooled_validation = validate_tat_distributions(
                simulated_tats=np.asarray(validation["pooled_sim_tats"], dtype=float),
                observed_tats=np.asarray(validation["pooled_obs_tats"], dtype=float),
            )

            mean_p50_err = float(summary["pct_err_p50"].mean())
            mean_p95_err = float(summary["pct_err_p95"].mean())
            overall_map = float((mean_p50_err + mean_p95_err) / 2.0)

            row_list.append(
                {
                    "parameter": param_name,
                    "value": value,
                    "mean_p50_error_pct": mean_p50_err,
                    "mean_p95_error_pct": mean_p95_err,
                    "overall_map_pct": overall_map,
                    "ks_stat": float(pooled_validation.get("ks_stat", np.nan)),
                    "p_value": float(pooled_validation.get("p_value", np.nan)),
                    "best_value": False,
                    "specimen_type": specimen_type,
                    "shift_label": shift_label,
                    "config_key": config_key,
                }
            )

            if specimen_type is not None and config_key is not None:
                _restore_specimen_shift_override(specimen_type, shift_label, config_key, previous_value)

        if row_list:
            df = pd.DataFrame(row_list)
            best_idx = df["overall_map_pct"].idxmin(skipna=True)
            if isinstance(best_idx, int) and not pd.isna(best_idx):
                df.loc[best_idx, "best_value"] = True
            df = df.sort_values("overall_map_pct", kind="mergesort").reset_index(drop=True)
            df.to_csv(output_csv, index=False)
            _write_manifest_row(output_csv, param_name, values, df, manifest_path)
            return df

        empty_df = pd.DataFrame(columns=["parameter", "value", "mean_p50_error_pct", "mean_p95_error_pct", "overall_map_pct", "ks_stat", "p_value", "best_value", "specimen_type", "shift_label", "config_key"])
        empty_df.to_csv(output_csv, index=False)
        _write_manifest_row(output_csv, param_name, values, empty_df, manifest_path)
        return empty_df
    finally:
        if specimen_type is None or config_key is None:
            _restore_parameter_state(original_state)


def _parse_param_grid(raw_grid: str) -> dict[str, list[float | int]]:
    """Parse a semicolon-delimited grid like 'param1:0.1,0.2;param2:12,18'."""
    grid: dict[str, list[float | int]] = {}
    for block in raw_grid.split(";"):
        if not block.strip():
            continue
        name, _, values_text = block.partition(":")
        if not name.strip() or not values_text.strip():
            raise ValueError(f"Invalid parameter grid entry '{block}'. Expected 'param:value1,value2'.")
        values = [_coerce_value(v.strip()) for v in values_text.split(",") if v.strip()]
        if not values:
            raise ValueError(f"No candidate values found in grid entry '{block}'.")
        grid[name.strip()] = values
    return grid


# -----------------------------------------------------------------------------
# Multi-parameter sweeps
# -----------------------------------------------------------------------------
# This block evaluates every combination of a small number of global parameters.
# It is useful when a handful of parameters are thought to interact.
def run_multi_parameter_grid(
    param_grid: dict[str, list[float | int]],
    data_path: str | Path | None = None,
    iterations: int = 1,
    sim_days: int = 7,
    seed_base: int = 42,
    initial_conditions_path: str | Path | None = None,
    output_csv: str | Path | None = None,
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
    run_tag: str | None = None,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> pd.DataFrame:
    """Evaluate every combination in a multi-parameter grid and return a ranked table."""
    param_names = list(param_grid.keys())
    if not param_names:
        raise ValueError("param_grid must contain at least one parameter name")

    monthly_obs = load_monthly_observed_data(data_path)
    baseline_policy = build_baseline_policy()
    output_path = Path(output_csv) if output_csv is not None else _default_scan_path("multi_grid", results_dir=results_dir, run_tag=run_tag)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(manifest_path)
    rows: list[dict[str, object]] = []

    for combo in product(*[param_grid[name] for name in param_names]):
        overrides = {name: value for name, value in zip(param_names, combo)}
        validation = run_monthly_validation(
            monthly_obs=monthly_obs,
            iterations=iterations,
            sim_days=sim_days,
            seed_base=seed_base,
            proposed_policy=baseline_policy,
            output_path=None,
            initial_conditions_json=initial_conditions_path,
            parameter_overrides=overrides,
        )
        summary = validation["validation_summary"]
        if summary.empty:
            continue

        summary["pct_err_p50"] = np.abs((summary["simulated_p50"] - summary["observed_p50"]) / summary["observed_p50"]) * 100.0
        summary["pct_err_p95"] = np.abs((summary["simulated_p95"] - summary["observed_p95"]) / summary["observed_p95"]) * 100.0
        pooled_validation = validate_tat_distributions(
            simulated_tats=np.asarray(validation["pooled_sim_tats"], dtype=float),
            observed_tats=np.asarray(validation["pooled_obs_tats"], dtype=float),
        )

        mean_p50_err = float(summary["pct_err_p50"].mean())
        mean_p95_err = float(summary["pct_err_p95"].mean())
        overall_map = float((mean_p50_err + mean_p95_err) / 2.0)

        val_map = ", ".join(f"{name}={value}" for name, value in overrides.items())
        rows.append({
            "combo_label": val_map,
            "parameter_values": str(overrides),
            **overrides,
            "mean_p50_error_pct": mean_p50_err,
            "mean_p95_error_pct": mean_p95_err,
            "overall_map_pct": overall_map,
            "ks_stat": float(pooled_validation.get("ks_stat", np.nan)),
            "p_value": float(pooled_validation.get("p_value", np.nan)),
            "best_value": False,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["combo_label", "parameter_values", "mean_p50_error_pct", "mean_p95_error_pct", "overall_map_pct", "ks_stat", "p_value", "best_value"])
    else:
        best_idx = df["overall_map_pct"].idxmin(skipna=True)
        if isinstance(best_idx, int) and not pd.isna(best_idx):
            df.loc[best_idx, "best_value"] = True
        df = df.sort_values("overall_map_pct", kind="mergesort").reset_index(drop=True)

    df.to_csv(output_path, index=False)
    _write_manifest_row(output_path, "multi_grid", list(param_grid.values())[0] if len(param_grid) == 1 else list(param_grid.keys()), df, manifest_path)
    return df


# -----------------------------------------------------------------------------
# Focused route-specific tuning matrix
# -----------------------------------------------------------------------------
# This is the primary workflow for the long-tail bottleneck analysis. It varies only
# the selected specimen + shift override while holding staffing and the rest of the
# lab policy fixed.
def run_focused_specimen_shift_matrix(
    matrix: dict[str, dict[str, dict[str, list[float | int]]]] | None = None,
    data_path: str | Path | None = None,
    iterations: int = 1,
    sim_days: int = 7,
    seed_base: int = 42,
    initial_conditions_path: str | Path | None = None,
    output_csv: str | Path | None = None,
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
    run_tag: str | None = None,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> pd.DataFrame:
    """Evaluate the explicit specimen-type + shift bottleneck matrix.

    This is the recommended scan for the highest-impact operational strata identified from
    the LIS validation analysis.
    """
    if matrix is None:
        matrix = FOCUSED_TUNING_MATRIX

    monthly_obs = load_monthly_observed_data(data_path)
    baseline_policy = build_baseline_policy()
    output_path = Path(output_csv) if output_csv is not None else _default_scan_path("focused_tail_matrix", results_dir=results_dir, run_tag=run_tag)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(manifest_path)
    rows: list[dict[str, object]] = []

    for specimen_type, shift_map in matrix.items():
        for shift_label, tuning_map in shift_map.items():
            for config_key, values in tuning_map.items():
                for value in values:
                    spec_cfg = SPECIMEN_TYPES[specimen_type]
                    previous_value = None
                    tuning_overrides = spec_cfg.setdefault("tuning_overrides", {})
                    shift_cfg = tuning_overrides.setdefault(shift_label, {})
                    if config_key in shift_cfg:
                        previous_value = shift_cfg[config_key]
                    shift_cfg[config_key] = value

                    # Construct structured override payload for worker processes across multiprocessing boundaries
                    route_override_key = f"specimen_override_{specimen_type}_{shift_label}_{config_key}"
                    overrides_payload = {
                        route_override_key: {
                            "specimen_type": specimen_type,
                            "shift_label": shift_label,
                            "config_key": config_key,
                            "value": value,
                        }
                    }

                    try:
                        validation = run_monthly_validation(
                            monthly_obs=monthly_obs,
                            iterations=iterations,
                            sim_days=sim_days,
                            seed_base=seed_base,
                            proposed_policy=baseline_policy,
                            output_path=None,
                            initial_conditions_json=initial_conditions_path,
                            parameter_overrides=overrides_payload, 
                        )

                        summary = validation["validation_summary"]
                        if summary.empty:
                            continue

                        summary["pct_err_p50"] = np.abs((summary["simulated_p50"] - summary["observed_p50"]) / summary["observed_p50"]) * 100.0
                        summary["pct_err_p95"] = np.abs((summary["simulated_p95"] - summary["observed_p95"]) / summary["observed_p95"]) * 100.0
                        pooled_validation = validate_tat_distributions(
                            simulated_tats=np.asarray(validation["pooled_sim_tats"], dtype=float),
                            observed_tats=np.asarray(validation["pooled_obs_tats"], dtype=float),
                        )

                        mean_p50_err = float(summary["pct_err_p50"].mean())
                        mean_p95_err = float(summary["pct_err_p95"].mean())
                        overall_map = float((mean_p50_err + mean_p95_err) / 2.0)

                        rows.append({
                            "specimen_type": specimen_type,
                            "shift_label": shift_label,
                            "config_key": config_key,
                            "value": value,
                            "mean_p50_error_pct": mean_p50_err,
                            "mean_p95_error_pct": mean_p95_err,
                            "overall_map_pct": overall_map,
                            "ks_stat": float(pooled_validation.get("ks_stat", np.nan)),
                            "p_value": float(pooled_validation.get("p_value", np.nan)),
                            "best_value": False,
                        })
                    finally:
                        if previous_value is None:
                            shift_cfg.pop(config_key, None)
                            if not shift_cfg:
                                tuning_overrides.pop(shift_label, None)
                        else:
                            shift_cfg[config_key] = previous_value

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["specimen_type", "shift_label", "config_key", "value", "mean_p50_error_pct", "mean_p95_error_pct", "overall_map_pct", "ks_stat", "p_value", "best_value"])
    else:
        best_idx = df["overall_map_pct"].idxmin(skipna=True)
        if isinstance(best_idx, int) and not pd.isna(best_idx):
            df.loc[best_idx, "best_value"] = True
        df = df.sort_values("overall_map_pct", kind="mergesort").reset_index(drop=True)

    df.to_csv(output_path, index=False)
    _write_manifest_row(output_path, "focused_specimen_shift_matrix", [str(matrix)], df, manifest_path)
    return df


# -----------------------------------------------------------------------------
# Sequence runner
# -----------------------------------------------------------------------------
# This chooses which preset sweep to run. The focused Tail matrix is the route-specific
# model calibration workflow for the specimen/shift combinations identified as driving
# the longest TAT tails.
def run_parameter_sequence(
    sequence_name: str = "full",
    data_path: str | Path | None = None,
    iterations: int = 1,
    sim_days: int = 7,
    seed_base: int = 42,
    initial_conditions_path: str | Path | None = None,
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
    run_tag: str | None = None,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> pd.DataFrame:
    """Run a predefined parameter sweep sequence. This is the recommended local tuning workflow."""
    if sequence_name == "focused_tail_targets":
        return run_focused_specimen_shift_matrix(
            matrix=FOCUSED_TUNING_MATRIX,
            data_path=data_path,
            iterations=iterations,
            sim_days=sim_days,
            seed_base=seed_base,
            initial_conditions_path=initial_conditions_path,
            results_dir=results_dir,
            run_tag=run_tag,
            manifest_path=manifest_path,
        )

    if sequence_name not in DEFAULT_PARAMETER_SEQUENCE:
        raise ValueError(f"Unknown parameter sequence '{sequence_name}'. Choices: {sorted(DEFAULT_PARAMETER_SEQUENCE)}")


    # if sequence_name in {"joint_calibration", "tail_focused"}:
    if sequence_name in {"joint_calibration", "tail_focused", "downstream_workup_sweep"}:
    # if sequence_name in {"downstream_workup_sweep"}:
        grid = dict(DEFAULT_PARAMETER_SEQUENCE[sequence_name])
        output_path = _default_scan_path(sequence_name, results_dir=results_dir, run_tag=f"{run_tag}_{sequence_name}" if run_tag else sequence_name)
        return run_multi_parameter_grid(
            param_grid=grid,
            data_path=data_path,
            iterations=iterations,
            sim_days=sim_days,
            seed_base=seed_base,
            initial_conditions_path=initial_conditions_path,
            output_csv=output_path,
            results_dir=results_dir,
            run_tag=f"{run_tag}_{sequence_name}" if run_tag else sequence_name,
            manifest_path=manifest_path,
        )

    all_rows: list[pd.DataFrame] = []
    for param_name, values in DEFAULT_PARAMETER_SEQUENCE[sequence_name]:
        output_path = _default_scan_path(param_name, results_dir=results_dir, run_tag=f"{run_tag}_{sequence_name}" if run_tag else sequence_name)
        df = run_single_parameter_scan(
            param_name=param_name,
            values=values,
            data_path=data_path,
            iterations=iterations,
            sim_days=sim_days,
            seed_base=seed_base,
            initial_conditions_path=initial_conditions_path,
            output_csv=output_path,
            results_dir=results_dir,
            run_tag=f"{run_tag}_{sequence_name}" if run_tag else sequence_name,
            manifest_path=manifest_path,
        )
        all_rows.append(df)

        if not df.empty:
            best = df.loc[df["best_value"]].iloc[0]
            print(f"\n[{sequence_name}] {param_name}: best value={best['value']} | overall_map_pct={best['overall_map_pct']:.2f}%")
        else:
            print(f"\n[{sequence_name}] {param_name}: no valid scan results")

    combined = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    return combined


# -----------------------------------------------------------------------------
# CLI entry point
# -----------------------------------------------------------------------------
# - single parameter = classic 1D sweep
# - grid = joint search over a few variables
# - preset = predefined scan workflow for local tuning
# The focused route-specific preset is the default for the LIS calibration work.
def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a single-parameter or predefined sequence of Monte Carlo sensitivity sweeps against the observed LIS data. "
            "This is designed for local tuning over several hours."
        )
    )
    parser.add_argument("--param", type=str, default=None, help="Single parameter name from params_config.params_d2. If omitted, a predefined sequence is used.")
    parser.add_argument("--values", type=str, nargs="+", default=None, help="Parameter values to test, e.g. --values 0.08 0.12 0.16")
    parser.add_argument("--grid", type=str, default=None, help="Multi-parameter grid as 'param1:0.08,0.12;param2:12,18', for a full cartesian scan of Combined values.")
    # parser.add_argument("--preset", type=str, default="tail_focused", choices=sorted(DEFAULT_PARAMETER_SEQUENCE) + ["focused_tail_targets"], help="Predefined tuning set to run sequentially")
    parser.add_argument("--preset", type=str, default="downstream_workup_sweep", help="Predefined tuning set to run sequentially")
    parser.add_argument("--data-path", type=str, default=None, help="CSV containing observed monthly or daily TAT data")
    parser.add_argument("--iterations", type=int, default=1, help="Monte Carlo replications per candidate value")
    parser.add_argument("--sim-days", type=int, default=7, help="Length of each simulation in days")
    parser.add_argument("--seed-base", type=int, default=42, help="Base random seed for the sweep")
    parser.add_argument("--initial-conditions-path", type=str, default=None, help="Optional initial conditions JSON")
    parser.add_argument("--results-dir", type=str, default=str(DEFAULT_RESULTS_DIR), help="Directory where tracked tuning CSVs will be written")
    parser.add_argument("--run-tag", type=str, default="local_tuning", help="Optional label added to the output filename for easier tracking")
    parser.add_argument("--manifest-path", type=str, default=str(DEFAULT_MANIFEST_PATH), help="CSV manifest tracking the tuning runs")
    parser.add_argument("--specimen-type", type=str, default=None, help="Optional specimen type key to tune specifically, for example Tissue or Bone")
    parser.add_argument("--shift", type=str, default=None, choices=["Day", "Evening", "Night"], help="Optional shift label for a specimen-specific tuning scan")
    parser.add_argument("--config-key", type=str, default=None, help="Specimen override key to adjust (for example avg_incubation_time_Other, tech_review_range, pre_accession_hold_multiplier)")
    args = parser.parse_args()

    if args.grid is not None:
        grid = _parse_param_grid(args.grid)
        output_path = _default_scan_path("multi_grid", results_dir=args.results_dir, run_tag=args.run_tag)
        scan_df = run_multi_parameter_grid(
            param_grid=grid,
            data_path=args.data_path,
            iterations=args.iterations,
            sim_days=args.sim_days,
            seed_base=args.seed_base,
            initial_conditions_path=args.initial_conditions_path,
            output_csv=output_path,
            results_dir=args.results_dir,
            run_tag=args.run_tag,
            manifest_path=args.manifest_path,
        )
        print(f"\nMulti-parameter grid scan:")
        print(scan_df.to_string(index=False))
        if not scan_df.empty:
            best = scan_df.loc[scan_df["best_value"]].iloc[0]
            print(f"\nBest combined candidate: {best['parameter_values']} | overall_map_pct={best['overall_map_pct']:.2f}%")
        print(f"\nSaved tuning table to: {output_path}")
        print(f"Manifest: {args.manifest_path}")
        return

    if args.param is not None:
        if args.values is None:
            parser.error("--values is required when using --param")
        values = [_coerce_value(v) for v in args.values]
        output_path = _default_scan_path(args.param, results_dir=args.results_dir, run_tag=args.run_tag)
        scan_df = run_single_parameter_scan(
            param_name=args.param,
            values=values,
            data_path=args.data_path,
            iterations=args.iterations,
            sim_days=args.sim_days,
            seed_base=args.seed_base,
            initial_conditions_path=args.initial_conditions_path,
            output_csv=output_path,
            results_dir=args.results_dir,
            run_tag=args.run_tag,
            manifest_path=args.manifest_path,
            specimen_type=args.specimen_type,
            shift_label=args.shift,
            config_key=args.config_key,
        )
        print(f"\nSequential tuning scan for parameter: {args.param}")
        print(scan_df.to_string(index=False))
        if not scan_df.empty:
            best = scan_df.loc[scan_df["best_value"]].iloc[0]
            print(f"\nBest candidate: value={best['value']} with overall_map_pct={best['overall_map_pct']:.2f}%")
        print(f"\nSaved tuning table to: {output_path}")
        print(f"Manifest: {args.manifest_path}")
        return

    print(f"\nRunning preset parameter sequence: {args.preset}")
    sequence_df = run_parameter_sequence(
        sequence_name=args.preset,
        data_path=args.data_path,
        iterations=args.iterations,
        sim_days=args.sim_days,
        seed_base=args.seed_base,
        initial_conditions_path=args.initial_conditions_path,
        results_dir=args.results_dir,
        run_tag=args.run_tag,
        manifest_path=args.manifest_path,
    )

    if not sequence_df.empty:
        print(f"\nPreset tuning summary for {args.preset}:")
        print(sequence_df.to_string(index=False))
        best_overall = sequence_df.loc[sequence_df["best_value"]].sort_values("overall_map_pct").iloc[0]

        if "parameter" in best_overall.index and "value" in best_overall.index:
            print(f"\nOverall best scanned value: {best_overall['parameter']} = {best_overall['value']} | overall_map_pct={best_overall['overall_map_pct']:.2f}%")
        elif "combo_label" in best_overall.index:
            print(f"\nOverall best combined candidate: {best_overall['combo_label']} | overall_map_pct={best_overall['overall_map_pct']:.2f}%")
        else:
            print(f"\nOverall best scanned result: {best_overall.to_dict()} | overall_map_pct={best_overall['overall_map_pct']:.2f}%")
    else:
        print("No results in the preset sequence.")

    print(f"\nManifest: {args.manifest_path}")


if __name__ == "__main__":
    main()
