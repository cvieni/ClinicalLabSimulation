import simpy
import random
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import os
import sys
import traceback
import warnings
from typing import Dict

# Centralized parameters file which has the adjustable variables
import params_config.params_d3 as p

# Dictionaries
from params_config.config_d2 import Instrument_resources
from params_config.media_config import MEDIA_CONFIG
from params_config.specimen_config_d2 import SPECIMEN_TYPES
from params_config.staffing_config import SHIFT_STAFFING_PROFILE

# -------------------------------
# ----- Module import -----------
from modules.inventory import MediaInventory, inventory_manager_process
from modules.tracker import SpecimenTracker
from modules.analytics import export_ai_training_dataset, extract_run_stochastic_metrics
from modules.shift_manager_d2 import shift_handoff_process, shift_manager_process, set_resource_capacity, get_current_shift_config
from modules.accession_d2 import plating_worker_process, accession_worker_process, save_accession_breakdown_png_plt
from modules.specimen_generator import specimen_generator
from modules.spec_proc_helpers import get_tech_bench, consume_media_inventory
from modules.DiagnosticTracker import SimulationDiagnosticTracker
from modules.sim_classes import BatchAccumulator, MonitoredRequest
from modules.state_monitor_process import state_monitor_process
from modules.prepopulate_initialConds import load_initial_conditions_from_json
from modules.param_overrides import scoped_overrides
from modules.run_metrics import build_results_frame

# Project configuration
from project_config import OUTPUT_PNG_DIR


def _initialize_environment(seed, sim_days):
    """Create the simulation environment and shared state objects used by all processing stages."""
    random.seed(seed)
    np.random.seed(seed)
    sim_minutes = sim_days * 24 * 60

    env = simpy.Environment()
    env.run_seed = seed          # read by specimen_process to build per-specimen random streams
    tracker = SpecimenTracker()
    inventory = MediaInventory(env, MEDIA_CONFIG)
    active_counter = {"count": 0}

    routine_plating_store = simpy.Store(env)
    priority_plating_store = simpy.Store(env)
    accession_incoming_store = simpy.Store(env)
    stores_to_track = {
        "accession_incoming_store": accession_incoming_store,
        "routine_plating_store": routine_plating_store,
        "priority_plating_store": priority_plating_store,
    }
    return env, tracker, inventory, active_counter, stores_to_track, sim_minutes


def _initialize_resources(env, instrument_resources, shift_staffing_profile):
    """Build the SimPy resources for accession, plating, incubation, and reflex testing stages."""
    initial_shift = shift_staffing_profile["Weekday"]["Shift_1_Day"]
    cap_incubators = instrument_resources["incubator"]
    bc_cap = instrument_resources["bc_instrument"]
    phoenix_cap = instrument_resources["phoenix_instrument"]
    maldi_cap = instrument_resources["maldi_instrument"]

    return {
        "plating_bench": simpy.PriorityResource(env, capacity=initial_shift["plating_capacity"]),
        "incubator": simpy.Resource(env, capacity=cap_incubators),
        "bc_instrument": simpy.Resource(env, capacity=bc_cap),
        "phoenix_instrument": simpy.PriorityResource(env, capacity=phoenix_cap),
        "phoenix_loader_lock": simpy.PriorityResource(env, capacity=1),
        "maldi_instrument": simpy.PriorityResource(env, capacity=maldi_cap),
        "tech_accession": simpy.PriorityResource(env, capacity=initial_shift["tech_accession"]),
        "tech_plating": simpy.PriorityResource(env, capacity=initial_shift["tech_plating"]),
        "tech_blood": simpy.PriorityResource(env, capacity=initial_shift["tech_blood"]),
        "tech_routine": simpy.PriorityResource(env, capacity=initial_shift["tech_routine"]),
        "tech_urine": simpy.PriorityResource(env, capacity=initial_shift["tech_urine"]),
        "tech_new": simpy.PriorityResource(env, capacity=initial_shift["tech_new"]),
    }


def _get_active_worker_pool(shift_staffing_profile):
    """Peak accession / plating staffing across EVERY day-type and shift.

    The old version used Weekday/Shift_1_Day only. If any other shift is staffed higher than
    that, the number of worker processes (not the shift-managed resource capacity) became the
    ceiling. Extra workers are harmless: they queue on the capacity-limited tech resources.
    """
    accession, plating = 1, 1
    for day_profile in shift_staffing_profile.values():
        if not isinstance(day_profile, dict):
            continue
        for shift_cfg in day_profile.values():
            if not isinstance(shift_cfg, dict):
                continue
            accession = max(accession, int(shift_cfg.get("tech_accession", 1)))
            plating = max(plating, int(shift_cfg.get("tech_plating", 1)))
    return {"tech_accession": accession, "tech_plating": plating}


