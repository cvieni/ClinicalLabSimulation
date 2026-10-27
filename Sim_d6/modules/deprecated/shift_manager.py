import simpy
import random
import numpy as np
import pandas as pd

# Centralized parameters file which has the adjustable variables
import params_config.deprecated.params as p

from modules.tech_breaks import single_shift_breaks


# ==================================================================================
# SAFELY ADJUST SIMPY RESOURCE CAPACITY AT RUNTIME
# ==================================================================================
# Dynamically adjust resource capcity -> example of adding 2 more lab techs.
# By adding this module you ensure that processess in the waiting queue are explicitly addressed, otherwise waiting processes would stay blocked until a slot naturally releases
def set_resource_capacity(resource, new_capacity):
    """
    Safely adjusts SimPy Resource or PriorityResource capacity dynamically
    and wakes queued requests when capacity increases.
    """
    new_capacity = max(0, int(new_capacity))
    old_capacity = resource.capacity

    if old_capacity == new_capacity:
        return

    # Update private attribute directly (SimPy has no capacity property setter)
    resource._capacity = new_capacity

    capacity_diff = new_capacity - old_capacity

    # CASE 1: Capacity Increased -> Trigger queued requests for each newly opened slot
    if capacity_diff > 0:
        slots_to_trigger = min(capacity_diff, len(resource.queue))
        
        for _ in range(slots_to_trigger):
            if hasattr(resource, '_trigger_put'):
                # PriorityResource / BaseResource in standard SimPy 4.x
                resource._trigger_put(None)
            elif hasattr(resource, '_do_put'):
                # Alternative backend hook in select custom/legacy resource wrappers
                resource._do_put(None)

    # CASE 2: Capacity Decreased -> Dynamic check prevents new queue entries until count < new_capacity
    # SimPy naturally lets currently active workers finish without ejecting them.
    else:
        if hasattr(resource, '_trigger_get'):
            resource._trigger_get(None)
        elif hasattr(resource, '_do_get'):
            resource._do_get(None)

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
    # with resources[bench_key].request(priority=-2) as req:
    #     yield req
    #     yield env.timeout(duration)
    if bench_key not in resources:
            return
            
    resource = resources[bench_key]
    num_to_lock = resource.capacity  # Lock all active tech slots on this bench
    
    requests = []
    for _ in range(num_to_lock):
        req = resource.request(priority=-10)
        requests.append(req)
    
    # Wait until all slots for this bench are acquired for the huddle
    yield simpy.AllOf(env, requests)
    yield env.timeout(duration)
    
    # Release slots back to processing work
    for req in requests:
        resource.release(req)

def shift_manager_process(env, resources, shift_staffing_profile):
    """Dynamically adjusts capacities and launches breaks relative to shift entry."""
    last_spawned_shift = None  # Tracks which shift's breaks were last launched

    # Complete list of tech bench keys in resources & staffing_config
    ALL_TECH_BENCHES = [
        "tech_accession", "tech_plating",
        "tech_blood", "tech_new",
        "tech_routine",
        "tech_stool", "tech_urine",
    ]

    while True:
        sim_time = env.now
        current_day = int(sim_time // 1440) % 7  # 0-4 = Mon-Fri, 5-6 = Sat-Sun
        current_hour = int((sim_time % 1440) // 60)
        
        # Handle night shift wrap-around (hours 0-6 belong to shift that started yesterday)
        effective_day = (current_day - 1) % 7 if current_hour < 7 else current_day
        
        is_weekend = effective_day in [5, 6]
        day_type = "Weekend" if is_weekend else "Weekday"
        profiles = shift_staffing_profile[day_type]
        
        # Determine active shift profile and shift start hour
        shift_1_start, shift_1_end = p.shift_1_start, p.shift_1_end
        shift_2_start, shift_2_end = p.shift_2_start, p.shift_2_end

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
        set_resource_capacity(resources["plating_bench"], profile.get("plating_capacity", 3))
        # set_resource_capacity(resources["tech_routine"], profile.get("plating_capacity", 4))
        for bench_key in ALL_TECH_BENCHES:
            if bench_key in resources:
                set_resource_capacity(resources[bench_key], profile.get(bench_key, 0))

        # 2. Trigger huddle & breaks only on shift change
        # if current_shift_key != last_spawned_shift:
        #     # Calculate absolute shift entry timestamp in simulation minutes
        #     if current_shift_key[0] == "Night" and current_hour < 7:
        #         # Night shift started yesterday at 23:00
        #         days_elapsed = int(env.now // 1440) - 1
        #         shift_start_time = (days_elapsed * 1440) + (shift_2_end * 60)
        #     else:
        #         days_elapsed = int(env.now // 1440)
        #         shift_start_time = (days_elapsed * 1440) + (shift_start_hour * 60)

        #     # Spawn shift handoff huddles
        #     benches = ["tech_blood", "tech_routine", "tech_urine"]
        #     for bench_key in benches:
        #         if profile.get(bench_key, 0) > 0:
        #             env.process(shift_handoff_process(env, resources, bench_key, duration=15))

        #     # Spawn breaks for techs across each active bench relative to shift entry
        #     for bench_key in ALL_TECH_BENCHES:
        #         active_count = profile.get(bench_key, 0)
        #         if active_count > 0 and bench_key in resources:
        #             # Spawn huddle for the bench
        #             env.process(shift_handoff_process(env, resources, bench_key, duration=15))
                    
        #             # Spawn individual tech breaks
        #             for tech_i in range(active_count):
        #                 env.process(single_shift_breaks(
        #                     env, resources, bench_key, tech_i, shift_start_time=shift_start_time
        #                 ))
            
        #     last_spawned_shift = current_shift_key

        # 2. Trigger huddle & breaks only on shift change
        if current_shift_key != last_spawned_shift:
            if current_shift_key[0] == "Night" and current_hour < 7:
                days_elapsed = int(env.now // 1440) - 1
                shift_start_time = (days_elapsed * 1440) + (shift_2_end * 60)
            else:
                days_elapsed = int(env.now // 1440)
                shift_start_time = (days_elapsed * 1440) + (shift_start_hour * 60)

            # Spawn huddle and breaks EXACTLY ONCE per active bench
            for bench_key in ALL_TECH_BENCHES:
                active_count = profile.get(bench_key, 0)
                if active_count > 0 and bench_key in resources:
                    # 1. Single Huddle
                    env.process(shift_handoff_process(env, resources, bench_key, duration=15))
                    
                    # 2. Staggered Breaks
                    for tech_i in range(active_count):
                        env.process(single_shift_breaks(
                            env, resources, bench_key, tech_i, shift_start_time=shift_start_time
                        ))
            
            last_spawned_shift = current_shift_key

        # 3. Check every hour
        yield env.timeout(60)