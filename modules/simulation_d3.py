import simpy
import random
import numpy as np
import pandas as pd

# Centralized parameters file which has the adjustable variables
import params_config.params_d2 as p

# Dictionaries
from params_config.config_d2 import MEDIA_CONFIG, SPECIMEN_TYPES, SHIFT_STAFFING_PROFILE, Instrument_resources

# -------------------------------
# ----- Module import -----------
from modules.inventory import MediaInventory, inventory_manager_process
from modules.tracker import SpecimenTracker
from modules.analytics import export_ai_training_dataset
from modules.shift_manager import shift_handoff_process, shift_manager_process, set_resource_capacity, get_current_shift_config

# Main DES simulation process
from modules.specimen_process_d4 import specimen_process
from modules.spec_proc_helpers import get_tech_bench, consume_media_inventory


# -------------------------------
# ----- Buffer Incoming Requests -----------
# -------------------------------
class BatchAccumulator:
    """Buffers incoming requests until a batch size or timeout condition is met."""
    def __init__(self, env, batch_size=p.batch_size, max_wait=p.max_wait):
        self.env = env
        self.batch_size = batch_size
        self.max_wait = max_wait
        self.queue = []
        self.timer_proc = None

    def wait_for_batch(self):
        """Processes call this to pause until released in a batch."""
        event = self.env.event()
        self.queue.append(event)

        if len(self.queue) >= self.batch_size:
            self._flush_batch()
        elif self.timer_proc is None or not self.timer_proc.is_alive:
            self.timer_proc = self.env.process(self._batch_timer())

        return event

    def _batch_timer(self):
        try:
            yield self.env.timeout(self.max_wait)
            self._flush_batch()
        except simpy.Interrupt:
            pass # Batch filled before timeout
        
    def _flush_batch(self):
        # if self.timer_proc and self.timer_proc.is_alive:
        #     self.timer_proc.defused = True
        if self.timer_proc and self.timer_proc.is_alive:
            try:
                self.timer_proc.interrupt()
            except RuntimeError:
                pass # Already finished
            
        to_release = self.queue[:self.batch_size]
        self.queue = self.queue[self.batch_size:]
        
        for event in to_release:
            if not event.triggered:
                event.succeed()


# continous background observer that checks every 30 minutes to see how many specimens are:
# 1. in the lab (active_specs)
# 2. in the plating queue
# 3. tech queue
# then log_state takes a snapshot of these metrics to produce the time series plots
def state_monitor_process(env, resources, tracker, active_counter, shift_staffing_profile, interval=30):
    """
    Periodically records simulation state metrics (queues, active specimens, 
    busy techs, and scheduled staffing levels).
    """
    # Define active tech keys across all benches
    tech_keys = [
        "tech_accession",
        "tech_plating",
        "tech_blood",
        "tech_routine",
        "tech_urine",
        "tech_new",
    ]

    while True:
        yield env.timeout(interval)
        
        # Get active shift staffing target
        shift_cfg = get_current_shift_config(env.now, shift_staffing_profile)
        
        active_specs = active_counter['count']
        plating_q = len(resources["plating_bench"].queue) if "plating_bench" in resources else 0

        # 1. Sum queue lengths across all active tech benches
        tech_q = sum(
            len(resources[key].queue) 
            for key in tech_keys 
            if key in resources
        )
        
        # 2. Sum busy tech count (currently processing tasks)
        busy_techs = sum(
            resources[key].count 
            for key in tech_keys 
            if key in resources
        )
        
        # 3. Sum total scheduled/assigned techs from active shift profile
        total_assigned_techs = sum(
            shift_cfg.get(key, 0) 
            for key in tech_keys
        )

        # Build dictionary of individual technician queue lengths
        individual_tech_queues = {
            f"{key}_queue_length": len(resources[key].queue) if key in resources else 0
            for key in tech_keys
        }
        
        tracker.log_state(
            timestamp=env.now,
            active_specimens=active_specs,
            plating_queue=plating_q,
            tech_queue=tech_q,
            busy_techs=busy_techs,
            active_techs=total_assigned_techs, 
            **individual_tech_queues
        )



