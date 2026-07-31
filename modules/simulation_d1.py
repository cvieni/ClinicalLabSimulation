import simpy
import random
import numpy as np
import pandas as pd

from modules.inventory import MediaInventory, inventory_manager_process
from modules.tracker import SpecimenTracker

from modules.analytics import export_ai_training_dataset

# Dictionaries
from modules.config import MEDIA_CONFIG, SPECIMEN_TYPES, SHIFT_STAFFING_PROFILE 

# Define adjustable variables:
reincubation_percent = 0.08
rejection_percent = 0.02      # 2% of samples are rejected before processing
second_workup_percent = 0.80  #


class BatchAccumulator:
    """Buffers incoming requests until a batch size or timeout condition is met."""
    def __init__(self, env, batch_size=10, max_wait=15):
        self.env = env
        self.batch_size = batch_size
        self.max_wait = max_wait
        self.queue = []
        self.timer_active = False

    def wait_for_batch(self):
        """Processes call this to pause until released in a batch."""
        event = self.env.event()
        self.queue.append(event)

        if not self.timer_active:
            self.env.process(self._batch_timer())

        # Trigger release if batch size is reached immediately
        if len(self.queue) >= self.batch_size:
            self._flush_batch()

        return event

    def _batch_timer(self):
        self.timer_active = True
        yield self.env.timeout(self.max_wait)
        self._flush_batch()

    def _flush_batch(self):
        self.timer_active = False
        to_release = self.queue[:self.batch_size]
        self.queue = self.queue[self.batch_size:]
        
        for event in to_release:
            if not event.triggered:
                event.succeed()

# ==================================================================================
# SAFELY ADJUST SIMPY RESOURCE CAPACITY AT RUNTIME
# ==================================================================================
def set_resource_capacity(resource, new_capacity):
    """Safely adjusts SimPy Resource or PriorityResource capacity dynamically."""
    if resource.capacity != new_capacity:
        capacity_diff = new_capacity - resource.capacity
        # resource.capacity = new_capacity
        resource._capacity = new_capacity

        # If capacity increased, trigger queued requests to claim newly opened slots
        if capacity_diff > 0:
            if hasattr(resource, '_trigger_put'):
                resource._trigger_put(None)
            elif hasattr(resource, '_do_put'):
                # Fallback for alternative SimPy versions
                resource._do_put()

def state_monitor_process(env, resources, tracker, active_counter, interval=30):
    while True:
        yield env.timeout(interval)
        active_specs = active_counter['count']
        plating_q = len(resources["plating_bench"].queue)
        tech_q = len(resources["tech"].queue)
        
        tracker.log_state(env.now, active_specs, plating_q, tech_q)


