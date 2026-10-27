import random

# Dictionaries
from params_config.specimen_config_d2 import SPECIMEN_TYPES
from modules.specimen_process_d5 import specimen_process

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



# ---------------------------------------------------------------------------
# --- Generate the Specimens -----------------------------------------
# ---------------------------------------------------------------------------
# def specimen_generator(env, full_id, spec_type, resources, inventory, tracker, active_counter, plating_batcher):
def specimen_generator(env, full_id, spec_type, resources, inventory, tracker, active_counter, plating_batcher, 
                       routine_plating_store, priority_plating_store, accession_incoming_store):
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
        
        # env.process(specimen_process(
        #     env, full_id, spec_type, resources, inventory, tracker, 
        #     active_counter, plating_batcher
        # ))
        env.process(specimen_process(
            env, full_id, spec_type, resources, inventory, tracker, 
            active_counter, 
            routine_plating_store, priority_plating_store, accession_incoming_store, 
            plating_batcher
        ))
