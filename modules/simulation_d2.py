import simpy
import random
import numpy as np
import pandas as pd

# Centralized parameters file which has the adjustable variables
import params_config.params as p

from modules.inventory import MediaInventory, inventory_manager_process
from modules.tracker import SpecimenTracker

from modules.analytics import export_ai_training_dataset

# Dictionaries
from params_config.config import MEDIA_CONFIG, SPECIMEN_TYPES, SHIFT_STAFFING_PROFILE, Instrument_resources



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

# ==================================================================================
# SAFELY ADJUST SIMPY RESOURCE CAPACITY AT RUNTIME
# ==================================================================================
# Dynamically adjust resource capcity -> example of adding 2 more lab techs.
# By adding this module you ensure that processess in the waiting queue are explicitly addressed, otherwise waiting processes would stay blocked until a slot naturally releases
def set_resource_capacity(resource, new_capacity):
    """Safely adjusts SimPy Resource or PriorityResource capacity dynamically."""
    if resource.capacity != new_capacity:
        capacity_diff = new_capacity - resource.capacity
        # Update SimPys internal capacity counter
        # resource._capacity = new_capacity
        # Ensures capacity is >0
        resource._capacity = max(0, new_capacity)

        # If capacity increased, trigger queued requests to claim newly opened slots
        if capacity_diff > 0:
            if hasattr(resource, '_trigger_put'):
                resource._trigger_put(None)
            elif hasattr(resource, '_do_put'):
                # Fallback for alternative SimPy versions
                resource._do_put()

def get_current_shift_config(sim_minute, shift_staffing_profile):
    """Calculates active shift configuration based on simulation minute (clock time)."""
    current_hour = (sim_minute / 60.0) % 24
    day_of_week = int(sim_minute // (24 * 60)) % 7
    day_type = "Weekend" if day_of_week >= 5 else "Weekday"
    
    shifts = shift_staffing_profile.get(day_type, {})
    for shift_key, config in shifts.items():
        start_h, end_h = config["hours"]
        if start_h < end_h:
            if start_h <= current_hour < end_h:
                return config
        else:  # Overnight shift spanning midnight
            if current_hour >= start_h or current_hour < end_h:
                return config
                
    raise ValueError(f"No shift matching current time: Hour {current_hour:.1f}, Day Type: {day_type}")

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

# ==========================================
# 1. Check and Consume Inventory Helper Function
# ==========================================
def consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_req):
    # Initialize variables
    # media_allocated = False
    stockout_start = None
    attempts = 0
    max_attempts = 5

    while attempts < max_attempts:
        can_fulfill = all(
            inventory.total_inventory(media) >= qty 
            for media, qty in media_req.items()
        )
        
        if can_fulfill:
            for media, qty in media_req.items():
                inventory.try_consume_media(media, qty)
                # Safely log media usage to tracker
                if hasattr(tracker, 'log_media_usage'):
                    tracker.log_media_usage(media, qty)
                else:
                    tracker.media_usage[media] = tracker.media_usage.get(media, 0) + qty

            if stockout_start is not None:
                delay_duration = env.now - stockout_start
                tracker.log_stockout_delay(spec_id, delay_duration)

            return True  # Successfully allocated
        else:
            attempts += 1
            if stockout_start is None:
                stockout_start = env.now
                tracker.log_event(spec_id, spec_type, "Stockout Delay Started", env.now)

            # Re-check inventory every N minutes during a stockout
            recheck_interval = getattr(p, 'inventory_stockout_recheck', 15)
            yield env.timeout(recheck_interval)

    # Max attempts reached; log failure and return False without forcing consumption
    tracker.log_event(spec_id, spec_type, "3b. Media Allocation Failed - Aborted", env.now)
    return False

# Helper to pick the right tech resource based on specimen type
def get_tech_bench(spec_type, resources):
    if spec_type in ["BCx", "BodyFluid"]:
        return resources["tech_blood"]
    elif spec_type in ["Urine"]:
        return resources["tech_urine"]
    elif spec_type in ["Tissue", "Tissue_genital", "Tissue_FNA", "Bone_Cx"]:
        return resources["tech_routine"]
    else:
        return resources["tech_general"]

