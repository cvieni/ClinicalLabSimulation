import simpy
import random
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import os
from typing import Dict
import sys

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
# Main DES simulation process
# from modules.specimen_process_d5 import specimen_process
from modules.spec_proc_helpers import get_tech_bench, consume_media_inventory
from modules.DiagnosticTracker import SimulationDiagnosticTracker
from modules.sim_classes import BatchAccumulator, MonitoredRequest
from modules.state_monitor_process import state_monitor_process
from modules.prepopulate_initialConds import load_initial_conditions_from_json

# Project configuration
from project_config import OUTPUT_PNG_DIR


# Place this function above run_simulation or near state_monitor_process
def deadlock_diagnostic_observer(env, resources, interval=60):
    """Prints resource queue bottlenecks to terminal to pinpoint hang-ups."""
    while True:
        yield env.timeout(interval)


def _initialize_environment(seed, sim_days):
    """Create the simulation environment and shared state objects used by all processing stages."""
    random.seed(seed)
    np.random.seed(seed)
    sim_minutes = sim_days * 24 * 60

    env = simpy.Environment()
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
    """Return the staffing pool for the first modeled active shift.

    We intentionally use the active shift composition rather than the maximum staffing
    seen across all shifts. This keeps the queue diagnostics tied to the operating profile
    being simulated and avoids over-interpreting queue growth as a separate system bug.
    """
    weekday_profile = shift_staffing_profile.get("Weekday", {})
    active_shift = weekday_profile.get("Shift_1_Day") or next(iter(weekday_profile.values()), {})
    return {
        "tech_accession": int(active_shift.get("tech_accession", 1)),
        "tech_plating": int(active_shift.get("tech_plating", 1)),
    }


def _spawn_background_workers(env, resources, accession_incoming_store, routine_plating_store, priority_plating_store, tracker, batch_size, max_wait, shift_staffing_profile):
    """Start background workers for the modeled active shift staffing profile."""
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
def _apply_runtime_parameter_overrides(parameter_overrides=None):
    """Apply any override dict before starting the DES so tuning values are honored even under multiprocessing."""
    if not parameter_overrides:
        return
    for name, value in parameter_overrides.items():
        if not hasattr(p, name):
            raise ValueError(f"Unknown runtime override '{name}' in params_config.params_d2")
        setattr(p, name, value)