def specimen_process(env, spec_id, spec_type, resources, inventory, tracker, time_plating_mean, time_incubation_hours, active_counter, plating_batcher):
    active_counter['count'] += 1
    # 1. Define media_requirements FIRST before any checks
    spec_cfg = SPECIMEN_TYPES[spec_type]
    media_requirements = spec_cfg["media_req"]

    # ==========================================
    # 1. ARRIVAL & PRE-ANALYTICAL REJECTION
    # ==========================================
    tracker.log_event(spec_id, spec_type, "1. Arrived", env.now)
    
    # Pre-Analytical Screening (e.g., mislabeled, clotted, insufficient volume)
    if random.random() < rejection_percent:
        tracker.log_event(spec_id, spec_type, "1b. Rejected (Pre-Analytical)", env.now)
        active_counter['count'] -= 1
        return  # Exit workflow immediately

    # ==========================================
    # 2. Check and Consume Inventory
    # ==========================================
    # Initialize variables
    media_allocated = False
    stockout_start = None
    attempts = 0

    while not media_allocated:
        can_fulfill = all(
            inventory.total_inventory(media) >= qty 
            for media, qty in media_requirements.items()
        )
        
        if can_fulfill:
            for media, qty in media_requirements.items():
                inventory.try_consume_media(media, qty)
                # Safely log media usage to tracker
                if hasattr(tracker, 'log_media_usage'):
                    tracker.log_media_usage(media, qty)
                else:
                    tracker.media_usage[media] = tracker.media_usage.get(media, 0) + qty

            media_allocated = True
            
            if stockout_start is not None:
                delay_duration = env.now - stockout_start
                tracker.log_stockout_delay(spec_id, delay_duration)
        else:
            attempts += 1
            if stockout_start is None:
                stockout_start = env.now
                tracker.log_event(spec_id, spec_type, "Stockout Delay Started", env.now)

            # Auto-fallback after 2 hours to avoid freezing the sim
            if attempts > 4:
                media_allocated = True
                break

            # Re-check inventory every 30 minutes during a stockout
            yield env.timeout(30)


    # Determine priority: Lower number = Higher priority
    # BCx gets Priority 1 (STAT), Breaks get Priority -1 (Top), Routine gets Priority 10
    is_stat = spec_type.upper().startswith("BCX") or spec_cfg.get("is_stat", False)
    spec_priority = 1 if is_stat else 10

    # ==========================================
    # 3. PLATING STAGE
    # ==========================================
    # Wait for batch of 10 or max 15 minutes before requesting plating bench
    yield plating_batcher.wait_for_batch()

    with resources["plating_bench"].request(priority=spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, "2. Plating Started", env.now)
        plating_duration = max(0.5, random.normalvariate(time_plating_mean, 3.0))
        yield env.timeout(plating_duration)

    # ==========================================
    # 4. INCUBATION STAGE
    # ==========================================
    tracker.log_event(spec_id, spec_type, "3. Incubation Started", env.now)
    incubation_duration = max(60, random.normalvariate(time_incubation_hours * 60, 120))
    yield env.timeout(incubation_duration)
    # 4b. Stochastic Re-Incubation STAGE
    if random.random() < reincubation_percent:  # 8% need re-incubation
        tracker.log_event(spec_id, spec_type, "3b. Extended Incubation", env.now)
        yield env.timeout(12 * 60)  # Extra 12 hours
  
    # ==========================================
    # 5. TECH REVIEW STAGE
    # ==========================================
    with resources["tech"].request(priority=spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, "4. Review Started", env.now)
        
        # Two ways to model this -> 
        # 1. Apply a specific amount of time per Specimen
        # 2. Apply a specific amount of time per plate
        # Added a dictionary definition for each specimen type as Urine likely is faster per plate, then tissue/wound
        min_time, max_time = spec_cfg.get("tech_review_range", (2.0, 5.0))
        # Draw a random processing time within that specimen's specific range
        specimen_review_time = random.uniform(min_time, max_time)
        yield env.timeout(specimen_review_time)

    # ==========================================
    # 6a. REFLEX TESTING & SUB-CULTURE
    # ==========================================
    if random.random() < second_workup_percent:
        # STEP 1: Subculture Pure Colony
        with resources["tech"].request(priority=spec_priority) as req:
            yield req
            tracker.log_event(spec_id, spec_type, "4a. Sub Pure Colony Started", env.now)
            # Tech subcultures/streaks mixed/dirty culture to a fresh isolation plate (e.g., 3-5 mins)
            yield env.timeout(random.uniform(1.0, 3.0))
        
        # Overnight incubation for the pure colony subculture (e.g., 18-24 hours)
        tracker.log_event(spec_id, spec_type, "4b. Sub Pure Colony Incubation", env.now)
        yield env.timeout(random.uniform(18.0, 24.0) * 60)

        # ==========================================
        # 6b. REFLEX TESTING: MALDI-TOF IDENTIFICATION
        # ==========================================
        with resources["tech"].request(priority=spec_priority) as req:
            yield req
            tracker.log_event(spec_id, spec_type, "4c. MALDI Prep Started", env.now)
            # Tech spots target plate and adds matrix target preparation (10 mins)
            yield env.timeout(10)
            
        # Mass Spectrometer automated run (20 mins, no tech occupied)
        yield env.timeout(20)
        tracker.log_event(spec_id, spec_type, "4d. MALDI ID Completed", env.now)

        
    # ==========================================
    # 10. COMPLETE
    # ==========================================
    tracker.log_event(spec_id, spec_type, "5. Completed", env.now)
    active_counter['count'] -= 1


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


def specimen_generator(env, spec_type, resources, inventory, tracker, time_plating_mean, time_incubation_hours, active_counter, plating_batcher):
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


# ==================================================================================
# Shift Controller Process
# ==================================================================================
def shift_handoff_process(env, resources, duration=15):
    """Locks high-priority tech resource slots for team huddles at shift change."""
    with resources["tech"].request(priority=-2) as req:
        yield req
        yield env.timeout(duration)  # 15-minute handoff delay