# ==================================================================================
# Process Specimens
# ==================================================================================
def specimen_process(env, spec_id, spec_type, resources, inventory, tracker, time_plating_mean, time_incubation_hours, active_counter, plating_batcher):
    active_counter['count'] += 1

    # 1. Define media_requirements and culture type FIRST before any checks
    spec_cfg = SPECIMEN_TYPES[spec_type]
    is_blood_culture = spec_type.upper().startswith("BCX") or spec_cfg.get("is_blood_culture", False)
    is_body_fluid = spec_type.upper().startswith("BodyFluid") or spec_cfg.get("is_BodyFluid", False)

    # ==========================================
    # 1. ARRIVAL & PRE-ANALYTICAL REJECTION
    # ==========================================
    tracker.log_event(spec_id, spec_type, "1. Arrived", env.now)
    # Pre-Analytical Screening (e.g., mislabeled, clotted, insufficient volume)
    if random.random() < p.rejection_percent:
        tracker.log_event(spec_id, spec_type, "1b. Rejected (Pre-Analytical)", env.now)
        active_counter['count'] -= 1
        return  # Exit workflow immediately


    # ==========================================
    # 2: INITIAL PROCESSING (Automated instrument vs. Direct plating)
    # 2A. Blood cultures + Body fluids (Automated instrument, ex. BACTEC)
    # ==========================================
    if is_blood_culture or is_body_fluid:
        tracker.log_event(spec_id, spec_type, "2a. Loaded into Automated Bactec Instrument", env.now)
                    
        # Define Positivity probability (~10-15% of blood cultures are positive)
        if is_blood_culture is True:
            pos_rate = spec_cfg.get("positivity_rate", p.BCx_positivity)
            # Time until machine flags positive (typically 12 - 36 hours)
            # normalvariate = (mean , standard deviation); max to prevent unrealistic pos times
            mean_pos_time = p.avg_time2posBcx
            std_pos_time = p.std_time2posBcx
        elif is_body_fluid is True:
            pos_rate = spec_cfg.get("positivity_rate", p.BdyFlid_positivity)
            mean_pos_time = p.avg_time2posBdyFld
            std_pos_time = p.std_time2posBdyFld

        is_positive = random.random() < pos_rate

        # --- MACHINE CAPACITY HELD HERE ---
        with resources["bc_instrument"].request() as bc_req:
            yield bc_req
            
            if is_positive:
                time_to_pos_hours = max(8.0, random.normalvariate(mean_pos_time, std_pos_time))
                yield env.timeout(time_to_pos_hours * 60)
                tracker.log_event(spec_id, spec_type, "2b. BCx or BodyFluid Flagged POSITIVE", env.now)
            else:
                # Holds the instrument slot for 5 days (120 hours) then frees slot
                yield env.timeout(120 * 60)
                tracker.log_event(spec_id, spec_type, "BC Flagged NEGATIVE (Final)", env.now)
                active_counter['count'] -= 1
                return  # Negative culture completes workflow
        # --- OUT OF MACHINE: Slot is now free for new samples ---

        # 3. PLATING STAGE
        # If positive, proceed to downstream subculturing & incubation
        # --- NOW ALLOCATE AGAR PLATES FOR SUBCULTURE ---
        media_requirements = spec_cfg["media_req"]
        media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_requirements)
        if not media_allocated:
            active_counter['count'] -= 1
            return  # Abort specimen processing immediately

            # --- HIGH PRIORITY (STAT) PLATING ---
        spec_priority = 1  # STAT Priority
        # Move specimen to plating bench
        with resources["plating_bench"].request(priority=spec_priority) as req:
            yield req
            tracker.log_event(spec_id, spec_type, "3. Culture from Bottle Plating Started", env.now)
            # Use getattr to prevent AttributeError if params misses a key
            # Fallback to 1.0
            std_time = p.plating_std_time
            min_time =p.min_plating_time
            plating_duration = max(min_time, random.normalvariate(time_plating_mean, std_time))

            yield env.timeout(plating_duration)

        # 4. SUBCULTURE AGAR INCUBATION (~24 Hours) ----------
        with resources["incubator"].request() as inc_req:
            yield inc_req
            tracker.log_event(spec_id, spec_type, "3B. Culture from Bottle Incubation Started", env.now)
            # ~24 hour agar plate incubation
            subculture_inc_duration = max(p.min_subcult_incbtion_time_Bcx * 60, random.normalvariate(24 * 60, 120))
            yield env.timeout(subculture_inc_duration)

    # ==========================================
    # 2B. PATHWAY B: STANDARD DIRECT-PLATING WORKFLOW (Urine, Wounds, Sputum, etc.)
    # ==========================================
    else:
        media_requirements = spec_cfg["media_req"]
        # yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_requirements)
        media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_requirements)
        if not media_allocated:
            active_counter['count'] -= 1
            return  # Abort specimen processing immediately

        spec_priority = 1 if spec_cfg.get("is_stat", False) else 10

        # 3. PLATING STAGE
        # Wait for batch of 10 or max 15 minutes before requesting plating bench
        yield plating_batcher.wait_for_batch()

        # Move specimen to plating bench
        with resources["plating_bench"].request(priority=spec_priority) as req:
            yield req
            tracker.log_event(spec_id, spec_type, "3A. Plating from Specimen Started", env.now)
            mu = p.avg_plating_time
            sigma = p.plating_std_time
            plating_duration = max(p.min_plating_time, random.normalvariate(mu, sigma))
            # plating_duration = max(p.min_plating_time, random.normalvariate(time_plating_mean, p.max_plating_time))
            yield env.timeout(plating_duration)

        # 4. INCUBATION STAGE
        # ==========================================
        # Move specimen to Incubation
        with resources["incubator"].request() as inc_req:
            yield inc_req
            tracker.log_event(spec_id, spec_type, "3B. Incubation from Primary Specimen Started", env.now)
            incubation_duration = max(p.min_incubation_time_Other, random.normalvariate(time_incubation_hours * 60, 120))
            yield env.timeout(incubation_duration)

    # =============================================================================
    # ==========================================
    # 5. Unified Tech REVIEW STAGE (after first incubation)
    # ==========================================
    # Initial Tech Review (Applies equally to all incubated agar plates)
    # Two ways to model this -> 
    # 1. Apply a specific amount of time per Specimen
    # 2. Apply a specific amount of time per plate
    # Added a dictionary definition for each specimen type as Urine likely is faster per plate, then tissue/wound
    tech_resource = get_tech_bench(spec_type, resources)

    with tech_resource.request(priority=spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, "5. Tech Review Started", env.now)
        min_time, max_time = spec_cfg.get("tech_review_range", (p.min_tech_review_sub, p.max_tech_review_sub))
        yield env.timeout(random.uniform(min_time, max_time))

    # ==========================================
    # 5B. Stochastic chance of needing to reincubate for an addtl ~4-12 hours
    # ==========================================
    if random.random() < p.reincubation_percent:  # 8% need re-incubation
        with resources["incubator"].request() as reinc_req:
            yield reinc_req
            tracker.log_event(spec_id, spec_type, "5a. Extended Re-Incubation", env.now)
            min_reinc = getattr(p, 'min_reincubate_time', 4.0) * 60
            max_reinc = getattr(p, 'max_reincubate_time', 12.0) * 60
            yield env.timeout(random.uniform(min_reinc, max_reinc))
  
    # ==========================================
    # 6a. REFLEX TESTING & SUB-CULTURE
    # ==========================================
    if is_blood_culture or is_body_fluid:
        # STEP 1: Evaluate Subculture
        with resources["tech_general"].request(priority=spec_priority) as req:
            yield req
            tracker.log_event(spec_id, spec_type, "4a. Evaluate Subculture", env.now)
            # Tech subcultures/streaks mixed/dirty culture to a fresh isolation plate (e.g., 3-5 mins)
            yield env.timeout(random.uniform(p.min_subcultEval_time, p.max_subcultEval_time))
    else:
        # Track how many times this specimen has undergone subculturing
        subculture_count = 0
        max_subcultures = getattr(p, 'max_subculture_limit', 3) # Safeguard cap if needed

        while subculture_count < max_subcultures:
            # Determine probability based on current subculture iteration
            if subculture_count == 0:
                chance = p.second_workup_percent  # First time evaluating a second workup
            elif subculture_count == 1:
                chance = p.third_workup_percent  # Third workup probability
            else:
                chance = p.additional_workup_percent # Optional fallback for 4th+

            # Roll to see if another subculture workup is required
            if random.random() < chance:
                subculture_count += 1
                
                # STEP 1: Subculture Pure Colony
                with resources["tech_routine"].request(priority=spec_priority) as req:
                    yield req
                    stage_label = f"4a. Sub Pure Colony #{subculture_count} Started"
                    tracker.log_event(spec_id, spec_type, stage_label, env.now)
                    # Tech subcultures/streaks mixed/dirty culture to a fresh isolation plate
                    yield env.timeout(random.uniform(p.min_subculture_time, p.max_subculture_time))
                
                # Overnight incubation for the pure colony subculture (18-24 hours)
                with resources["incubator"].request() as inc_req:
                    yield inc_req
                    inc_label = f"4b. Sub Pure Colony #{subculture_count} Incubation"
                    tracker.log_event(spec_id, spec_type, inc_label, env.now)
                    yield env.timeout(random.uniform(18.0, 24.0) * 60)
            else:
                # If no further workup is needed, break out of the loop
                break

    # ==========================================
    # 6b. REFLEX TESTING: MALDI-TOF IDENTIFICATION
    # ==========================================
    if random.random() < p.maldi_testing_percent:
        # Determine least busy tech between tech_routine and tech_general
        r_tech = resources.get("tech_routine", resources["tech_general"])
        g_tech = resources["tech_general"]

        # Compare capacity-adjusted workload ratios
        r_ratio = len(r_tech.queue) / max(1, r_tech.capacity)
        g_ratio = len(g_tech.queue) / max(1, g_tech.capacity)
        chosen_tech = r_tech if r_ratio <= g_ratio else g_tech

        with chosen_tech.request(priority=spec_priority) as tech_req:
            yield tech_req
            tracker.log_event(spec_id, spec_type, "6a. MALDI Target Spotting Started", env.now)
            
            maldi_prep_time = random.uniform(
                getattr(p, 'min_maldi_prep_time', 5.0), 
                getattr(p, 'max_maldi_prep_time', 15.0)
            )
            yield env.timeout(maldi_prep_time)
            tracker.log_event(spec_id, spec_type, "6b. MALDI ID Completed", env.now)

    # ==========================================
    # 6c. REFLEX TESTING: PHOENIX
    # ==========================================
    if random.random() < p.Phoenix_test_percent:
        # 1. Route prep to whichever tech (routine vs general) has a shorter line
        r_tech = resources.get("tech_routine", resources["tech_general"])
        g_tech = resources["tech_general"]

        # Compare capacity-adjusted workload ratios
        r_ratio = len(r_tech.queue) / max(1, r_tech.capacity)
        g_ratio = len(g_tech.queue) / max(1, g_tech.capacity)
        chosen_tech = r_tech if r_ratio <= g_ratio else g_tech

        with chosen_tech.request(priority=spec_priority) as tech_req:
            yield tech_req
            tracker.log_event(spec_id, spec_type, "7a. Phoenix Prep Started", env.now)
            prep_time = random.uniform(p.min_PHENIXprep_time, p.max_PHENIXprep_time)
            yield env.timeout(prep_time)

        # 2. Phoenix Instrument Incubation (4-hour max queue timeout)
        phoenix_res = resources["phoenix_instrument"]
        phoenix_req = phoenix_res.request()
        timeout_evt = env.timeout(240)  # 240 mins max wait time

        results = yield phoenix_req | timeout_evt

        if phoenix_req in results:
            try:
                tracker.log_event(spec_id, spec_type, "7b. Phoenix Incubation Started", env.now)
                phoenix_run_time = getattr(p, 'phoenix_run_time_hours', 4.0) * 60
                yield env.timeout(phoenix_run_time)
                tracker.log_event(spec_id, spec_type, "7c. Phoenix AST Completed", env.now)
            finally:
                phoenix_res.release(phoenix_req)
        else:
            phoenix_req.cancel()
            tracker.log_event(spec_id, spec_type, "Phoenix Slot Timeout - Deferred/Bypassed", env.now)
            print(f"⚠️ [TIMEOUT WARNING] t={env.now/60:.1f}h | {spec_id} timed out waiting for Phoenix slot!")

    # ==========================================
    # 10. COMPLETE
    # ==========================================
    tracker.log_event(spec_id, spec_type, "5. Completed", env.now)
    active_counter['count'] -= 1


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


