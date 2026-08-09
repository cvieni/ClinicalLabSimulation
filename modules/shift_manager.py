import simpy
import random
import numpy as np
import pandas as pd

# Centralized parameters file which has the adjustable variables
import params_config.params as p

from modules.tech_breaks import single_shift_breaks


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
        shift_1_start, shift_1_end = p.shift_1_start, p.shift_1_end
        shift_2_start, shift_2_end = p.shift_2_start, p.shift_2_end
        # shift_3_start, shift_3_end = p.shift_3_start, p.shift_3_end

        if shift_1_start <= current_hour < shift_1_end:
            profile = profiles["Shift_1_Day"]
            current_shift_key = ("Day", effective_day)
            shift_start_hour = shift_1_start
        elif shift_2_start <= current_hour < shift_2_end:
            profile = profiles["Shift_2_Evening"]
            current_shift_key = ("Evening", effective_day)
            shift_start_hour = shift_2_start
        else:
            profile = profiles["Shift_3_Night"]
            current_shift_key = ("Night", effective_day)
            shift_start_hour = shift_2_end if current_hour >= shift_2_end else -1  # Night shift starts at 23:00 previous day

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
                shift_start_time = (days_elapsed * 1440) + (shift_2_end * 60)
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