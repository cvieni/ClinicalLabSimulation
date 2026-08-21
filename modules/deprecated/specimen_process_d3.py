import simpy
import random
import numpy as np
import pandas as pd

from modules.inventory import MediaInventory, inventory_manager_process
from modules.tracker import SpecimenTracker
from modules.specimen_priority import get_specimen_priority


# Centralized parameters file which has the adjustable variables
import params_config.params_d2 as p
# Dictionaries
from params_config.config_d2 import MEDIA_CONFIG, SPECIMEN_TYPES, SHIFT_STAFFING_PROFILE, Instrument_resources, SPEC_PRIORITY_MAP


# ==========================================
# Helper to pick the right tech resource based on specimen type
# ==========================================
# Based on the Specific specimen route to a specific tech
def get_tech_bench(spec_type, resources):
    if spec_type in ["BCx", "BodyFluid"]:
        return resources["tech_blood"]
    elif spec_type in ["Urine"]:
        return resources["tech_urine"]
    elif spec_type in ["Tissue", "Tissue_FNA", "Tissue_genital", "Bone_Cx"]:
        return resources["tech_routine"]
    else:
        return resources["tech_new"]

def get_least_busy_tech(resources, primary_key="tech_routine", fallback_key="tech_new"):
    """Load-balances tech requests across available benches based on queue/capacity."""
    r_tech = resources.get(primary_key, resources[fallback_key])
    g_tech = resources[fallback_key]
    r_ratio = len(r_tech.queue) / max(1, r_tech.capacity)
    g_ratio = len(g_tech.queue) / max(1, g_tech.capacity)
    return r_tech if r_ratio <= g_ratio else g_tech