# ==================================================================================
# Shift Controller Process
# ==================================================================================
def shift_handoff_process(env, resources, bench_key, duration=p.handoff_time):
    """Locks high-priority tech resource slots on a specific bench for team huddles."""
    with resources[bench_key].request(priority=-2) as req:
        yield req
        yield env.timeout(duration)

def shift_manager_process(env, resources, shift_staffing_profile):
    """Dynamically adjusts capacities and launches breaks relative to shift entry."""
    last_spawned_shift = None  # Tracks which shift's breaks were last launched

    while True:
        current_day = int(env.now // 1440) % 7  # 0-4 = Mon-Fri, 5-6 = Sat-Sun
        current_hour = int((env.now % 1440) // 60)
        
        # Handle night shift wrap-around (hours 0-6 belong to shift that started yesterday)
        effective_day = (current_day - 1) % 7 if current_hour < 7 else current_day
        
        is_weekend = effective_day in [5, 6]
        day_type = "Weekend" if is_weekend else "Weekday"
        profiles = shift_staffing_profile[day_type]
        
        # Determine active shift profile and shift start hour
        if 7 <= current_hour < 15:
            profile = profiles["Shift_1_Day"]
            current_shift_key = ("Day", effective_day)
            shift_start_hour = 7
        elif 15 <= current_hour < 23:
            profile = profiles["Shift_2_Evening"]
            current_shift_key = ("Evening", effective_day)
            shift_start_hour = 15
        else:
            profile = profiles["Shift_3_Night"]
            current_shift_key = ("Night", effective_day)
            shift_start_hour = 23 if current_hour >= 23 else -1  # Night shift starts at 23:00 previous day

        # 1. Dynamically set bench-specific tech capacities
        set_resource_capacity(resources["plating_bench"], profile["plating_capacity"])
        set_resource_capacity(resources["tech_blood"], profile.get("tech_blood", 0))
        set_resource_capacity(resources["tech_routine"], profile.get("tech_routine", 0))
        set_resource_capacity(resources["tech_urine"], profile.get("tech_urine", 0))
        set_resource_capacity(resources["tech_general"], profile.get("tech_general", 0))

        # 2. Trigger huddle & breaks on shift change
        if current_shift_key != last_spawned_shift:
            # Calculate absolute shift entry timestamp in simulation minutes
            if current_shift_key[0] == "Night" and current_hour < 7:
                # Night shift started yesterday at 23:00
                days_elapsed = int(env.now // 1440) - 1
                shift_start_time = (days_elapsed * 1440) + (23 * 60)
            else:
                days_elapsed = int(env.now // 1440)
                shift_start_time = (days_elapsed * 1440) + (shift_start_hour * 60)

            # Spawn shift handoff huddles
            benches = ["tech_blood", "tech_routine", "tech_urine", "tech_general"]
            for bench_key in benches:
                if profile.get(bench_key, 0) > 0:
                    env.process(shift_handoff_process(env, resources, bench_key, duration=15))

            # Spawn breaks for techs across each active bench relative to shift entry
            for bench_key in benches:
                active_count = profile.get(bench_key, 0)
                for tech_i in range(active_count):
                    env.process(single_shift_breaks(
                        env, resources, bench_key, tech_i, shift_start_time=shift_start_time
                    ))
            
            last_spawned_shift = current_shift_key

        # 3. Check every hour
        yield env.timeout(60)

# ==================================================================================
# Tech Breaks Generator
# ==================================================================================
def single_shift_breaks(env, resources, bench_key, tech_id, shift_start_time=0):
    """
    Simulates breaks for 1 technician during a SINGLE 8-hour shift.
    Staggers breaks slightly per tech_id so everyone doesn't eat lunch simultaneously.
    """
    # Stagger breaks by 15 mins per tech so 5 techs take lunch sequentially
    stagger_delay = tech_id * 15

    # Calculate offset if process started slightly after shift start
    time_into_shift = env.now - shift_start_time

    # Shift starts at t=0 relative to cycle
    # --- 1. Random 5-min bathroom break in first 2 hours of shift ---
    bathroom_break = random.randint(30, 90) + stagger_delay
    delay_1 = max(0, bathroom_break - time_into_shift)
    yield env.timeout(delay_1)
    with resources[bench_key].request(priority=-1) as req:
        yield req
        yield env.timeout(5)

    # --- 2. Scheduled 15-min morning break (~2 hours in) ---
    # Subtract previous delay/duration so this lands at the 2-hour mark
    elapsed = env.now - shift_start_time
    delay_2 = max(0, 120 + stagger_delay - elapsed)
    # time_to_morning_break = max(0, 120 - (bathroom_break + 5))
    yield env.timeout(delay_2)
    with resources[bench_key].request(priority=-1) as req:
        yield req
        yield env.timeout(15)

    # 3. Lunch Break (~4.5 hours in)
    # --- Scheduled 30-min lunch break (~4.5 hours in) ---
    # 270 mins target - 135 mins elapsed = 135 mins wait
    elapsed = env.now - shift_start_time
    delay_3 = max(0, 270 + stagger_delay - elapsed)
    yield env.timeout(delay_3)
    # yield env.timeout(135)  
    with resources[bench_key].request(priority=-1) as req:
        yield req
        yield env.timeout(30)



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
    batch_size = getattr(p, 'batch_size', 10) if 'p' in globals() else 10
    max_wait = getattr(p, 'max_wait', 15) if 'p' in globals() else 15
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