def run_simulation(sim_days = None, seed = None, 
                   instrument_resources = None, shift_staffing_profile = None,
                #    time_plating_mean = None, time_incubation_hours = None,
                   initial_conditions_json=None,
                   parameter_overrides=None,
                   set_progress=None,
                   save_plots=True,
                   log_filename = "sim_log_file.log"
                   ):
    # Strict assertions: Fail instantly with a clear message if None is passed
    # assert time_plating_mean is not None, "time_plating_mean was passed as None to run_simulation!"
    # assert time_incubation_hours is not None, "time_incubation_hours was passed as None to run_simulation!"

    # # Fallback to config if shift_staffing_profile is None
    _apply_runtime_parameter_overrides(parameter_overrides)

    if shift_staffing_profile is None:
        shift_staffing_profile = SHIFT_STAFFING_PROFILE
    # Fallback for instrument_resources as well if omitted
    if instrument_resources is None:
        instrument_resources = Instrument_resources

    env, tracker, inventory, active_counter, stores_to_track, sim_minutes = _initialize_environment(seed, sim_days)
    routine_plating_store = stores_to_track["routine_plating_store"]
    priority_plating_store = stores_to_track["priority_plating_store"]
    accession_incoming_store = stores_to_track["accession_incoming_store"]

    # =========================================================
    # LOAD INITIAL CONDITIONS FROM JSON AT t=0
    # =========================================================
    if initial_conditions_json and os.path.exists(initial_conditions_json):
        load_initial_conditions_from_json(
            json_path=initial_conditions_json,
            env=env,
            tracker=tracker,
            active_counter=active_counter,
            stores=stores_to_track
        )
    elif initial_conditions_json:
        print(f"Warning: Specified initial conditions file was not found: {initial_conditions_json}")
    else:
        print("No initial conditions file provided. Starting simulation from a fresh state.")

    # Safely get batcher settings or fall back
    # batch_size = getattr(p, 'batch_size', 10) if 'p' in globals() else 10
    # max_wait = getattr(p, 'max_wait', 15) if 'p' in globals() else 15
    batch_size = p.batch_size
    max_wait = p.max_wait
    plating_batcher = BatchAccumulator(env, batch_size=batch_size, max_wait=max_wait)

    # 1. Extract Capacities Directly from Dicts
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

    # # Spawn background consumer workers matching peak day plating tech capacity
    # NUM_PLATING_WORKERS = initial_shift["tech_plating"]
    # for _ in range(NUM_PLATING_WORKERS):
    #     env.process(plating_worker_process(env, resources, routine_plating_store, priority_plating_store, tracker))

    # # Spawn accession batch workers based on total tech capacity
    # accession_capacity = initial_shift.get("tech_accession")
    # for _ in range(accession_capacity):
    #     env.process(accession_worker_process(
    #         env=env,
    #         resources=resources,
    #         accession_incoming_store=accession_incoming_store,
    #         routine_plating_store=routine_plating_store,
    #         tracker=tracker,
    #         batch_size=10,       # Adjust tray/rack batch size as needed
    #         max_wait_time=5.0    # Tech won't wait more than 5 mins to start a partial tray
    #     ))


    # =========================================================================
    # ADD DIAGNOSTIC TRACKER
    # =========================================================================
    diagnostic_tracker = SimulationDiagnosticTracker(
        env=env,
        resources=resources,
        stores=stores_to_track,
        check_interval=30.0  # Logs to stdout every 15 sim minutes
    )

    # 3. Start Processes
    env.process(inventory_manager_process(env, inventory, MEDIA_CONFIG))
    env.process(state_monitor_process(env, resources, tracker, active_counter, shift_staffing_profile, interval=30))
    env.process(shift_manager_process(env, resources, shift_staffing_profile))
    env.process(deadlock_diagnostic_observer(env, resources, interval=60))


    for spec_type in SPECIMEN_TYPES:
        env.process(specimen_generator(
            env, f"{spec_type[:3].upper()}-GEN",
            spec_type, resources, inventory, tracker, 
            active_counter, plating_batcher, 
            routine_plating_store, priority_plating_store, accession_incoming_store
        ))

    # =========================================================
    # DYNAMIC PROGRESS BAR EXECUTION LOOP
    # =========================================================
    # This stage keeps the long-running simulation readable: the actual time-stepping
    # is factored into a helper so the main function focuses on configuration and wiring.
    original_stdout = sys.stdout
    log_filepath = str(log_filename)

    with open(log_filepath, "w", encoding="utf-8") as f:
        sys.stdout = f
        print(f"=== Simulation Log Started for {sim_days} Days ({sim_minutes} mins) ===")
        print(f"Seed: {seed} | Active-shift worker pool: accession={max_accession_techs}, plating={max_plating_techs}")
        print("Note: queue diagnostics below reflect the modeled active shift capacity and batching behavior, not a separate Python-thread lock.")

        try:
            _run_simulation_steps(env, resources, sim_minutes, set_progress, num_steps=20)
            print(f"=== Simulation Completed at Sim Time {env.now:.1f} min ===")
        finally:
            # Always restore original stdout even if an exception occurs
            sys.stdout = original_stdout

    print(f"Simulation run complete. Debug log saved to: {os.path.abspath(log_filename)}")

    # =========================================================
    # EXPORT DIAGNOSTIC TIME-SERIES CSV FOR PLOTTING
    # =========================================================
    pid = os.getpid()
    timeseries_path = Path("results_experiments") / f"diagnostics_timeseries_proc_{pid}.csv"
    diagnostic_tracker.export_csv(timeseries_path)

    # =========================================================
    # POST-SIMULATION DATA PROCESSING
    # =========================================================

    logs = getattr(tracker, 'logs', [])
    state_logs = getattr(tracker, 'state_logs', [])
    media_usage = dict(getattr(tracker, 'media_usage', {}))

    df_raw = pd.DataFrame(logs)
    df_state = pd.DataFrame(state_logs)

    # Calculate stochastic metrics for single run output
    total_specimens = df_raw["Specimen_ID"].nunique() if not df_raw.empty and "Specimen_ID" in df_raw.columns else 0
    stochastic_stats = extract_run_stochastic_metrics(df_raw, total_specimens)

    if df_raw.empty:
        return pd.DataFrame(), df_state, media_usage, pd.DataFrame(), stochastic_stats

    # df_pivot = df_raw.pivot(index=["Specimen_ID", "Type"], columns="Stage", values="Minute").reset_index()
    # Replace df_raw.pivot with pivot_table to safely handle multiple log entries per stage
    df_pivot = df_raw.pivot_table(
        index=["Specimen_ID", "Type"], 
        columns="Stage", 
        values="Minute", 
        aggfunc="first"
    ).reset_index()

    # Flexible string matching
    def find_col_contains(keywords):
        for col in df_pivot.columns:
            for kw in keywords:
                if kw.lower() in str(col).lower():
                    return col
        return None

    col_arrived = find_col_contains(["arrived", "arrival", "1."])
    col_plating = find_col_contains(["plating", "3a.", "3b", "2C", "3A", "3B-1", "Plating from PrimarySpecimen"])
    col_inc_start = find_col_contains(["incubat", "3a-3", "Incubation from Primary Specimen Started"])
    col_inc_end = find_col_contains(["review", "4."])
    col_addtl_test = find_col_contains(["6d. MALDI ID Completed", "7c. Phoenix AST Completed"])
    col_addtl_test = find_col_contains(["6d. MALDI ID Completed", "7c. Phoenix AST Completed"])
    col_completed = find_col_contains(["complete", "result", "autoverif", "10."])

    # col_arrived = find_col(["1. Arrived", "1. Arrived (Initial State)"])
    # col_plating = find_col(["2C. Routine Plating Started", "3A. Priority Blood Plating Started", 
    #                         "3B-1. Sample loaded for Automated Plating Started", "3B-2. Plating from PrimarySpecimen Started"])
    # col_inc_start = find_col(["3B-2. Incubation from Primary Specimen Started", "3a-3. Incubate plate from BCx or BF Bottle"])
    # col_inc_end = find_col(["4. Tech Review Started (Plate - Day 2)"])
    # col_completed = find_col(["10. Completed", "6d. MALDI ID Completed", "7c. Phoenix AST Completed"])


    if col_completed and col_arrived:
        df_pivot["Total_TAT_Hours"] = (df_pivot[col_completed] - df_pivot[col_arrived]) / 60.0
    else:
        df_pivot["Total_TAT_Hours"] = np.nan

    if col_plating and col_arrived:
        df_pivot["Wait_For_Plating_Mins"] = df_pivot[col_plating] - df_pivot[col_arrived]
    else:
        df_pivot["Wait_For_Plating_Mins"] = np.nan

    if col_inc_end and col_inc_start:
        df_pivot["Incubation_Hours"] = (df_pivot[col_inc_end] - df_pivot[col_inc_start]) / 60.0

    try:
        df_ai_features = export_ai_training_dataset(df_raw, df_state, tracker)
    except Exception:
        df_ai_features = pd.DataFrame()

    # Export Diagnostic PNG ONCE after simulation run finishes
    if save_plots:
        save_accession_breakdown_png_plt(
            tracker_or_df=tracker,
            output_folder=str(OUTPUT_PNG_DIR),
            filename="accession_throughput_breakdown.png"
        )

    return df_pivot, df_state, media_usage, df_ai_features, stochastic_stats