def req_resource(resource, priority=None):
    """Helper to request a resource safely whether it is a PriorityResource or standard Resource."""
    if isinstance(resource, simpy.PriorityResource) and priority is not None:
        return resource.request(priority=priority)
    return resource.request()


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
    tracker.log_event(spec_id, spec_type, "Media Allocation Failed - Aborted", env.now)
    return False

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
    # Calculate base priority from specimen config
    base_priority = get_specimen_priority(spec_cfg)
    
    # Calculate waiting delay (0 on initial arrival)
    time_waiting = env.now - arrival_time
    
    # Priority upgrades over time (e.g., improves by 1 rank level every 15 minutes of wait)
    # Clamp to minimum priority of 0 so it never goes negative
    # always keep blood culture, CSF, STATs, and bone culture as top priority, only apply dynamic priority to other tissue sampls
    if spec_priority > 4: 
        # spec_priority = max(1, base_priority - (time_waiting / 15.0))
        spec_priority = max(4, base_priority - (time_waiting / 15.0))

    # Request a general technician to receive, accession, and sort the specimen with semi-dynamic priority
    with req_resource(resources["tech_accession"], spec_priority) as req:
        yield req
        
        tracker.log_event(spec_id, spec_type, "1c. Accessioning & Central Processing Started", env.now)
        
        # Sample accessioning time (e.g., uniform distribution between min/max params)
        # 1. Fetch processing range from config or fallback to global params
        # proc_config = spec_cfg.get("accession_proc_time")
        proc_config = spec_cfg.get("accession_time_config", {})
        # mean_time, max_time = proc_config[0], proc_config[1]
        probs = proc_config.get("bin_probabilities")
        edges = proc_config.get("bin_edges")

        # 2. Sample processing duration
        # Looking closer at this -> our accession data is not evenly distributed and is rather a long tail distribution (high mode at ~1-5 min ~90% of data with 2% long tail to ~100 min)
        # accession_time = random.uniform(min_time, max_time)
        # accession_time = min(np.random.exponential(mean_time), max_time)

        # 2. Convert empirical mean_time into Log-Normal parameters
        # Assumes a right-skew shape factor sigma=0.7 (matches mode at ~2-3m, tail to max_time)
        # sigma = 0.7 
        # mu = np.log(mean_time) - (sigma**2 / 2)
        p_norm = np.array(probs, dtype=np.float64)
        p_norm /= p_norm.sum()
        bin_idx = np.random.choice(len(p_norm), p=p_norm)
        
        # 3. Draw duration and cap at your real-world max limit
        accession_time = np.random.uniform(edges[bin_idx], edges[bin_idx + 1])
        # accession_time = min(np.random.lognormal(mean=mu, sigma=sigma), max_time)

        yield env.timeout(accession_time)
        
        tracker.log_event(spec_id, spec_type, "1d. Accessioning & Central Processing Completed", env.now)


    # ==========================================
    # 2: INITIAL PROCESSING (Automated instrument vs. Direct plating)
    # 2A. Blood cultures + Body fluids (Automated instrument, ex. BACTEC)
    # ==========================================
    if is_blood_culture or is_body_fluid:
        tracker.log_event(spec_id, spec_type, "2a. Loaded into Automated Bactec Instrument", env.now)

        # Define Positivity probability (~10-15% of blood cultures are positive)
        if is_blood_culture is True:
            pos_rate = spec_cfg.get("positivity_rate", p.BCx_positivity)
        elif is_body_fluid is True:
            pos_rate = spec_cfg.get("positivity_rate", p.BdyFlid_positivity)

        is_positive = random.random() < pos_rate

        # -------------------------------------------
        # --- BACTEC MACHINE CAPACITY HELD HERE ---
        with resources["bc_instrument"].request() as bc_req:
            yield bc_req
            
            if is_positive:
                # if is_blood_culture:
                #     # Sample directly from Log-Normal distribution of ARUP's 2024 data 
                #     time_to_pos_hours = p.sample_time_to_positive("BloodCult")
                # else:
                #     time_to_pos_hours = p.sample_time_to_positive("BodyFluid")
                
                # Retrieve specimen specific TTP config
                cfg = spec_cfg.get("ttp_config")

                # 1. Randomly pick a bin based on the historical percentages
                selected_bin_idx = np.random.choice(len(cfg["bin_probabilities"]), p=cfg["bin_probabilities"])

                # 2. Uniformly sample a specific time within that chosen bin's boundaries
                low_edge = cfg["bin_edges"][selected_bin_idx]
                high_edge = cfg["bin_edges"][selected_bin_idx + 1]

                ttp_duration_hrs = np.random.uniform(low_edge, high_edge)

                yield env.timeout(ttp_duration_hrs * 60.0)
                tracker.log_event(spec_id, spec_type, "2b. BCx or BodyFluid Flagged POSITIVE", env.now)

                # yield env.timeout(time_to_pos_hours * 60)
                # tracker.log_event(spec_id, spec_type, "2b. BCx or BodyFluid Flagged POSITIVE", env.now)
            else:
                # Holds the instrument slot for 5 days (120 hours) then frees slot
                yield env.timeout(120 * 60)
                tracker.log_event(spec_id, spec_type, "2c. BC Flagged NEGATIVE", env.now)
                active_counter['count'] -= 1
                return  # Negative culture completes workflow
        # --- OUT OF MACHINE: Slot is now free for new samples ---
        # --------------------------------------------------------

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
                # Use getattr to prevent AttributeError if params misses a key
                std_time = p.plating_std_time
                min_time = p.min_plating_time
                max_plating_time = p.max_plating_time
                mean_plating_time = p.avg_plating_time
                # plating_duration = max(min_time, random.normalvariate(mean_plating_time, std_time))
                plating_duration = random.triangular(min_time, max_plating_time, mean_plating_time)

                workup_number += 1
                yield env.timeout(plating_duration)

        # 3. Hand off to Blood tech to set up biofire, read gram stain, and then move to incubator
        # 3A. BioFire + Gram Stain: Pre/In parallel Subculture
        # ==========================================
        tech_blood = resources.get("tech_blood")
        with req_resource(tech_blood, spec_priority) as req:
            yield req
            tracker.log_event(spec_id, spec_type, "3a-2. BioFire + Gram Stain Setup", env.now)
            # Stochastic duration for smear prep, staining, reading, and rapid tests
            min_bio =  p.min_biochem_screen_time
            max_bio = p.max_biochem_screen_time
            mean_bio = p.mean_biochem_screen_time
            # bio_time = random.uniform(min_bio, max_bio)
            bio_time = random.expovariate(1.0 / mean_bio)
            yield env.timeout(bio_time)


            tracker.log_event(spec_id, spec_type, "3a-3. BioFire + Gram Stain Completed", env.now)

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
        auto_plating_prob = getattr(p, "auto_plating_probability", 0.85)
        is_auto_candidate = is_stool_culture or is_urine_culture
        use_automated_system = random.random() < auto_plating_prob

        if is_auto_candidate and use_automated_system:
            # =========================================================
            # AUTOMATED SYSTEM PATHWAY (e.g., WASP: Most Stools or Urine)
            # =========================================================
            # 1. Extra 2 minutes during accessioning stage
            tracker.log_event(spec_id, spec_type, "Accessioning (Automated System Prep) Started", env.now)

            # 0-2 minutes of extra accessioning time to load onto WASP machine
            extra_accession_time = random.uniform(0.0, 2.0)
            yield env.timeout(extra_accession_time)

            # 2. Consume required media (No lab tech resource needed)
            media_requirements = spec_cfg.get("media_req", {})
            media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_requirements)

            if not media_allocated:
                active_counter["count"] -= 1
                return  # Abort specimen processing immediately

            # 3. Automated Plating Execution
            tracker.log_event(spec_id, spec_type, "3B-1. Sample loaded for Automated Plating Started", env.now)
            workup_number += 1

            # Simulate automated plating processing time (e.g., 1.5 - 3.0 min per sample)
            auto_plate_time = random.uniform(p.automatic_plating_time_min, p.automatic_plating_time_max)
            yield env.timeout(auto_plate_time)
            tracker.log_event(spec_id, spec_type, "3B-1. Automated Plating Completed", env.now)

        else:
        # ==========================================
        # STANDARD DIRECT-PLATING WORKFLOW: PERFORMED BY TECHNICIAN
        # ==========================================
            # Wait for batch of 10 or max 15 minutes before requesting plating bench
            yield plating_batcher.wait_for_batch()

            tech_plating = resources.get("tech_plating")
            with req_resource(tech_plating, spec_priority) as req:
                yield req
                media_requirements = spec_cfg.get("media_req", {})
                media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_requirements)
                if not media_allocated:
                    active_counter['count'] -= 1
                    return

                # =========================================
                # 3A. PLATING STAGE (Move specimen to plating bench)
                # =========================================
                with req_resource(resources["plating_bench"], spec_priority) as p_req:
                    yield p_req
                    tracker.log_event(spec_id, spec_type, "3B-2. Plating from PrimarySpecimen Started", env.now)

                    mu = p.avg_plating_time
                    sigma = p.plating_std_time
                    mintime = p.min_plating_time
                    max_plating_time = p.max_plating_time
                    mean_plating_time = p.avg_plating_time
                    # plating_duration = max(mintime, random.normalvariate(mu, sigma))
                    plating_duration = random.triangular(mintime, max_plating_time, mean_plating_time)
                    workup_number += 1
                    yield env.timeout(plating_duration)

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

        # Determine least busy tech between tech_routine and tech_general
        chosen_tech = get_least_busy_tech(resources, "tech_routine", "tech_new")
        maldi_res = resources["maldi_instrument"]

        # Hold the tech throughout prep AND machine run (tech is dedicated/waiting)
        with chosen_tech.request(priority=spec_priority) as tech_req:
            yield tech_req
            tracker.log_event(spec_id, spec_type, "6a. MALDI Target Spotting Started", env.now)
            
            # 1. Spotting / Prep
            min_maldi_prep_time = p.min_MALDI_prep_time
            max_maldi_prep_time = p.max_MALDI_prep_time
            maldi_prep_time = random.uniform(min_maldi_prep_time, max_maldi_prep_time)
            yield env.timeout(maldi_prep_time)
            tracker.log_event(spec_id, spec_type, "6b. MALDI Target Spotting Completed", env.now)

            # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
            # Is it more realistic for tech to sit and wait for Maldi to finish? or do they leave and do something else???
            # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
            # 2. Tech loads and waits for the MALDI-TOF instrument run
            with req_resource(maldi_res, spec_priority) as maldi_req:
                yield maldi_req
                tracker.log_event(spec_id, spec_type, "6c. MALDI Instrument Run Started", env.now)
                
                # Sample acquisition / laser fire / spectrum generation run time
                maldi_run_time = p.MALDI_runtime  # in minutes
                yield env.timeout(maldi_run_time)
                
                tracker.log_event(spec_id, spec_type, "6d. MALDI ID Completed", env.now)
        # Tech and MALDI instrument are both automatically released here

    # ==========================================
    # 6c. REFLEX TESTING: PHOENIX
    # ==========================================
    if not has_phoenix_tested and (random.random() < p.Phoenix_test_percent):
        # lock out repeat phoenix testing
        has_phoenix_tested = True
        
        # -----------------------------------------------------------
        # 1. Route prep to whichever tech (routine vs general) has a shorter line
        # -----------------------------------------------------------
        chosen_tech = get_least_busy_tech(resources, "tech_routine", "tech_new")

        with chosen_tech.request(priority=spec_priority) as tech_req:
            yield tech_req
            tracker.log_event(spec_id, spec_type, "7a. Phoenix Prep Started", env.now)
            prep_time = random.uniform(p.min_PHENIXprep_time, p.max_PHENIXprep_time)
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

    # ==========================================
    # 10. COMPLETE
    # ==========================================
    tracker.log_event(spec_id, spec_type, "10. Completed", env.now)
    active_counter['count'] -= 1