def shift_manager_process(env, resources):
    """Dynamically adjusts capacities based on time of day AND day of week."""
    last_spawned_shift = None  # Tracks which shift's breaks were last launched

    while True:
        current_day = int(env.now // 1440) % 7  # 0-4 = Mon-Fri, 5-6 = Sat-Sun
        current_hour = int((env.now % 1440) // 60)
        
        # Handle night shift wrap-around (hours 0-6 belong to the shift that started yesterday)
        effective_day = (current_day - 1) % 7 if current_hour < 7 else current_day
        
        is_weekend = effective_day in [5, 6]
        day_type = "Weekend" if is_weekend else "Weekday"
        profiles = SHIFT_STAFFING_PROFILE[day_type]
        
        # Determine active shift profile
        if 7 <= current_hour < 15:
            profile = profiles["Shift_1_Day"]
            current_shift_key = ("Day", effective_day)
        elif 15 <= current_hour < 23:
            profile = profiles["Shift_2_Evening"]
            current_shift_key = ("Evening", effective_day)
        else:
            profile = profiles["Shift_3_Night"]
            current_shift_key = ("Night", effective_day)

        # 1. Safely set dynamic capacities
        active_techs = profile["tech_capacity"]
        set_resource_capacity(resources["plating_bench"], profile["plating_capacity"])
        set_resource_capacity(resources["tech"], profile["tech_capacity"])

        # 2. Inject Break Processes ONLY for the active technicians working this shift
        # Trigger shift handoff huddle & breaks when a NEW shift starts
        if current_shift_key != last_spawned_shift:
            # 1. Start 15-min shift handoff huddle
            env.process(shift_handoff_process(env, resources, duration=15))
            
            # 2. Spawn breaks for active techs
            for tech_i in range(active_techs):
                env.process(single_shift_breaks(env, resources, tech_i))
            
            last_spawned_shift = current_shift_key

        # 3. Check every hour
        yield env.timeout(60)  # Re-evaluate capacity every hour

# ==================================================================================
# Tech Breaks Generator
# ==================================================================================
def single_shift_breaks(env, resources, tech_id, shift_start_offset=0):
    """
    Simulates breaks for 1 technician during a SINGLE 8-hour shift.
    Staggers breaks slightly per tech_id so everyone doesn't eat lunch simultaneously.
    """
    # Stagger breaks by 15 mins per tech so 5 techs take lunch sequentially
    stagger_delay = tech_id * 15

    # Shift starts at t=0 relative to cycle
    # --- 1. Random 5-min bathroom break in first 2 hours of shift ---
    bathroom_break = random.randint(30, 90) + stagger_delay
    yield env.timeout(bathroom_break)
    with resources["tech"].request(priority=-1) as req:
        yield req
        yield env.timeout(5)

    # --- 2. Scheduled 15-min morning break (~2 hours in) ---
    # Subtract previous delay/duration so this lands at the 2-hour mark
    time_to_morning_break = max(0, 120 - (bathroom_break + 5))
    yield env.timeout(time_to_morning_break)
    with resources["tech"].request(priority=-1) as req:
        yield req
        yield env.timeout(15)

    # 3. Lunch Break (~4.5 hours in)
    # --- Scheduled 30-min lunch break (~4.5 hours in) ---
    # 270 mins target - 135 mins elapsed = 135 mins wait
    yield env.timeout(135)  
    with resources["tech"].request(priority=-1) as req:
        yield req
        yield env.timeout(30)

        
# ==================================================================================
# == Run Simulation =============================================================
# ==================================================================================
def run_simulation(sim_days, seed, cap_plating, cap_techs, cap_incubators, time_plating_mean, time_incubation_hours):
    random.seed(seed)
    np.random.seed(seed)
    sim_minutes = sim_days * 24 * 60

    env = simpy.Environment()

    # 1. Initiate Trackers, Inventory, and Shared Batcher
    tracker = SpecimenTracker()
    inventory = MediaInventory(env, MEDIA_CONFIG)
    active_counter = {'count': 0}
    plating_batcher = BatchAccumulator(env, batch_size=10, max_wait=15)

    # 2. Define Resources
    resources = {
        "plating_bench": simpy.PriorityResource(env, capacity=cap_plating),
        "tech": simpy.PriorityResource(env, capacity=cap_techs),
        "incubator": simpy.Resource(env, capacity=cap_incubators)
    }

    # 3. Start Background Processes
    env.process(inventory_manager_process(env, inventory, MEDIA_CONFIG))
    env.process(state_monitor_process(env, resources, tracker, active_counter, interval=30))
    env.process(shift_manager_process(env, resources))

    # 4. Start Generators
    for spec_type in SPECIMEN_TYPES:
        env.process(specimen_generator(
            env, spec_type, resources, inventory, tracker, time_plating_mean, 
            time_incubation_hours, active_counter, plating_batcher
        ))

    # 5. Run Simulation
    env.run(until=sim_minutes)

    # 6. Extract Logs
    logs = getattr(tracker, 'logs', [])
    state_logs = getattr(tracker, 'state_logs', [])
    media_usage = dict(getattr(tracker, 'media_usage', {}))

    df_raw = pd.DataFrame(logs)
    df_state = pd.DataFrame(state_logs)

    if df_raw.empty:
        return pd.DataFrame(), df_state, media_usage, pd.DataFrame()

    # 7. Pivot Event Log Safely
    df_pivot = df_raw.pivot(index=["Specimen_ID", "Type"], columns="Stage", values="Minute").reset_index()

    def find_col(possible_names):
        for name in possible_names:
            if name in df_pivot.columns:
                return name
        return None

    col_arrived = find_col(["1. Arrived", "Arrived", "Arrival"])
    col_plating = find_col(["2. Plating Started", "Plating Started", "Plating"])
    col_inc_start = find_col(["3. Incubation Started", "Incubation Started"])
    col_inc_end = find_col(["4. Review Started", "Incubation Ended", "Review Started"])
    col_completed = find_col(["5. Completed", "Completed", "Complete"])

    # 8. Compute Operational KPIs
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

    # 9. Export AI Training Features
    try:
        df_ai_features = export_ai_training_dataset(df_raw, df_state, tracker)
    except Exception:
        df_ai_features = pd.DataFrame()

    return df_pivot, df_state, media_usage, df_ai_features