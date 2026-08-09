import simpy
import random
import numpy as np
import pandas as pd

# Centralized parameters file which has the adjustable variables
import params_config.params as p

# Dictionaries
from params_config.config import MEDIA_CONFIG, SPECIMEN_TYPES, SHIFT_STAFFING_PROFILE, Instrument_resources

# -------------------------------
# ----- Module import -----------
from modules.inventory import MediaInventory, inventory_manager_process
from modules.tracker import SpecimenTracker
from modules.analytics import export_ai_training_dataset
from modules.shift_manager import shift_handoff_process, shift_manager_process, set_resource_capacity, get_current_shift_config

# Main DES simulation process
from modules.specimen_process_d2 import specimen_process, consume_media_inventory, get_tech_bench


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
    while True:
        yield env.timeout(interval)
        
        # Get active shift staffing target
        shift_cfg = get_current_shift_config(env.now, shift_staffing_profile)
        
        active_specs = active_counter['count']
        plating_q = len(resources["plating_bench"].queue)
        
        # Sum bench tech queues
        tech_q = (len(resources["tech_blood"].queue) + len(resources["tech_routine"].queue) + len(resources["tech_urine"].queue) + len(resources["tech_general"].queue) )
        
        # Calculate active busy tech count
        busy_techs = (resources["tech_blood"].count + resources["tech_routine"].count + resources["tech_urine"].count + resources["tech_general"].count)
        
        total_assigned_techs = (shift_cfg["tech_blood"] + shift_cfg["tech_routine"] + shift_cfg["tech_urine"] + shift_cfg["tech_general"])

        tracker.log_state(
            timestamp=env.now,
            active_specimens=active_specs,
            plating_queue=plating_q,
            tech_queue=tech_q,
            busy_techs=busy_techs,
            active_techs=total_assigned_techs
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

def nhpp_next_arrival_delta(current_minute, hourly_weights, daily_volume_mean):
    """
    Lewis-Shedler Thinning Algorithm for non-homogeneous Poisson processes.
    Generates proper inter-arrival gaps in MINUTES.
    """
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
        
        # 2. Determine current hour of day
        hour_of_day = int((sim_time % 1440) // 60)
        
        # 3. Calculate actual arrival rate for this hour
        actual_rate = (daily_volume_mean * norm_weights[hour_of_day]) / 60.0
        
        # 4. Thinning acceptance test
        if random.random() <= (actual_rate / max_rate):
            return t_elapsed  # Return true accumulated time delta in minutes


def specimen_generator(env, full_id, spec_type, resources, inventory, tracker, time_plating_mean, time_incubation_hours, active_counter, plating_batcher):
    spec_id = 0
    spec_cfg = SPECIMEN_TYPES[spec_type]
    hourly_weights = spec_cfg["hourly_arrival_weights"]
    daily_vol = spec_cfg["daily_volume_mean"]

    while True:
        # Calculate proper arrival gap
        time_to_next = nhpp_next_arrival_delta(env.now, hourly_weights, daily_vol)
        
        # 1. Wait for next specimen
        yield env.timeout(time_to_next)
        
        # 2. Spawn specimen process
        spec_id += 1
        full_id = f"{spec_type[:3].upper()}-{spec_id:05d}"
        
        env.process(specimen_process(
            env, full_id, spec_type, resources, inventory, tracker, 
            time_plating_mean, time_incubation_hours, active_counter, plating_batcher
        ))


# Place this function above run_simulation or near state_monitor_process
def deadlock_diagnostic_observer(env, resources, interval=60):
    """Prints resource queue bottlenecks to terminal to pinpoint hang-ups."""
    while True:
        yield env.timeout(interval)
        # print(f"\n--- 🔍 SIMULATION HEALTH CHECK | Sim Time: {env.now / 60:.1f} Hours ---")
        # for res_name, res in resources.items():
        #     queue_len = len(res.queue)
        #     users_len = len(res.users)
        #     cap = res.capacity
        #     if queue_len > 0 or users_len == cap:
        #         print(f"  • {res_name:<20} | Capacity: {users_len}/{cap} | Queued: {queue_len}")
        # print("----------------------------------------------------------\n")
        
# ==================================================================================
# == Run Simulation =============================================================
# ==================================================================================
def run_simulation(sim_days = None, seed = None, 
                   instrument_resources = None, shift_staffing_profile = None,
                   time_plating_mean = None, time_incubation_hours = None
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

    # Get initial staffing (Day 1, Shift 1) for initial Resource initialization
    initial_shift = shift_staffing_profile["Weekday"]["Shift_1_Day"]

    # 2. Initialize SimPy Resources using explicit values
    resources = {
        "plating_bench": simpy.PriorityResource(env, capacity=initial_shift["plating_capacity"]),
        "incubator": simpy.Resource(env, capacity=cap_incubators),
        "bc_instrument": simpy.Resource(env, capacity=bc_cap),
        "phoenix_instrument": simpy.Resource(env, capacity=phoenix_cap),

        # --- Split Techs by Bench ---
        "tech_blood": simpy.PriorityResource(env, capacity=initial_shift["tech_blood"]),
        "tech_routine": simpy.PriorityResource(env, capacity=initial_shift["tech_routine"]),
        "tech_urine": simpy.PriorityResource(env, capacity=initial_shift["tech_urine"]),
        "tech_general": simpy.PriorityResource(env, capacity=initial_shift["tech_general"])
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
            time_plating_mean, time_incubation_hours, 
            active_counter, plating_batcher
        ))

    env.run(until=sim_minutes)

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

    col_arrived = find_col(["1. Arrived", "Arrived", "Arrival"])
    col_plating = find_col(["3. Culture from Bottle Plating Started", "3A. Plating from Specimen Started", "Plating Started"])
    col_inc_start = find_col(["3B. Culture from Bottle Incubation Started", "3B. Incubation from Primary Specimen Started"])
    col_inc_end = find_col(["5. Tech Review Started", "Review Started"])
    col_completed = find_col(["5. Completed", "Completed", "Complete"])

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

    return df_pivot, df_state, media_usage, df_ai_features