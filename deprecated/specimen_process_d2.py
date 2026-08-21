import simpy
import random
import numpy as np
import pandas as pd

# Centralized parameters file which has the adjustable variables
import params_config.params as p

from modules.inventory import MediaInventory, inventory_manager_process
from modules.tracker import SpecimenTracker

# Dictionaries
from params_config.config import MEDIA_CONFIG, SPECIMEN_TYPES, SHIFT_STAFFING_PROFILE, Instrument_resources


# ==========================================
# Helper to pick the right tech resource based on specimen type
# ==========================================
# Based on the Specific specimen route to a specific tech
def get_tech_bench(spec_type, resources):
    if spec_type in ["BCx", "BodyFluid"]:
        return resources["tech_blood"]
    # elif spec_type in ["Urine"]:
    elif spec_type in ["Urine_Invasive", "Urine_NonInvasive"]:
        return resources["tech_urine"]
    elif spec_type in ["Tissue", "Tissue_genital", "Tissue_FNA", "Bone_Cx"]:
    #  To Add
    # elif spec_type in ["Resp_nonCF", "Resp_CF",
    #                     "Stool"]:
        return resources["tech_routine"]
    else:
        return resources["tech_general"]


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

# ==================================================================================
# Process Specimens
# ==================================================================================
def specimen_process(env, spec_id, spec_type, resources, inventory, tracker, time_plating_mean, time_incubation_hours, active_counter, plating_batcher):
    active_counter['count'] += 1

    # Track individual colony workups for this specimen
    workup_number = 0
    has_maldi_tested = False
    has_phoenix_tested = False

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
            tracker.log_event(spec_id, spec_type, "3. Plate Culture from BCx or Body Fluid Bottle", env.now)
            # Use getattr to prevent AttributeError if params misses a key
            # Fallback to 1.0
            std_time = p.plating_std_time
            min_time =p.min_plating_time
            plating_duration = max(min_time, random.normalvariate(time_plating_mean, std_time))
            workup_number += 1

            yield env.timeout(plating_duration)

        # 4. SUBCULTURE AGAR INCUBATION (~24 Hours) ----------
        with resources["incubator"].request() as inc_req:
            yield inc_req
            tracker.log_event(spec_id, spec_type, "3B. Incubate plate from BCx or BF Bottle", env.now)
            # ~24 hour agar plate incubation
            incubation_1_time_min = p.incubation_1_time_min * 60
            incubation_1_time_avg = p.incubation_1_time_min * 60
            subculture_inc_duration = max(incubation_1_time_min, random.normalvariate(incubation_1_time_avg, 120))
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
    if not has_maldi_tested and (random.random() < p.maldi_testing_percent):
        has_maldi_tested = True

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
                # phoenix_run_time = getattr(p, 'phoenix_run_time_hours', 4.0) * 60
                phoenix_run_time = p.phoenix_run_time_hours * 60
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