# ==================================================================================
# EVENT & TIMEOUT MONITORING HELPER
# ==================================================================================
class MonitoredRequest:
    """Wraps a SimPy resource request and logs warnings if waiting exceeds threshold."""
    def __init__(self, env, resource, resource_name, spec_id, timeout_warn=60):
        self.env = env
        self.resource = resource
        self.resource_name = resource_name
        self.spec_id = spec_id
        self.timeout_warn = timeout_warn
        self.req = None

    def __enter__(self):
        self.req = self.resource.request()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.req:
            self.resource.release(self.req)

    def wait(self):
        start_time = self.env.now
        # Wait for either resource acquisition OR warning timeout
        yield self.req
        wait_duration = self.env.now - start_time
        if wait_duration >= self.timeout_warn:
            print(f"⚠️ [DELAY WARNING] t={self.env.now:.1f}m | {self.spec_id} waited {wait_duration:.1f}m for {self.resource_name}!")

# ---------------------------------------------------------------------------
# Helper function to extract correct 24-hour weight vector regardless of configuration format
# ---------------------------------------------------------------------------
def get_current_hourly_weights(raw_weights, sim_minute):
    """
    Extracts a 24-element weight array from raw_weights based on current simulation time.
    Handles:
      - Dict format: {"weekday": [...], "weekend": [...]}
      - Flat 24-element list: [...]
      - Single-element nested list: [[...]]
    """
    if isinstance(raw_weights, dict):
        total_hours = int(sim_minute // 60)
        day_of_week = (total_hours // 24) % 7  # Days 0-4 = Weekday, Days 5-6 = Weekend
        key = "weekend" if day_of_week >= 5 else "weekday"
        return raw_weights[key]
    elif isinstance(raw_weights, list):
        if len(raw_weights) == 1 and isinstance(raw_weights[0], list):
            return raw_weights[0]
        return raw_weights
    else:
        return [1.0 / 24.0] * 24

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
def nhpp_next_arrival_delta(current_minute, raw_weights, daily_volume_mean):
    """
    Lewis-Shedler Thinning Algorithm for non-homogeneous Poisson processes (nhpp).
    Generates proper inter-arrival gaps in MINUTES.
    """
    hourly_weights = get_current_hourly_weights(raw_weights, current_minute)

    total_w = sum(hourly_weights) if sum(hourly_weights) > 0 else 1.0
    norm_weights = [w / total_w for w in hourly_weights]
    
    # Peak arrival rate in arrivals PER MINUTE
    peak_weight = max(norm_weights)
    max_rate = (daily_volume_mean * peak_weight) / 60.0  # arrivals/min
    
    if max_rate <= 0:
        return 60.0  # Safe default fallback
        
    t_elapsed = 0.0
    sim_time = current_minute
    
    while True:
        # 1. Sample candidate gap using peak rate
        dt = random.expovariate(max_rate)
        t_elapsed += dt
        sim_time += dt

        # 2. Re-evaluate weights if simulation crosses midnight or weekend threshold
        active_weights = get_current_hourly_weights(raw_weights, sim_time)
        active_total_w = sum(active_weights) if sum(active_weights) > 0 else 1.0
        active_norm = [w / active_total_w for w in active_weights]
        
        # 3. Determine current hour of day
        hour_of_day = int((sim_time % 1440) // 60)
        
        # 4. Calculate actual arrival rate for this hour
        actual_rate = (daily_volume_mean * active_norm[hour_of_day]) / 60.0
        
        # 4. Thinning acceptance test
        if random.random() <= (actual_rate / max_rate):
            return t_elapsed  # Return true accumulated time delta in minutes



# tmp
import matplotlib.pyplot as plt
import os

def save_accession_breakdown_png_plt(tracker_or_df, output_folder, filename):
    """
    Exports a PNG breakdown of accessioned specimens over time by specimen type.
    Dynamically extracts event records from various SpecimenTracker implementations.
    """
    df_events = None

    # 1. Direct DataFrame
    if isinstance(tracker_or_df, pd.DataFrame):
        df_events = tracker_or_df.copy()

    # 2. Objects with methods returning DataFrames or lists
    elif hasattr(tracker_or_df, "get_events_df"):
        df_events = tracker_or_df.get_events_df()
    elif hasattr(tracker_or_df, "get_log"):
        df_events = pd.DataFrame(tracker_or_df.get_log())

    # 3. Common attribute names for lists/dicts inside tracker classes
    elif hasattr(tracker_or_df, "events"):
        df_events = pd.DataFrame(tracker_or_df.events)
    elif hasattr(tracker_or_df, "event_log"):
        df_events = pd.DataFrame(tracker_or_df.event_log)
    elif hasattr(tracker_or_df, "logs"):
        df_events = pd.DataFrame(tracker_or_df.logs)
    elif hasattr(tracker_or_df, "records"):
        df_events = pd.DataFrame(tracker_or_df.records)

    # 4. Fallback: Search attributes of tracker_or_df for list of dicts
    else:
        for attr_name in dir(tracker_or_df):
            if not attr_name.startswith("__"):
                val = getattr(tracker_or_df, attr_name)
                if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                    print(f"[Diagnostic] Found event log in tracker attribute: '{attr_name}'")
                    df_events = pd.DataFrame(val)
                    break

    if df_events is None or df_events.empty:
        print(f"[Warning] Could not parse tracker object. Available attributes on tracker: {[a for a in dir(tracker_or_df) if not a.startswith('_')]}")
        return

    # Normalize column names for flexible matching
    col_map = {c.lower(): c for c in df_events.columns}
    
    # Updated column mapping logic to match your exact DataFrame schema
    event_col = col_map.get("stage", col_map.get("event_name", col_map.get("event")))
    time_col = col_map.get("minute", col_map.get("time", col_map.get("timestamp")))
    type_col = col_map.get("type", col_map.get("specimen_type", col_map.get("spec_type")))

    if not event_col or not time_col or not type_col:
        print(f"[Warning] Required columns missing from event log. Found: {list(df_events.columns)}")
        return

    # Filter for Accession events
    accession_df = df_events[df_events[event_col].astype(str).str.contains("Accession", case=False, na=False)].copy()

    if accession_df.empty:
        print("[Warning] No Accession events found in event log.")
        return

    accession_df["Day"] = pd.to_numeric(accession_df[time_col], errors="coerce") / 1440.0
    accession_df = accession_df.sort_values("Day")

    accession_df["Count"] = 1
    accession_df["Cumulative_Count"] = accession_df.groupby(type_col)["Count"].cumsum()

    # Define high-contrast distinct color map and line styles
    unique_types = sorted(accession_df[type_col].dropna().unique())
    
    # Custom distinct palette mapping
    color_palette = [
        "#E6194B", "#3CB44B", "#FFE119", "#4363D8", "#F58231", 
        "#911EB4", "#46F0F0", "#F032E6", "#BCF60C", "#FABEBE", 
        "#008080", "#E6BEFF", "#9A6324", "#FFFAC8", "#800000"
    ]
    line_styles = ["-", "--", "-."]

    plt.figure(figsize=(13, 7))

    for idx, spec_type in enumerate(unique_types):
        group = accession_df[accession_df[type_col] == spec_type]
        color = color_palette[idx % len(color_palette)]
        style = line_styles[(idx // len(color_palette)) % len(line_styles)]
        
        plt.plot(
            group["Day"], 
            group["Cumulative_Count"], 
            label=spec_type, 
            linewidth=2.2,
            color=color,
            linestyle=style
        )

    plt.title("Cumulative Specimens Accessioned Over Time by Specimen Type", fontsize=14, fontweight="bold")
    plt.xlabel("Simulation Time (Days)", fontsize=12)
    plt.ylabel("Specimens Accessioned", fontsize=12)
    plt.legend(title="Specimen Type", bbox_to_anchor=(1.02, 1), loc="upper left", frameon=True)
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.tight_layout()

    os.makedirs(output_folder, exist_ok=True)
    full_path = os.path.join(output_folder, filename)
    plt.savefig(full_path, dpi=300)
    plt.close()
    print(f"[Diagnostic] High-contrast chart saved successfully to: {full_path}")

# ---------------------------------------------------------------------------
# --- Generate the Specimens -----------------------------------------
# ---------------------------------------------------------------------------
def specimen_generator(env, full_id, spec_type, resources, inventory, tracker, active_counter, plating_batcher):
    spec_id = 0
    spec_cfg = SPECIMEN_TYPES[spec_type]
    raw_weights = spec_cfg["hourly_arrival_weights"]
    daily_vol = spec_cfg["daily_volume_mean"]

    while True:
        # Dynamically fetch current 24-hr weights based on simulation time (env.now)
        current_weights = get_current_hourly_weights(raw_weights, env.now)

        # Calculate proper arrival gap
        time_to_next = nhpp_next_arrival_delta(env.now, current_weights, daily_vol)
        
        # 1. Wait for next specimen
        yield env.timeout(time_to_next)
        
        # 2. Spawn specimen process
        spec_id += 1
        full_id = f"{spec_type[:3].upper()}-{spec_id:05d}"
        
        env.process(specimen_process(
            env, full_id, spec_type, resources, inventory, tracker, 
            active_counter, plating_batcher
        ))


# Place this function above run_simulation or near state_monitor_process
def deadlock_diagnostic_observer(env, resources, interval=60):
    """Prints resource queue bottlenecks to terminal to pinpoint hang-ups."""
    while True:
        yield env.timeout(interval)


# ==================================================================================
# == Run Simulation =============================================================
# ==================================================================================
def run_simulation(sim_days = None, seed = None, 
                   instrument_resources = None, shift_staffing_profile = None,
                   time_plating_mean = None, time_incubation_hours = None,
                   set_progress=None
                   ):
    # Strict assertions: Fail instantly with a clear message if None is passed
    assert time_plating_mean is not None, "time_plating_mean was passed as None to run_simulation!"
    assert time_incubation_hours is not None, "time_incubation_hours was passed as None to run_simulation!"

    random.seed(seed)
    np.random.seed(seed)
    sim_minutes = sim_days * 24 * 60

    env = simpy.Environment()

    tracker = SpecimenTracker()
    inventory = MediaInventory(env, MEDIA_CONFIG)
    active_counter = {'count': 0}

    # Safely get batcher settings or fall back
    # batch_size = getattr(p, 'batch_size', 10) if 'p' in globals() else 10
    # max_wait = getattr(p, 'max_wait', 15) if 'p' in globals() else 15
    batch_size = p.batch_size
    max_wait = p.max_wait
    plating_batcher = BatchAccumulator(env, batch_size=batch_size, max_wait=max_wait)

    # 1. Extract Capacities Directly from Dicts
    cap_incubators = instrument_resources["incubator"]
    bc_cap = instrument_resources["bc_instrument"]
    phoenix_cap = instrument_resources["phoenix_instrument"]
    maldi_cap = instrument_resources["maldi_instrument"]

    # Get initial staffing (Day 1, Shift 1) for initial Resource initialization
    initial_shift = shift_staffing_profile["Weekday"]["Shift_1_Day"]

    # 2. Initialize SimPy Resources using explicit values
    resources = {
        "plating_bench": simpy.PriorityResource(env, capacity=initial_shift["plating_capacity"]),
        "incubator": simpy.Resource(env, capacity=cap_incubators),
        "bc_instrument": simpy.Resource(env, capacity=bc_cap),
        # Phoenix AST Resources
        "phoenix_instrument": simpy.PriorityResource(env, capacity=phoenix_cap),
        "phoenix_loader_lock": simpy.PriorityResource(env, capacity=1),
        
        # MALDI-TOF ID Resource
        "maldi_instrument": simpy.PriorityResource(env, capacity=maldi_cap),

        # --- Split Techs by Bench ---
        "tech_accession": simpy.PriorityResource(env, capacity=initial_shift["tech_accession"]),
        "tech_plating": simpy.PriorityResource(env, capacity=initial_shift["tech_plating"]),
        "tech_blood": simpy.PriorityResource(env, capacity=initial_shift["tech_blood"]),
        "tech_routine": simpy.PriorityResource(env, capacity=initial_shift["tech_routine"]),
        "tech_urine": simpy.PriorityResource(env, capacity=initial_shift["tech_urine"]),
        "tech_new": simpy.PriorityResource(env, capacity=initial_shift["tech_new"])
    }


    # 3. Start Processes
    env.process(inventory_manager_process(env, inventory, MEDIA_CONFIG))
    env.process(state_monitor_process(env, resources, tracker, active_counter, shift_staffing_profile, interval=30))
    env.process(shift_manager_process(env, resources, shift_staffing_profile))
    
    # ADD THIS LINE TO START DEADLOCK DIAGNOSTICS:
    env.process(deadlock_diagnostic_observer(env, resources, interval=60))

    for spec_type in SPECIMEN_TYPES:
        env.process(specimen_generator(
            env, f"{spec_type[:3].upper()}-GEN",
            spec_type, resources, inventory, tracker, 
            active_counter, plating_batcher
        ))

    # =========================================================
    # DYNAMIC PROGRESS BAR EXECUTION LOOP
    # =========================================================
    # Advance in 5% increments to update the progress bar without UI overhead
    step_percent = 5
    num_steps = 100 // step_percent

    for i in range(1, num_steps + 1):
        target_minute = (sim_minutes / num_steps) * i
        env.run(until=target_minute)

        if set_progress:
            pct = i * step_percent
            current_day = (env.now / (24 * 60)) + 1
            set_progress((
                pct,
                f"{pct}%",
                f"Simulating Day {current_day:.1f} of {sim_days} days..."
            ))

            # ==========================================
            # QUEUE SURGE DIAGNOSTIC
            # ==========================================
            print("\n" + "="*60)
            print("--- QUEUE SURGE DIAGNOSTIC ---")
            print("="*60)
            for name, res in resources.items():
                if hasattr(res, 'queue'):
                    print(f"Resource: {name:<22} | In Use: {res.count}/{res.capacity} | Waiting in Queue: {len(res.queue)}")
            print("="*60 + "\n")


    # Guarantee execution up to the exact final minute
    if env.now < sim_minutes:
        env.run(until=sim_minutes)
    
    # =========================================================
    # POST-SIMULATION DATA PROCESSING
    # =========================================================

    logs = getattr(tracker, 'logs', [])
    state_logs = getattr(tracker, 'state_logs', [])
    media_usage = dict(getattr(tracker, 'media_usage', {}))

    df_raw = pd.DataFrame(logs)
    df_state = pd.DataFrame(state_logs)

    if df_raw.empty:
        return pd.DataFrame(), df_state, media_usage, pd.DataFrame()

    # df_pivot = df_raw.pivot(index=["Specimen_ID", "Type"], columns="Stage", values="Minute").reset_index()
    # Replace df_raw.pivot with pivot_table to safely handle multiple log entries per stage
    df_pivot = df_raw.pivot_table(
        index=["Specimen_ID", "Type"], 
        columns="Stage", 
        values="Minute", 
        aggfunc="first"
    ).reset_index()

    def find_col(possible_names):
        for name in possible_names:
            if name in df_pivot.columns:
                return name
        return None

    col_arrived = find_col(["1. Arrived", "Arrived", "Arrival", "Specimen Arrived"])
    col_plating = find_col(["3A. Plate Culture from BCx or Body Fluid Bottle", "3B-1. Plating from PrimarySpecimen Started"])
    col_inc_start = find_col(["3a-3. Incubate plate from BCx or BF Bottle", "3B-2. Incubation from Primary Specimen Started"])
    col_inc_end = find_col(["4. Tech Review Started (Plate - Day 2)"])
    col_completed = find_col(["10. Completed", "Completed", "Complete"])

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
    save_accession_breakdown_png_plt(
        tracker_or_df=tracker,
        output_folder="output_pngs",
        filename="accession_throughput_breakdown.png"
    )

    return df_pivot, df_state, media_usage, df_ai_features