def _spawn_background_workers(env, resources, accession_incoming_store, routine_plating_store, priority_plating_store, tracker, batch_size, max_wait, shift_staffing_profile):
    """Start background workers sized to peak staffing across all shifts."""
    active_pool = _get_active_worker_pool(shift_staffing_profile)
    max_accession_techs = active_pool["tech_accession"]
    max_plating_techs = active_pool["tech_plating"]

    for i in range(max_accession_techs):
        env.process(accession_worker_process(
            env,
            resources,
            accession_incoming_store,
            routine_plating_store,
            tracker,
            batch_size=batch_size,
            max_wait_time=max_wait,
            worker_id=i + 1,
        ))

    for j in range(max_plating_techs):
        env.process(plating_worker_process(
            env,
            resources,
            routine_plating_store,
            priority_plating_store,
            tracker,
            worker_id=j + 1,
        ))

    return max_accession_techs, max_plating_techs


def _run_simulation_steps(env, resources, sim_minutes, set_progress, num_steps=20):
    """Advance the SimPy environment in fixed increments and emit queue diagnostics for the UI/log output."""
    step_percent = 100 // num_steps
    for i in range(1, num_steps + 1):
        target_minute = (sim_minutes / num_steps) * i
        env.run(until=target_minute)

        if set_progress:
            pct = i * step_percent
            current_day = (env.now / (24 * 60)) + 1
            set_progress((
                pct,
                f"{pct}%",
                f"Simulating Day {current_day:.1f} of {sim_minutes / (24 * 60):.1f} days...",
            ))

            print("\n" + "=" * 60)
            print("--- QUEUE SURGE DIAGNOSTIC ---")
            print("=" * 60)
            for name, res in resources.items():
                if hasattr(res, 'queue'):
                    print(f"Resource: {name:<22} | In Use: {res.count}/{res.capacity} | Waiting in Queue: {len(res.queue)}")
            print("=" * 60 + "\n")

    if env.now < sim_minutes:
        env.run(until=sim_minutes)


# ==================================================================================
# == Run Simulation =============================================================
# ==================================================================================
def run_simulation(sim_days=None, seed=None,
                   instrument_resources=None, shift_staffing_profile=None,
                   initial_conditions_json=None,
                   parameter_overrides=None,
                   set_progress=None,
                   save_plots=True,
                   log_filename="sim_log_file.log",
                   export_diagnostics=None,
                   ):
    """Run one replication. parameter_overrides are applied for this run only and rolled back
    afterwards (see modules/param_overrides.py), so nothing leaks into the next run in a reused
    worker process."""
    if sim_days is None or seed is None:
        raise ValueError("run_simulation requires sim_days and seed")
    with scoped_overrides(parameter_overrides):
        return _run_simulation_impl(
            sim_days, seed, instrument_resources, shift_staffing_profile, initial_conditions_json,
            set_progress, save_plots, log_filename, export_diagnostics,
        )


