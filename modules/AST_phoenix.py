import random
import numpy as np
import params_config.params_d2 as p

from modules.spec_proc_helpers import get_least_busy_tech

def process_phoenix_testing(env, spec_id, spec_type, resources, tracker, spec_priority, num_colonies):
    """Pathway D2: Reflex Phoenix Automated Antimicrobial Susceptibility Testing (AST)."""

    # -----------------------------------------------------------
    # 1. Route prep to whichever tech (routine vs general) has a shorter line
    # -----------------------------------------------------------
    chosen_tech = get_least_busy_tech(resources, "tech_routine", "tech_new")

    with chosen_tech.request(priority=spec_priority) as tech_req:
        yield tech_req
        tracker.log_event(spec_id, spec_type, "7a. Phoenix Prep Started", env.now)
        min_prep_t = p.min_PHENIXprep_time
        max_prep_t = p.max_PHENIXprep_time
        prep_time = random.uniform(min_prep_t, max_prep_t)
        # !!! DO NOT scale prep based on num_colonies. Instead this is just the average MALDI prep time in a typical day. As the tech normally does a batch run of maldi and doesn't set up 1 rxn at a time
        yield env.timeout(prep_time)
        # yield env.timeout(prep_time * num_colonies)

    # Tech is released here!

    # # -----------------------------------------------------------
            # # 2. Phoenix Instrument Incubation (4-hour max queue timeout)
            # # -----------------------------------------------------------
            # # - Setup AS Atomic Multi-Colony Loading (Specimen A before Specimen B)
            # phoenix_res = resources["phoenix_instrument"]
            # timeout_limit = p.phoenix_max_wait
            # print(f"DEBUG: spec={spec_id}, timeout_limit={timeout_limit}, current_time={env.now}")
            # # make sure priority passed as an integer
            # prio = int(spec_priority) if spec_priority is not None else 10
    
            # acquired_requests = []
            # timed_out = False
    
            # # 1. Acquire exclusive privilege to load the instrument
            # loader_lock = resources["phoenix_loader_lock"]
            # with loader_lock.request(priority=spec_priority) as lock_req:
            #     lock_res = yield lock_req | env.timeout(timeout_limit)
    
            #     if lock_req not in lock_res:
            #         # Timed out waiting for the loader lock itself
            #         timed_out = True
            #     else:
            #         # Specimen has exclusive loading access; claim all colony slots at once
            #         slot_reqs = [req_resource(phoenix_res, spec_priority) for _ in range(num_colonies)]
            #         all_slots_evt = env.all_of(slot_reqs)
                    
            #         # Check slot availability with remaining timeout
            #         res = yield all_slots_evt | env.timeout(timeout_limit)
    
            #         if all_slots_evt in res:
            #             acquired_requests = slot_reqs
            #         else:
            #             # Failed to get all slots within timeout; cancel pending requests
            #             for req in slot_reqs:
            #                 if req.triggered:
            #                     phoenix_res.release(req)
            #                 else:
            #                     try:
            #                         req.cancel()
            #                     except Exception:
            #                         pass
            #             timed_out = True
    
            # # ===========================================================
            # # 2. Incubation or Rollback Cleanup (OUTSIDE the lock)
            # # ===========================================================
            # if not timed_out and len(acquired_requests) == num_colonies:
            #     # --- SUCCESS: All colonies loaded, incubate concurrently ---
            #     tracker.log_event(spec_id, spec_type, "7b. Phoenix Incubation Started", env.now)
            #     phoenix_run_time = p.phoenix_run_time_hours * 60
            #     yield env.timeout(phoenix_run_time)
            #     tracker.log_event(spec_id, spec_type, "7c. Phoenix AST Completed", env.now)
    
            #     # Release all instrument slots after incubation completes
            #     for req in acquired_requests:
            #         phoenix_res.release(req)
            # else:
            #     # --- TIMEOUT: Log failure ---
            #     tracker.log_event(spec_id, spec_type, "Phoenix Slot Timeout - Deferred/Bypassed", env.now)
            #     print(f"⚠️ [TIMEOUT WARNING] t={env.now/60:.1f}h | {spec_id} timed out acquiring all {num_colonies} Phoenix slots!")
    
    # ===========================================================
    # Phoenix Instrument Incubation (Direct Request Pattern)
    # ===========================================================
    phoenix_res = resources["phoenix_instrument"]
    timeout_limit = p.phoenix_max_wait
    prio = int(spec_priority) if spec_priority is not None else 10

    # 1. Create slot requests
    slot_reqs = [phoenix_res.request(priority=prio) for _ in range(num_colonies)]

    # 2. Yield directly on the slot requests (or a single timeout)
    # In SimPy, yielding a list of requests waits for ALL of them to complete
    timeout_evt = env.timeout(timeout_limit)

    # Wait until ALL requests are granted OR the timeout fires
    results = yield env.all_of(slot_reqs) | timeout_evt

    # 3. VERIFY DIRECTLY IF ALL SLOTS WERE GRANTED
    # Do not rely on 'all_slots_evt in results'! Check each request event directly.
    all_granted = all(req.triggered for req in slot_reqs)

  
    if all_granted:
        # --- SUCCESS ---
        tracker.log_event(spec_id, spec_type, "7b. Phoenix Incubation Started", env.now)
        phoenix_run_time = p.phoenix_run_time_hours * 60
        
        try:
            yield env.timeout(phoenix_run_time)
            tracker.log_event(spec_id, spec_type, "7c. Phoenix AST Completed", env.now)
        finally:
            # Guaranteed release
            for req in slot_reqs:
                phoenix_res.release(req)
    else:
        # --- REAL TIMEOUT ---
        for req in slot_reqs:
            if req.triggered:
                phoenix_res.release(req)
            else:
                if hasattr(phoenix_res, 'get_queue') and req in phoenix_res.get_queue:
                    phoenix_res.get_queue.remove(req)
                try:
                    req.cancel()
                except Exception:
                    pass

        tracker.log_event(spec_id, spec_type, "Phoenix Slot Timeout - Deferred/Bypassed", env.now)
        print(f"⚠️ REAL TIMEOUT: t={env.now/60:.1f}h | {spec_id} waited full {timeout_limit}m without getting slots.")       

        # # -----------------------------------------------------------
        # # 3A. AST RUN (successful allocation) -----------------------
        # # -----------------------------------------------------------
        # if all_allocated in results:
        #     tracker.log_event(spec_id, spec_type, "7b. Phoenix Incubation Started", env.now)
        #     # phoenix_run_time = getattr(p, 'phoenix_run_time_hours', 4.0) * 60
        #     phoenix_run_time = p.phoenix_run_time_hours * 60
        #     yield env.timeout(phoenix_run_time)
        #     tracker.log_event(spec_id, spec_type, "7c. Phoenix AST Completed", env.now)
        #     # Release all slots after run completion
        #     for req in phoenix_req:
        #         phoenix_res.release(req)
        # else:
        # # -----------------------------------------------------------
        # # 3B. Timed out and ran out of Queue Space - AST Run Aborted -----------------------
        # # -----------------------------------------------------------
        #     tracker.log_event(spec_id, spec_type, "Phoenix Slot Timeout - Deferred/Bypassed", env.now)
        #     print(f"⚠️ [TIMEOUT WARNING] t={env.now/60:.1f}h | {spec_id} timed out waiting for Phoenix slot!")
        #     # Cancel all requests and release any partial slots acquired
        #     for req in phoenix_req:
        #         if req.triggered:
        #             # Slot was acquired before timeout - release it
        #             phoenix_res.release(req)
        #         else:
        #             # Slot is still waiting in queue - cancel it so it doesn't block others
        #             req.cancel()