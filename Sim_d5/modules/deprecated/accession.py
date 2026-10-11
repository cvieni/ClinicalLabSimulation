import random
import numpy as np
import params_config.params_d2 as p
from modules.specimen_priority import get_specimen_priority
from modules.spec_proc_helpers import req_resource

def process_accessioning(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority,
                        arrival_time, routine_plating_store):

    # ==========================================
    # 1c. CENTRAL PROCESSING & ACCESSIONING
    # ==========================================
    tracker.log_event(spec_id, spec_type, "1c. Arrived at Pre-Accession Hold", env.now)

    # -------------------------------------------------------------
    # Step A: Pre-Accession Holding / Sorting Track (NO TECH REQUIRED)
    # -------------------------------------------------------------
    # Calculate base priority from specimen config
    base_priority = get_specimen_priority(spec_cfg)

    IS_HIGH_PRIORITY_STAT = base_priority <= 4

    if not IS_HIGH_PRIORITY_STAT:
        base_priority = get_specimen_priority(spec_cfg)
        time_waiting = env.now - arrival_time
        # Improves priority by 1 rank per 15 mins of wait time, clamped at max priority level 4
        spec_priority = max(5.0, base_priority - (time_waiting / 15.0))

    # ==========================================
    # 2. PRE-ACCESSION HOLDING TRACK (No Tech Required)
    # ==========================================
    if IS_HIGH_PRIORITY_STAT:
        pre_accession_hold = 0.0
    else:
        acc_config = spec_cfg["accession_time_config"]
        probs = acc_config["bin_probabilities"]
        edges = acc_config["bin_edges"]        
        bin_idx = np.random.choice(len(probs), p=probs)
        pre_accession_hold = random.uniform(edges[bin_idx], edges[bin_idx + 1])

    if pre_accession_hold > 0:
        yield env.timeout(pre_accession_hold)

    # ==========================================
    # 3. ACTIVE TECH TOUCH (Resource Allocation & Load Balancing)
    # ==========================================
    tracker.log_event(spec_id, spec_type, "1c. Waiting for Accession Tech", env.now)

    # Load balance: Overflow to plating techs if accession queue exceeds threshold
    tech_pool = resources['tech_accession']
    if len(tech_pool.queue) > 50:
        candidates = [resources['tech_accession'], resources.get('tech_float')]
        valid_candidates = [r for r in candidates if r and r.capacity > 0]
        if valid_candidates:
            tech_pool = min(valid_candidates, key=lambda r: len(r.queue) / r.capacity)


    with req_resource(tech_pool, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, "1d. Accessioning Started (Tech Touch)", env.now)

        # -----------------------------------------------------
        # Duration Math: Plating Deduction & Touch Calculations
        # -----------------------------------------------------
        if IS_HIGH_PRIORITY_STAT:
            touch_min = p.bld_touch_time_min
            touch_max = p.bld_touch_time_max
            touch_mean = (touch_min + touch_max) / 2.0
            pure_accession_time = random.triangular(touch_min, touch_max, touch_mean)
        else:
            touch_min = p.touch_time_min
            touch_max = p.touch_time_max
            touch_mean = (touch_min + touch_max) / 2.0
            pure_accession_time = random.triangular(touch_min, touch_max)

        yield env.timeout(pure_accession_time)
        tracker.log_event(spec_id, spec_type, "1d. Accessioning Completed", env.now)

    # ==========================================
    # 4. INSTRUMENT DROP-OFF & HANDOFF ROUTING
    # ==========================================
    is_blood = spec_type.upper().startswith("BCX") or spec_cfg.get("is_blood_culture", False)
    is_body_fluid = spec_type.upper().startswith("BODYFLUID") or spec_cfg.get("is_BodyFluid", False)

    if is_blood or is_body_fluid:
        tracker.log_event(spec_id, spec_type, "2A. Time to Load onto BC Instrument (Automated)", env.now)
        yield env.timeout(random.uniform(0.1, 0.5))
        tracker.log_event(spec_id, spec_type, "2A. Loaded into BC Instrument", env.now)
    else:
        # Route standard specimens asynchronously into FIFO plating store
        tracker.log_event(spec_id, spec_type, "2B. Queued in Routine Plating Store", env.now)
        item = {
            'spec_id': spec_id,
            'spec_type': spec_type,
            'spec_cfg': spec_cfg,
            'priority': spec_priority,
            'accession_completed_at': env.now
        }
        yield routine_plating_store.put(item)



def plating_worker_process(env, resources, routine_plating_store, priority_plating_store, tracker):
    """
    Worker process that prioritizes positive blood culture plating store items
    before pulling routine items on a First-In-First-Out (FIFO) basis.
    """
    while True:
        # 1. Check if there are priority positive blood cultures first
        if len(priority_plating_store.items) > 0:
            item = yield priority_plating_store.get()
            is_priority = True
        else:
            # 2. Otherwise, fetch standard routine specimens (FIFO order)
            get_priority = priority_plating_store.get()
            get_routine = routine_plating_store.get()
            
            # Wait for whichever store receives an item first
            results = yield env.any_of([get_priority, get_routine])
            
            if get_priority in results:
                item = results[get_priority]
                is_priority = True
                get_routine.cancel()
            else:
                item = results[get_routine]
                is_priority = False
                get_priority.cancel()

        spec_id = item['spec_id']
        spec_type = item['spec_type']
        spec_cfg = item['spec_cfg']
        spec_priority = item.get('priority', 5)
        done_event = item.get('done_event', None)

        tracker.log_event(spec_id, spec_type, "2B. Waiting for Plating Tech", env.now)

        # Select tech pool
        candidate_keys = ['tech_plating', 'tech_urine', 'tech_routine']
        valid_pools = [resources[k] for k in candidate_keys if k in resources and resources[k].capacity > 0]

        tech_pool = min(valid_pools, key=lambda r: len(r.queue) / r.capacity) if valid_pools else resources['tech_plating']

        with tech_pool.request(priority=spec_priority) as req:
            yield req
            
            log_prefix = "3A. Priority Blood Plating" if is_priority else "2C. Routine Plating"
            tracker.log_event(spec_id, spec_type, f"{log_prefix} Started", env.now)
            
            plating_time = spec_cfg.get("plating_touch_time", random.uniform(1.0, 3.0))
            yield env.timeout(plating_time)
            
            tracker.log_event(spec_id, spec_type, f"{log_prefix} Completed", env.now)

        # Unblock waiting main thread (for priority blood cultures)
        if done_event and not done_event.triggered:
            done_event.succeed()