def _run_simulation_impl(sim_days, seed, instrument_resources, shift_staffing_profile,
                         initial_conditions_json, set_progress, save_plots, log_filename,
                         export_diagnostics):
    if shift_staffing_profile is None:
        shift_staffing_profile = SHIFT_STAFFING_PROFILE
    if instrument_resources is None:
        instrument_resources = Instrument_resources
    if export_diagnostics is None:
        export_diagnostics = p.export_diagnostic_timeseries

    env, tracker, inventory, active_counter, stores_to_track, sim_minutes = _initialize_environment(seed, sim_days)
    routine_plating_store = stores_to_track["routine_plating_store"]
    priority_plating_store = stores_to_track["priority_plating_store"]
    accession_incoming_store = stores_to_track["accession_incoming_store"]

    # =========================================================
    # LOAD INITIAL CONDITIONS FROM JSON AT t=0
    # =========================================================
    initial_conditions_loaded = False
    if initial_conditions_json and os.path.exists(initial_conditions_json):
        load_initial_conditions_from_json(
            json_path=initial_conditions_json,
            env=env,
            tracker=tracker,
            active_counter=active_counter,
            stores=stores_to_track
        )
        initial_conditions_loaded = True
    elif initial_conditions_json:
        warnings.warn(f"Specified initial conditions file was not found: {initial_conditions_json}; "
                      f"starting empty and applying warmup_days={p.warmup_days}.")
    else:
        print("No initial conditions file provided. Starting simulation from a fresh state.")

    batch_size = p.batch_size
    max_wait = p.max_wait
    plating_batcher = BatchAccumulator(env, batch_size=batch_size, max_wait=max_wait)

    resources = _initialize_resources(env, instrument_resources, shift_staffing_profile)

    # =========================================================================
    # SPAWN FIXED BACKGROUND WORKERS
    # =========================================================================
    max_accession_techs, max_plating_techs = _spawn_background_workers(
        env,
        resources,
        accession_incoming_store,
        routine_plating_store,
        priority_plating_store,
        tracker,
        batch_size=batch_size,
        max_wait=max_wait,
        shift_staffing_profile=shift_staffing_profile,
    )

    # =========================================================================
    # DIAGNOSTIC TRACKER (optional: state_monitor_process already polls every 30 min)
    # =========================================================================
    diagnostic_tracker = None
    if export_diagnostics:
        diagnostic_tracker = SimulationDiagnosticTracker(
            env=env,
            resources=resources,
            stores=stores_to_track,
            check_interval=30.0,
        )

    # Start Processes
    env.process(inventory_manager_process(env, inventory, MEDIA_CONFIG))
    env.process(state_monitor_process(env, resources, tracker, active_counter, shift_staffing_profile, interval=30))
    env.process(shift_manager_process(env, resources, shift_staffing_profile))

    for spec_type in SPECIMEN_TYPES:
        env.process(specimen_generator(
            env, f"{spec_type[:3].upper()}-GEN",
            spec_type, resources, inventory, tracker,
            active_counter, plating_batcher,
            routine_plating_store, priority_plating_store, accession_incoming_store
        ))

    # =========================================================
    # EXECUTION LOOP
    # =========================================================
    original_stdout = sys.stdout
    log_filepath = str(log_filename)

    with open(log_filepath, "w", encoding="utf-8") as f:
        sys.stdout = f
        print(f"=== Simulation Log Started for {sim_days} Days ({sim_minutes} mins) ===")
        print(f"Seed: {seed} | Peak worker pool: accession={max_accession_techs}, plating={max_plating_techs}")
        print(f"TTP sources: {p.TTP_SOURCE}")

        try:
            _run_simulation_steps(env, resources, sim_minutes, set_progress, num_steps=20)
            print(f"=== Simulation Completed at Sim Time {env.now:.1f} min ===")
        finally:
            sys.stdout = original_stdout

    print(f"Simulation run complete. Debug log saved to: {os.path.abspath(log_filename)}")

    # =========================================================
    # EXPORT DIAGNOSTIC TIME-SERIES CSV (unique file per process AND seed)
    # =========================================================
    if diagnostic_tracker is not None:
        out_dir = Path("results_experiments")
        out_dir.mkdir(parents=True, exist_ok=True)
        diagnostic_tracker.export_csv(out_dir / f"diagnostics_timeseries_proc_{os.getpid()}_seed{seed}.csv")

    # =========================================================
    # POST-SIMULATION DATA PROCESSING
    # =========================================================
    logs = getattr(tracker, 'logs', [])
    state_logs = getattr(tracker, 'state_logs', [])
    media_usage = dict(getattr(tracker, 'media_usage', {}))

    df_raw = pd.DataFrame(logs)
    df_state = pd.DataFrame(state_logs)

    total_specimens = df_raw["Specimen_ID"].nunique() if not df_raw.empty and "Specimen_ID" in df_raw.columns else 0
    stochastic_stats = extract_run_stochastic_metrics(df_raw, total_specimens)

    if df_raw.empty:
        return pd.DataFrame(), df_state, media_usage, pd.DataFrame(), stochastic_stats

    # TAT = arrival -> "10. Completed", by exact stage name, restricted to the measurement window.
    df_pivot, window_diag = build_results_frame(df_raw, sim_minutes, initial_conditions_loaded)
    if isinstance(stochastic_stats, dict):
        stochastic_stats.update(window_diag)
        stochastic_stats["ttp_source"] = dict(p.TTP_SOURCE)
    if window_diag["n_incomplete_in_window"] > 0:
        warnings.warn(f"{window_diag['n_incomplete_in_window']} in-window specimens never completed "
                      f"(right-censored). Increase cooldown_days or sim_days.")

    try:
        df_ai_features = export_ai_training_dataset(df_raw, df_state, tracker)
    except Exception:
        # Do not swallow silently: a broken export used to look identical to "no features".
        traceback.print_exc()
        warnings.warn("export_ai_training_dataset failed (traceback above); returning empty AI features.")
        df_ai_features = pd.DataFrame()

    if save_plots:
        save_accession_breakdown_png_plt(
            tracker_or_df=tracker,
            output_folder=str(OUTPUT_PNG_DIR),
            filename="accession_throughput_breakdown.png"
        )

    return df_pivot, df_state, media_usage, df_ai_features, stochastic_stats
