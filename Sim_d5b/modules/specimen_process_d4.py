import simpy
import random
import numpy as np
import pandas as pd

from modules.inventory import MediaInventory, inventory_manager_process
from modules.tracker import SpecimenTracker
from modules.specimen_priority import get_specimen_priority

from modules.spec_proc_helpers import req_resource, get_tech_bench, get_least_busy_tech, consume_media_inventory
from modules.subpathways import process_accessioning, process_automated_bactec, process_automated_wasp, process_manual_plating
from modules.MALDI_biochemicals import process_maldi_testing, process_BioFire, process_GramStain
from modules.AST_phoenix import process_phoenix_testing

# Centralized parameters file which has the adjustable variables
import params_config.params_d2 as p
# Dictionaries
from params_config.config_d2 import MEDIA_CONFIG, SPECIMEN_TYPES, SHIFT_STAFFING_PROFILE, Instrument_resources, SPEC_PRIORITY_MAP



# ==================================================================================
# Process Specimens
# ==================================================================================
def specimen_process(env, spec_id, spec_type, resources, inventory, tracker, active_counter, plating_batcher):
    active_counter['count'] += 1

    # Record exact simulation arrival time
    arrival_time = env.now

    # Track individual colony workups for this specimen
    workup_number = 0
    subculture_count = p.subculture_count # initialize
    num_colonies = 1
    # multiple_colony_selector = 0
    has_maldi_tested = False
    has_phoenix_tested = False

    # 1. Define media_requirements and culture type FIRST before any checks
    spec_cfg = SPECIMEN_TYPES[spec_type]
    is_blood_culture = spec_type.upper().startswith("BCX") or spec_cfg.get("is_blood_culture", False)
    is_body_fluid = spec_type.upper().startswith("BodyFluid") or spec_cfg.get("is_BodyFluid", False)
    is_stool_culture = spec_type.upper().startswith("Stool") or spec_cfg.get("is_stool", False)
    is_urine_culture = spec_type.upper().startswith("Urine") or spec_cfg.get("is_urine", False)


    # 1. Initialize Priority at the start to prevent UnboundLocalError
    spec_priority = get_specimen_priority(spec_cfg)

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
    # 1c. CENTRAL PROCESSING & ACCESSIONING
    # ==========================================
    yield from process_accessioning(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, arrival_time)

    # ==========================================
    # 2: Direct to the primary subpathway
    # INITIAL PROCESSING (Automated instrument vs. Direct plating)
    # 2A. Blood cultures + Body fluids (Automated instrument, ex. BACTEC)
    # ==========================================
    if is_blood_culture or is_body_fluid:
        # Automated Bactec/Instrument pathway
        is_positive = yield from process_automated_bactec(env, spec_id, spec_type, spec_cfg, resources, tracker, 
                                                          is_blood_culture, is_body_fluid)

        if not is_positive:
            active_counter['count'] -= 1
            return

        # ==========================================
        # Step 3: Positive Blood Culture --------------
        # ==========================================
 
        # ==========================================
        # 3B. PLATING STAGE (First work up from bottle)
        # =========================================
        # If positive, proceed to downstream subculturing & incubation
        # --- NOW ALLOCATE AGAR PLATES FOR SUBCULTURE ---
        media_requirements = spec_cfg["media_req"]
        media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_requirements)
        if not media_allocated:
            active_counter['count'] -= 1
            return  # Abort specimen processing immediately
            
        tech_blood_plating = resources.get("tech_plating")
        with req_resource(tech_blood_plating, spec_priority) as req:
            yield req
            # --- HIGH PRIORITY (STAT) PLATING ---
            # Move specimen to plating bench for set up
            with req_resource(resources["plating_bench"], spec_priority) as p_req:
                yield p_req
                tracker.log_event(spec_id, spec_type, "3A. Plate Culture from BCx or Body Fluid Bottle", env.now)
                # std_time = p.plating_std_time
                min_time = p.min_plating_time
                # plating_duration = max(min_time, random.normalvariate(mean_plating_time, std_time))
                max_plating_time = p.max_plating_time
                mean_plating_time = p.avg_plating_time
                plating_duration = random.triangular(min_time, max_plating_time, mean_plating_time)

                workup_number += 1
                yield env.timeout(plating_duration)

        # ==========================================
        # 3. Hand off to Blood tech to set up biofire, read gram stain, and then move to incubator
        # 3A. BioFire + Gram Stain: Pre/In parallel Subculture
        # ==========================================
        tech_blood = resources.get("tech_blood")
        
        yield from process_BioFire(env, spec_id, spec_type, resources, tracker, spec_priority, tech_blood)
        yield from process_GramStain(env, spec_id, spec_type, resources, tracker, spec_priority, tech_blood)

        # ==========================================
        # Set Aside for INCUBATION (~24 Hours) ----------
        with resources["incubator"].request() as inc_req:
            yield inc_req
            tracker.log_event(spec_id, spec_type, "3a-3. Incubate plate from BCx or BF Bottle", env.now)
            # ~24 hour agar plate incubation
            incubation_1_time_std = p.incubation_1_time_std * 60
            incubation_1_time_avg = p.incubation_1_time_avg * 60
            subculture_inc_duration = max(incubation_1_time_std, random.normalvariate(incubation_1_time_avg, 120))
            yield env.timeout(subculture_inc_duration)

    # ==========================================
    # 2. PATHWAY B: STANDARD DIRECT-PLATING WORKFLOW (Urine, Wounds, Sputum, etc.) - 
    # ==========================================
    else:
        # Define probability of automated plating (e.g., 85% automated, 15% manual fallback)
        # This can also be pulled from spec_cfg.get("auto_plating_prob", 0.85)
        auto_plating_prob = p.auto_plating_probability
        is_auto_candidate = is_stool_culture or is_urine_culture
        use_automated_system = random.random() < auto_plating_prob

        if is_auto_candidate and use_automated_system:
            success = yield from process_automated_wasp(env, spec_id, spec_type, spec_cfg, inventory, tracker)
            workup_number =+ 1
        else:
            success = yield from process_manual_plating(env, spec_id, spec_type, spec_cfg, resources, inventory, tracker, spec_priority, plating_batcher)
            workup_number =+ 1

        # Handle early exit if media allocation failed inside WASP or Manual plating
        if not success:
            active_counter['count'] -= 1
            return

        # ---------------------------------------------------------
        # Common SUB- WORKFLOW: STOOL samples gets GN BROTH INCUBATION & THEN SUBCULTURE
        #  Executes for both WASP/Auto and Manual plating paths
        # ---------------------------------------------------------
        if is_stool_culture:
            tracker.log_event(spec_id, spec_type, "GN Broth 6-Hour Incubation Started", env.now)

            # Passive incubation delay for 6 hours (360 minutes) - NO TECH HELD
            gn_incubation_minutes = 6.0 * 60.0  # 360.0 mins
            yield env.timeout(gn_incubation_minutes)
            tracker.log_event(spec_id, spec_type, "GN Broth 6-Hour Incubation Completed", env.now)

            # 2. Request BOTH technician and plating bench for secondary subculture
            tech_plating = resources.get("tech_plating")
            with req_resource(tech_plating, spec_priority) as req:
                yield req
                with req_resource(resources["plating_bench"], spec_priority) as p_req:
                    yield p_req
                    tracker.log_event(spec_id, spec_type, "GN Broth Subculture Plating Started", env.now)
                    
                    # Consume secondary subculture media plate
                    subculture_media = {"HE_Agar": 1} 
                    media_allocated = yield from consume_media_inventory(
                        env, inventory, tracker, spec_id, spec_type, subculture_media
                    )
                    
                    if not media_allocated:
                        active_counter["count"] -= 1
                        return

                    # Manual subculture time (e.g., 2 to 4 minutes)
                    manual_subculture_time = random.uniform(2.0, 4.0)
                    workup_number += 1
                    yield env.timeout(manual_subculture_time)
                    
                    tracker.log_event(spec_id, spec_type, "GN Broth Subculture Plating Completed", env.now)


        # ==========================================
        # 3B. INCUBATION STAGE
        # ==========================================
        # --- PRIMARY INCUBATION (Shared by both WASP and Manual Direct-Plating of Stool or Urine) ---
        with resources["incubator"].request() as inc_req:
            yield inc_req
            tracker.log_event(spec_id, spec_type, "3B-2. Incubation from Primary Specimen Started", env.now)
            mu_incb_time_Other = p.avg_incubation_time_Other
            std_incubation_time_Other = p.std_incubation_time_Other
            low_thresh = max(12.0 * 60.0, mu_incb_time_Other - 2 * std_incubation_time_Other)

            def get_lognormal_sample(mean, std):
                variance = std ** 2
                mu_val = np.log((mean ** 2) / np.sqrt(variance + mean ** 2))
                sigma_val = np.sqrt(np.log(1 + (variance / (mean ** 2))))
                return np.random.lognormal(mu_val, sigma_val)
            
            incubation_duration = get_lognormal_sample(mu_incb_time_Other, std_incubation_time_Other)
            # incubation_duration = max(low_thresh, random.normalvariate(mu_incb_time_Other, std_incubation_time_Other))

            yield env.timeout(incubation_duration)

    # =============================================================================
    # ==========================================
    # 4. Unified Tech REVIEW STAGE (after first incubation)
    # ==========================================
    # Initial Tech Review (Applies equally to all incubated agar plates)
    # Two ways to model this -> 
    # 1. Apply a specific amount of time per Specimen
    # 2. Apply a specific amount of time per plate
    # Added a dictionary definition for each specimen type as Urine likely is faster per plate, then tissue/wound
    tech_resource = get_tech_bench(spec_type, resources)

    with req_resource(tech_resource, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, "4. Tech Review Started (Plate - Day 2)", env.now)
        min_time, max_time = spec_cfg.get("tech_review_range", (p.min_tech_review_sub, p.max_tech_review_sub))
        yield env.timeout(random.uniform(min_time, max_time))

    # ------------------------------------------------------------------------
    # 4B. Stochastic chance of needing to reincubate for an addtl ~4-12 hours
    # -----------------------------------------------------------------------
    if random.random() < p.reincubation_percent:  # 8% need re-incubation
        with resources["incubator"].request() as reinc_req:
            yield reinc_req
            tracker.log_event(spec_id, spec_type, "4a. Extended Re-Incubation", env.now)
            min_reinc = p.min_reincubate_time * 60
            max_reinc = p.max_reincubate_time * 60
            yield env.timeout(random.uniform(min_reinc, max_reinc))

    # ==========================================
    # 6a. REFLEX TESTING & SUB-CULTURE
    # ==========================================
    # Blood culture or body fluids ----------
    if is_blood_culture:
        # STEP 1: Evaluate Subculture
        # Blood cultures go back to the blood culture bench
        with req_resource(resources["tech_blood"], spec_priority) as req:
            yield req
            tracker.log_event(spec_id, spec_type, "4a. Evaluate Blood Subculture (Plate - Day 2)", env.now)
            # Tech subcultures/streaks mixed/dirty culture to a fresh isolation plate (e.g., 3-5 mins)
            yield env.timeout(random.uniform(p.min_subcultEval_time, p.max_subcultEval_time))

        # --- MULTI-COLONY CHECK APPLIED HERE (2nd Plating Round & Onward) ---
            multipleColony_roll = random.random()
            p4 = p.four_colony_blood_percent
            p3 = p.third_colony_blood_percent
            p2 = p.second_colony_blood_percent
            # Include so that you only roll for multiple colonies 1x after the first incubation
            if multipleColony_roll < p4:
                tracker.log_event(spec_id, spec_type, "4a. Bcx - Likely Mixed Flora", env.now)
                active_counter['count'] -= 1
                return  # Exit workflow immediately without doing workup or downstream tests
            elif multipleColony_roll < (p4 + p3):
                num_colonies = 3
            elif multipleColony_roll < (p4 + p3 + p2):
                num_colonies = 2
            else:
                num_colonies = 1
        # -----------------------------------------------------------
        # -----------------------------------------------------------

        # -----------------------------------------------------------
        # ----------------------------------------------------------------------------------
        # Now Tech Evaluates if colonies require extra subculturing (e.g., 2nd or 3rd workup)
        # --- SUB-CULTURE / SECOND ROUND PLATING LOOP ---
        max_subcultures = p.max_subculture_limit_blood

        while subculture_count < max_subcultures:
            if subculture_count == 0:
                chance = p.second_workup_percent
            elif subculture_count == 1:
                chance = p.third_workup_percent
            else:
                chance = p.additional_workup_percent

            # Increase chance of additional workup if multiple colonies are present
            if 1 < num_colonies < 4:
                chance *= 1.5

            # Roll to see if another subculture workup is required
            if random.random() < chance:
                subculture_count += 1

                # Extra media required per isolated colony
                sub_media_req = spec_cfg["media_req"]
                extra_media_allocated = yield from consume_media_inventory(
                    env, inventory, tracker, spec_id, spec_type, 
                    {m: q * num_colonies for m, q in sub_media_req.items()}
                )
                if not extra_media_allocated:
                    active_counter['count'] -= 1
                    return

                # Tech labor to subculture isolated colonies
                with req_resource(resources["tech_blood"], spec_priority) as req:
                    yield req
                    stage_label = f"5a. Sub Pure Colony (Plate - Day {1+subculture_count})"
                    tracker.log_event(spec_id, spec_type, stage_label, env.now)
                    
                    base_sub_time = random.uniform(p.min_subculture_time, p.max_subculture_time)
                    colony_factor = 1.0 + (num_colonies - 1) * p.colony_workup_time_factor
                    yield env.timeout(base_sub_time * colony_factor)
                
                # Incubation for subculture agar plates
                with resources["incubator"].request() as inc_req:
                    yield inc_req
                    inc_label = f"5b. Sub Pure Colony #{subculture_count} Incubation"
                    tracker.log_event(spec_id, spec_type, inc_label, env.now)

                    incubation_2_time_std = p.incubation_2_time_std * 60
                    incubation_2_time_avg = p.incubation_2_time_avg * 60
                    subculture_inc_duration = max(incubation_2_time_std, random.normalvariate(incubation_2_time_avg, 120))
                    yield env.timeout(subculture_inc_duration)

            else: 
                # Complete work up
                # in line wiht for while subculture_count < max_subcultures:
                break

    # ==========================================
    # Non-blood culture (urine, wound, tissue, stool)
    # ==========================================
    # Day 2 of specimen for non-blood culture specimens -- Secondary workup
    else:
        # Track how many times this specimen has undergone subculturing
        max_subcultures = p.max_subculture_limit_other

        # -----------------------------------------------------------
        # --- MULTI-COLONY CHECK APPLIED HERE (2nd Plating Round & Onward) ---
        multipleColony_roll = random.random()
        p4 = p.four_colony_percent
        p3 = p.third_colony_percent
        p2 = p.second_colony_percent
        if multipleColony_roll < p4:
            tracker.log_event(spec_id, spec_type, "4B. Other specimen - Likely Mixed Flora", env.now)
            active_counter['count'] -= 1
            return  # Exit workflow immediately without doing workup or downstream tests
        elif multipleColony_roll < (p4 + p3):
            num_colonies = 3
        elif multipleColony_roll < (p4 + p3 + p2):
            num_colonies = 2
        else:
            num_colonies = 1
        # -----------------------------------------------------------
        # -----------------------------------------------------------

        while subculture_count < max_subcultures:
            # Determine probability based on current subculture iteration
            if subculture_count == 0:
                chance = p.second_workup_percent  # First time evaluating a second workup
            elif subculture_count == 1:
                chance = p.third_workup_percent  # Third workup probability
            else:
                chance = p.additional_workup_percent # Optional fallback for 4th+

            # Increase chance of additional workup if multiple colonies are present
            if 1 < num_colonies < 4:
                chance *= 1.5

            # ==========================================
            # Rapid Biochemicals + Gram Stain: Pre/In parallel Subculture
            # ==========================================
            # Direct Gram stain / rapid biochemical screening (e.g., Coagulase, Catalase, Rapid PYR)
            tech_day2 = get_least_busy_tech(resources, "tech_routine", "tech_new")
            
            with req_resource(tech_day2, spec_priority) as req:
                yield req
                tracker.log_event(spec_id, spec_type, "4a. Rapid Biochemical Screening ", env.now)
                
                # Stochastic duration for smear prep, staining, reading, and rapid tests
                min_bio = p.min_biochem_screen_time
                max_bio = p.max_biochem_screen_time
                biochem_time = random.uniform(min_bio, max_bio)
                yield env.timeout(biochem_time * num_colonies)
                tracker.log_event(spec_id, spec_type, "4a. Direct Biochemical Screening Completed", env.now)

            # Roll to see if another subculture workup is required
            if random.random() < chance:
                subculture_count += 1

                # Extra media required per isolated colony
                sub_media_req = spec_cfg["media_req"]
                extra_media_allocated = yield from consume_media_inventory(
                    env, inventory, tracker, spec_id, spec_type, 
                    {m: q * num_colonies for m, q in sub_media_req.items()}
                )
                if not extra_media_allocated:
                    active_counter['count'] -= 1
                    return
                    
                # STEP 1: Subculture Pure Colony
                with req_resource(resources["tech_routine"], spec_priority) as req:
                    yield req
                    stage_label = f"4a. Sub Pure Colony #{subculture_count} Started ({num_colonies} colonies)"
                    tracker.log_event(spec_id, spec_type, stage_label, env.now)

                    # Tech subcultures/streaks mixed/dirty culture to a fresh isolation plate
                    base_sub_time = random.uniform(p.min_subculture_time, p.max_subculture_time)
                    colony_factor = 1.0 + (num_colonies - 1) * p.colony_workup_time_factor
                    plating_dur = base_sub_time * colony_factor
                    yield env.timeout(plating_dur)
                
                # Overnight incubation for the pure colony subculture (18-24 hours)
                with resources["incubator"].request() as inc_req:
                    yield inc_req
                    inc_label = f"4b. Sub Pure Colony #{subculture_count} Incubation"
                    tracker.log_event(spec_id, spec_type, inc_label, env.now)
                    incubation_2_time_std = p.incubation_2_time_std * 60
                    incubation_2_time_avg = p.incubation_2_time_avg * 60
                    subculture_inc_duration = max(incubation_2_time_std, random.normalvariate(incubation_2_time_avg, 120))
                    yield env.timeout(subculture_inc_duration)

            else:
                # If no further workup is needed, break out of the loop
                break


    # ==========================================
    # 6b. REFLEX TESTING: MALDI-TOF IDENTIFICATION
    # ==========================================
    if not has_maldi_tested and  (random.random() < p.maldi_testing_percent):
        # lock out colony from repeat testing
        has_maldi_tested = True

        # Run MALDI subprocess
        yield from process_maldi_testing(env, spec_id, spec_type, resources, tracker, spec_priority)
        

    # ==========================================
    # 6c. REFLEX TESTING: PHOENIX
    # ==========================================
    if not has_phoenix_tested and (random.random() < p.Phoenix_test_percent):
        # lock out repeat phoenix testing
        has_phoenix_tested = True

        yield from process_phoenix_testing(env, spec_id, spec_type, resources, tracker, spec_priority, num_colonies)

    # ==========================================
    # 10. COMPLETE
    # ==========================================
    tracker.log_event(spec_id, spec_type, "10. Completed", env.now)
    active_counter['count'] -= 1