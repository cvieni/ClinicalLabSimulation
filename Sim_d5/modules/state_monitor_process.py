# modules/state_monitor_process
from params_config.staffing_config import SHIFT_STAFFING_PROFILE
from modules.shift_manager_d2 import shift_handoff_process, shift_manager_process, set_resource_capacity, get_current_shift_config

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
        "tech_stool",
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
        # Sum real-time SimPy capacity across active tech resources
        actual_simpy_capacity = sum(
            resources[key].capacity 
            for key in tech_keys 
            if key in resources
        )
        
        tracker.log_state(
            timestamp=env.now,
            active_specimens=active_specs,
            plating_queue=plating_q,
            tech_queue=tech_q,
            busy_techs=busy_techs,
            active_techs=total_assigned_techs, 
            actual_simpy_capacity = actual_simpy_capacity,
            **individual_tech_queues
        )
