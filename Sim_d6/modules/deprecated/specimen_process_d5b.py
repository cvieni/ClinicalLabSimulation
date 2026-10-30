import simpy
import random
import numpy as np
import pandas as pd

from modules.inventory import MediaInventory, inventory_manager_process
from modules.tracker import SpecimenTracker
from modules.specimen_priority import get_specimen_priority

from modules.spec_proc_helpers import req_resource, get_tech_bench, get_least_busy_tech, consume_media_inventory
from modules.subpathways import process_automated_bactec, process_automated_wasp, process_manual_plating
from modules.MALDI_biochemicals import process_maldi_testing, process_BioFire, process_GramStain
from modules.AST_phoenix import process_phoenix_testing
from modules.accession_d2 import process_accessioning

# Centralized parameters file which has the adjustable variables
import params_config.params_d3 as p

# Dictionaries
from params_config.config_d2 import Instrument_resources
from params_config.media_config import MEDIA_CONFIG
from params_config.specimen_config_d2 import SPECIMEN_TYPES, resolve_specimen_tuning_value, resolve_time_range_override
from params_config.staffing_config import SHIFT_STAFFING_PROFILE


# ==================================================================================
# Process Specimens
# ==================================================================================
# The original specimen workflow mixed the blood-culture pathway, direct-plating route,
# and post-incubation review logic into one large function. This refactor splits those
# operations into explicit helper functions so each workflow is easier to reason about,
# test, and reuse while preserving the original simulation behavior.

def _finish_specimen(active_counter):
    """Centralize the active specimen decrement so each early-exit path behaves consistently."""
    active_counter['count'] = max(0, active_counter.get('count', 0) - 1)


def _get_specimen_flags(spec_type, spec_cfg):
    """Return the specimen type flags used by the blood-culture and direct-plating helpers."""
    return {
        "is_blood_culture": spec_type.upper().startswith("BCX") or spec_cfg.get("is_blood_culture", False),
        "is_body_fluid": spec_type.upper().startswith("BODYFLUID") or spec_cfg.get("is_BodyFluid", False),
        "is_stool_culture": spec_type.upper().startswith("STOOL") or spec_cfg.get("is_stool", False),
        "is_urine_culture": spec_type.upper().startswith("URINE") or spec_cfg.get("is_urine", False),
    }


def _sample_repeat_workup_profile(is_positive, is_polymicrobial, num_organisms):
    """Return the workup state for a positive specimen.

    The key logic is intentionally separated into explicit scenarios:
    1) positive + polymicrobial + multiple organisms require workup in parallel
    2) positive + polymicrobial + not all organisms are worked up
    3) positive + monomicrobial + additional workup still possible

    Legacy tuning variables are supported as aliases so the tuning sweep can target the
    same behavior through both the descriptive names and the historical config keys.
    """
    profile = {
        "is_positive": bool(is_positive),
        "is_polymicrobial": bool(is_polymicrobial),
        "num_organisms": max(1, int(num_organisms)),
        "needs_additional_workup": False,
        "workup_organism_count": 0,
    }

    if not profile["is_positive"]:
        return profile

    if not profile["is_polymicrobial"]:
        # monomicrobial_rate = getattr(p, "workup_required_rate", getattr(p, "monomicrobial_additional_workup_rate", 0.20))
        # profile["needs_additional_workup"] = random.random() < getattr(p, "monomicrobial_additional_workup_rate", monomicrobial_rate)
        # profile["workup_organism_count"] = 1 if profile["needs_additional_workup"] else 0
        # return profile

        # Direct link to monomicrobial sweep parameter
        rate = getattr(p, "monomicrobial_additional_workup_rate", 0.10)
        profile["needs_additional_workup"] = random.random() < rate
        profile["workup_organism_count"] = 1 if profile["needs_additional_workup"] else 0
        return profile

    # Polymicrobial work up ----------
    rate = getattr(p, "polymicrobial_workup_required_rate", 0.15)
    profile["needs_additional_workup"] = random.random() < rate
    if not profile["needs_additional_workup"]:
        return profile

    # polymicrobial_rate = getattr(p, "workup_required_rate", getattr(p, "polymicrobial_workup_required_rate", 0.45))
    # profile["needs_additional_workup"] = random.random() < getattr(p, "polymicrobial_workup_required_rate", polymicrobial_rate)
    # if not profile["needs_additional_workup"]:
    #     return profile

    all_organisms_worked_up = random.random() < getattr(p, "polymicrobial_all_organisms_worked_rate", 0.70)
    if all_organisms_worked_up:
        profile["workup_organism_count"] = profile["num_organisms"]
    else:
        max_workup_count = max(1, profile["num_organisms"] - 1)
        profile["workup_organism_count"] = random.randint(1, max_workup_count)

    return profile


def _perform_repeat_workup_batch(env, spec_id, spec_type, spec_cfg, resources, inventory, tracker, spec_priority, tech_key, workup_organism_count, is_blood_culture):
    """Subculture one additional workup batch. If multiple organisms are plated, they are handled together in a single parallel batch."""
    if workup_organism_count <= 0:
        return True

    media_requirements = {k: v * workup_organism_count for k, v in spec_cfg["media_req"].items()}
    media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_requirements)
    if not media_allocated:
        return False

    tech_resource = resources[tech_key]
    with req_resource(tech_resource, spec_priority) as req:
        yield req
        if workup_organism_count > 1:
            tracker.log_event(spec_id, spec_type, f"5a. Parallel repeat workup ({workup_organism_count} organisms)", env.now)
        else:
            tracker.log_event(spec_id, spec_type, "5a. Repeat workup (1 organism)", env.now)

        base_sub_time = random.uniform(p.min_subculture_time, p.max_subculture_time)
        colony_factor = 1.0 + (workup_organism_count - 1) * p.colony_workup_time_factor
        yield env.timeout(base_sub_time * colony_factor)

    with resources["incubator"].request() as inc_req:
        yield inc_req
        inc_label = "5b. Repeat workup incubation"
        tracker.log_event(spec_id, spec_type, inc_label, env.now)
        incubation_2_time_std = p.incubation_2_time_std * 60
        incubation_2_time_avg = p.incubation_2_time_avg * 60
        subculture_inc_duration = max(incubation_2_time_std, random.normalvariate(incubation_2_time_avg, 120))
        # DEBUG: Print once if parameters are actually changing
        # print(f"[INCUBATION] {spec_type} at sim_min={env.now:.1f} -> mean_hrs={mean_hrs}")
        yield env.timeout(subculture_inc_duration)

    return True


def _handle_blood_culture_path(env, spec_id, spec_type, spec_cfg, resources, inventory, tracker, active_counter, spec_priority, plating_store, priority_plating_store):
    """Process the blood culture / body fluid automation path, including subculture, incubation, and reflex tests."""
    is_blood_culture = spec_cfg.get("is_blood_culture", False) or spec_type.upper().startswith("BCX")
    is_body_fluid = spec_cfg.get("is_BodyFluid", False) or spec_type.upper().startswith("BODYFLUID")

    is_positive = yield from process_automated_bactec(env, spec_id, spec_type, spec_cfg, resources, tracker, is_blood_culture, is_body_fluid)

    if is_positive:
        tracker.log_event(spec_id, spec_type, "2A. Bactec Bottle Positive", env.now)
    else:
        tracker.log_event(spec_id, spec_type, "2A. Bactec Bottle Negative", env.now)
        _finish_specimen(active_counter)
        return False

    media_requirements = spec_cfg["media_req"]
    media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_requirements)
    if not media_allocated:
        tracker.log_event(spec_id, spec_type, "ABORTED_MEDIA_SHORTAGE", env.now)
        _finish_specimen(active_counter)
        return False

    plating_done_event = env.event()
    plating_job = {
        'spec_id': spec_id,
        'spec_type': spec_type,
        'spec_cfg': spec_cfg,
        'priority': spec_priority,
        'done_event': plating_done_event,
        'accession_completed_at': env.now,
    }

    yield priority_plating_store.put(plating_job)
    yield plating_done_event

    tech_blood = "tech_blood"
    yield from process_BioFire(env, spec_id, spec_type, resources, tracker, spec_priority, tech_blood)
    yield from process_GramStain(env, spec_id, spec_type, resources, tracker, spec_priority, tech_blood)

    with resources["incubator"].request() as inc_req:
        yield inc_req
        tracker.log_event(spec_id, spec_type, "3a-3. Incubate plate from BCx or BF Bottle", env.now)
        incubation_1_time_std_override = resolve_specimen_tuning_value(spec_cfg, "incubation_1_time_std", sim_minutes=env.now)
        incubation_1_time_avg_override = resolve_specimen_tuning_value(spec_cfg, "incubation_1_time_avg", sim_minutes=env.now)
        incubation_1_time_std = (p.incubation_1_time_std if incubation_1_time_std_override is None else float(incubation_1_time_std_override)) * 60
        incubation_1_time_avg = (p.incubation_1_time_avg if incubation_1_time_avg_override is None else float(incubation_1_time_avg_override)) * 60
        subculture_inc_duration = max(incubation_1_time_std, random.normalvariate(incubation_1_time_avg, 120))
        yield env.timeout(subculture_inc_duration)

    return True


def _handle_direct_plating_path(env, spec_id, spec_type, spec_cfg, resources, inventory, tracker, active_counter, spec_priority, plating_batcher, routine_plating_store, priority_plating_store):
    """Process the direct plating / routine specimen path, including stool and urine fallbacks."""
    is_stool_culture = spec_cfg.get("is_stool", False) or spec_type.upper().startswith("STOOL")
    is_urine_culture = spec_cfg.get("is_urine", False) or spec_type.upper().startswith("URINE")

    auto_plating_prob = p.auto_plating_probability
    is_auto_candidate = is_stool_culture or is_urine_culture
    use_automated_system = random.random() < auto_plating_prob

    if is_auto_candidate and use_automated_system:
        success = yield from process_automated_wasp(env, spec_id, spec_type, spec_cfg, inventory, tracker)
        workup_number = 1
    else:
        success = yield from process_manual_plating(env, spec_id, spec_type, spec_cfg, resources, inventory, tracker, spec_priority, plating_batcher)
        workup_number = 1

    if not success:
        _finish_specimen(active_counter)
        return False, 1

    if is_stool_culture:
        tracker.log_event(spec_id, spec_type, "GN Broth 6-Hour Incubation Started", env.now)
        gn_incubation_minutes = 6.0 * 60.0
        yield env.timeout(gn_incubation_minutes)
        tracker.log_event(spec_id, spec_type, "GN Broth 6-Hour Incubation Completed", env.now)

        tech_plating = resources.get("tech_plating")
        with req_resource(tech_plating, spec_priority) as req:
            yield req
            with req_resource(resources["plating_bench"], spec_priority) as p_req:
                yield p_req
                tracker.log_event(spec_id, spec_type, "GN Broth Subculture Plating Started", env.now)
                subculture_media = {"HE_Agar": 1}
                media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, subculture_media)
                if not media_allocated:
                    _finish_specimen(active_counter)
                    return False, workup_number
                manual_subculture_time = random.uniform(2.0, 4.0)
                workup_number += 1
                yield env.timeout(manual_subculture_time)
                tracker.log_event(spec_id, spec_type, "GN Broth Subculture Plating Completed", env.now)

    with resources["incubator"].request() as inc_req:
        # yield inc_req
        # tracker.log_event(spec_id, spec_type, "Incubation from Primary Specimen Started", env.now)
        # mu_incb_time_Other_override = resolve_specimen_tuning_value(spec_cfg, "avg_incubation_time_Other", sim_minutes=env.now)
        # std_incubation_time_Other_override = resolve_specimen_tuning_value(spec_cfg, "std_incubation_time_Other", sim_minutes=env.now)
        # mu_incb_time_Other = p.avg_incubation_time_Other if mu_incb_time_Other_override is None else float(mu_incb_time_Other_override)
        # std_incubation_time_Other = p.std_incubation_time_Other if std_incubation_time_Other_override is None else float(std_incubation_time_Other_override)

        # def get_lognormal_sample(mean, std):
        #     variance = std ** 2
        #     mu_val = np.log((mean ** 2) / np.sqrt(variance + mean ** 2))
        #     sigma_val = np.sqrt(np.log(1 + (variance / (mean ** 2))))
        #     return np.random.lognormal(mu_val, sigma_val)

        # incubation_duration = get_lognormal_sample(mu_incb_time_Other, std_incubation_time_Other)
        # yield env.timeout(incubation_duration)

        yield inc_req
        tracker.log_event(spec_id, spec_type, "Incubation from Primary Specimen Started", env.now)
        # # avg_override = resolve_specimen_tuning_value(spec_cfg, "avg_incubation_time_Other", sim_minutes=env.now)
        # # avg_override = resolve_specimen_tuning_value(spec_cfg, "avg_incubation_time_Other", sim_minutes=env.now) or resolve_specimen_tuning_value(spec_cfg, f"{spec_type}_{get_shift_label_for_time(sim_minutes=env.now)}_avg_incubation_time_Other", sim_minutes=env.now)
        
        # avg_override = resolve_specimen_tuning_value(spec_cfg, "avg_incubation_time_Other", sim_minutes=env.now) or getattr(p, f"specimen_override_{spec_type}_{'Evening' if (15 <= int((env.now % 1440) // 60) < 23) else ('Night' if (int((env.now % 1440) // 60) >= 23 or int((env.now % 1440) // 60) < 7) else 'Day')}_avg_incubation_time_Other", {}).get("value", None)
        # std_override = resolve_specimen_tuning_value(spec_cfg, "std_incubation_time_Other", sim_minutes=env.now)
        
        # mean_hrs = getattr(p, "avg_incubation_time_Other", 16.0) if avg_override is None else float(avg_override)
        # std_hrs = getattr(p, "std_incubation_time_Other", 6.0) if std_override is None else float(std_override)

        current_hour = int((env.now % 1440) // 60)
        current_shift = "Evening" if (15 <= current_hour < 23) else ("Night" if (current_hour >= 23 or current_hour < 7) else "Day")
        
        # Extract potential override (handles raw numeric, dict with 'value', or nested object)
        override_val = getattr(p, f"specimen_override_{spec_type}_{current_shift}_avg_incubation_time_Other", None)
        if isinstance(override_val, dict):
            avg_override = override_val.get("value", None)
        else:
            avg_override = override_val

        # Fallback to specimen config dictionary matrix lookup
        if avg_override is None:
            avg_override = resolve_specimen_tuning_value(spec_cfg, "avg_incubation_time_Other", sim_minutes=env.now)
            
        std_override = resolve_specimen_tuning_value(spec_cfg, "std_incubation_time_Other", sim_minutes=env.now)
        
        mean_hrs = float(avg_override) if avg_override is not None else float(getattr(p, "avg_incubation_time_Other", 16.0))
        std_hrs = float(std_override) if std_override is not None else float(getattr(p, "std_incubation_time_Other", 6.0))




        # DEBUG: Print once if parameters are actually changing
        print(f"[INCUBATION] {spec_type} at sim_min={env.now:.1f} -> mean_hrs={mean_hrs}")

        # Robust lognormal calculation
        mean_min = mean_hrs * 60.0
        std_min = max(30.0, std_hrs * 60.0)
        variance = std_min ** 2
        mu = np.log((mean_min ** 2) / np.sqrt(variance + mean_min ** 2))
        sigma = np.sqrt(np.log(1.0 + (variance / (mean_min ** 2))))
        
        duration = np.random.lognormal(mu, sigma)
        yield env.timeout(duration)

    return True, workup_number


# def specimen_process(env, spec_id, spec_type, resources, inventory, tracker, active_counter, plating_batcher):
def specimen_process(env, spec_id, spec_type, resources, inventory, tracker, active_counter, 
                     routine_plating_store, priority_plating_store, accession_incoming_store, 
                     plating_batcher):
    
    active_counter['count'] += 1
    # Record exact simulation arrival time
    arrival_time = env.now
    # Track individual colony workups for this specimen
    subculture_count = p.subculture_count # initialize
    num_colonies = 1
    has_maldi_tested = False
    has_phoenix_tested = False

    # 1. Define media_requirements and culture type FIRST before any checks
    spec_cfg = SPECIMEN_TYPES[spec_type]
    flags = _get_specimen_flags(spec_type, spec_cfg)
    is_blood_culture = flags["is_blood_culture"]
    is_body_fluid = flags["is_body_fluid"]
    is_stool_culture = flags["is_stool_culture"]
    is_urine_culture = flags["is_urine_culture"]

    # Initialize Priority at the start to prevent UnboundLocalError
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
    # -------------------------------------------------------------
    # Step A: Pre-Accession Delay / Holding Queue (NO TECH USED)
    # Model optional pre-sorting or hold-bin time before tech touch
    # -------------------------------------------------------------
    yield from process_accessioning(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, arrival_time, 
                                    routine_plating_store, accession_incoming_store)

    # ==========================================
    # 2: Direct to the primary subpathway
    # INITIAL PROCESSING (Automated instrument vs. Direct plating)
    # 2A. Blood cultures + Body fluids (Automated instrument, ex. BACTEC)
    # ==========================================
    if is_blood_culture or is_body_fluid:
        path_ok = yield from _handle_blood_culture_path(
            env, 
            spec_id, spec_type, spec_cfg,
            resources, inventory, tracker, active_counter,
            spec_priority,
            routine_plating_store, priority_plating_store,
        )
        if not path_ok:
            return

    # ==========================================
    # 2. PATHWAY B: STANDARD DIRECT-PLATING WORKFLOW (Urine, Wounds, Sputum, etc.) - 
    # ==========================================
    else:
        path_ok, workup_number = yield from _handle_direct_plating_path(
            env,
            spec_id, spec_type, spec_cfg,
            resources, inventory, tracker, active_counter,
            spec_priority,
            plating_batcher, routine_plating_store, priority_plating_store,
        )
        if not path_ok:
            return

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
        override_range = resolve_time_range_override(
            spec_cfg,
            "tech_review_range",
            sim_minutes=env.now,
            default_range=(p.min_tech_review_sub, p.max_tech_review_sub),
        )
        if override_range is None:
            min_time, max_time = p.min_tech_review_sub, p.max_tech_review_sub
        else:
            min_time, max_time = override_range
        yield env.timeout(random.uniform(min_time, max_time))

    # ------------------------------------------------------------------------
    # 4B. Stochastic chance of needing to reincubate for an addtl ~4-12 hours
    # -----------------------------------------------------------------------
    if random.random() < p.reincubation_percent:  # % needed re-incubation
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

        # --- LIS-STYLE WORKUP CALIBRATION ---
        # Scenario 1: positive specimen -> polymicrobial -> multiple organisms need workup
        # Scenario 2: positive specimen -> polymicrobial -> not all organisms are worked up
        # Scenario 3: positive specimen -> monomicrobial -> additional workup still possible
        positive_specimen = random.random() < p.positive_specimen_rate
        if not positive_specimen:
            tracker.log_event(spec_id, spec_type, "4a. Blood culture negative / no repeat workup", env.now)
            _finish_specimen(active_counter)
            return

        multi_organism = random.random() < p.multiple_organism_rate
        if not multi_organism:
            num_colonies = 1
        else:
            multipleColony_roll = random.random()
            p4 = p.four_colony_blood_percent
            p3 = p.third_colony_blood_percent
            p2 = p.second_colony_blood_percent
            if multipleColony_roll < p4:
                tracker.log_event(spec_id, spec_type, "4a. Bcx - Likely Mixed Flora (4+ organisms)", env.now)
                num_colonies = 4
            elif multipleColony_roll < (p4 + p3):
                num_colonies = 3
            elif multipleColony_roll < (p4 + p3 + p2):
                num_colonies = 2
            else:
                num_colonies = 1

        workup_profile = _sample_repeat_workup_profile(True, multi_organism, num_colonies)
        if not workup_profile["needs_additional_workup"]:
            tracker.log_event(spec_id, spec_type, "4a. Positive culture but no repeat workup required", env.now)
            num_colonies = max(1, num_colonies)
        else:
            workup_batch_size = max(1, workup_profile["workup_organism_count"])
            max_subcultures = p.max_subculture_limit_blood

            while subculture_count < max_subcultures:
                if subculture_count == 0:
                    chance = p.second_workup_percent
                elif subculture_count == 1:
                    chance = p.third_workup_percent
                else:
                    chance = p.additional_workup_percent

                if 1 < workup_batch_size < 4:
                    chance *= 1.5

                # Roll to see if another subculture workup is required
                additional_workup_chance = getattr(p, "additional_workup_percent", chance)
                chance = max(chance, additional_workup_chance)

                if random.random() < chance:
                    subculture_count += 1
                    workup_batch_size = max(1, workup_profile["workup_organism_count"])
                    batch_ok = yield from _perform_repeat_workup_batch(
                        env,
                        spec_id, spec_type, spec_cfg,
                        resources, inventory, tracker,
                        spec_priority,
                        "tech_blood",
                        workup_batch_size,
                        True,
                    )
                    if not batch_ok:
                        _finish_specimen(active_counter)
                        return
                else:
                    break

            if workup_batch_size > 1:
                tracker.log_event(spec_id, spec_type, f"4a. Multiple organisms worked up in parallel ({workup_batch_size})", env.now)

            # If repeat workup was not required, the specimen proceeds to the standard
            # final review and identification steps without an extra subculture loop.

    # ==========================================
    # Non-blood culture (urine, wound, tissue, stool)
    # ==========================================
    # Day 2 of specimen for non-blood culture specimens -- Secondary workup
    else:
        # Track how many times this specimen has undergone subculturing
        max_subcultures = p.max_subculture_limit_other

        # --- LIS-STYLE WORKUP CALIBRATION ---
        # Scenario 1: positive specimen -> polymicrobial -> multiple organisms require workup
        # Scenario 2: positive specimen -> polymicrobial -> not all organisms are worked up
        # Scenario 3: positive specimen -> monomicrobial -> additional workup still possible
        positive_specimen = random.random() < p.positive_specimen_rate
        if not positive_specimen:
            tracker.log_event(spec_id, spec_type, "4B. No significant growth / no repeat workup", env.now)
            _finish_specimen(active_counter)
            return

        multi_organism = random.random() < p.multiple_organism_rate
        if not multi_organism:
            num_colonies = 1
        else:
            multipleColony_roll = random.random()
            p4 = p.four_colony_percent
            p3 = p.third_colony_percent
            p2 = p.second_colony_percent
            if multipleColony_roll < p4:
                tracker.log_event(spec_id, spec_type, "4B. Other specimen - Likely Mixed Flora (4+ organisms)", env.now)
                num_colonies = 4
            elif multipleColony_roll < (p4 + p3):
                num_colonies = 3
            elif multipleColony_roll < (p4 + p3 + p2):
                num_colonies = 2
            else:
                num_colonies = 1

        workup_profile = _sample_repeat_workup_profile(True, multi_organism, num_colonies)
        if not workup_profile["needs_additional_workup"]:
            tracker.log_event(spec_id, spec_type, "4B. Positive culture but no repeat workup required", env.now)
            num_colonies = max(1, num_colonies)
        else:
            workup_batch_size = max(1, workup_profile["workup_organism_count"])
            while subculture_count < max_subcultures:
                if subculture_count == 0:
                    chance = p.second_workup_percent
                elif subculture_count == 1:
                    chance = p.third_workup_percent
                else:
                    chance = p.additional_workup_percent

                if 1 < workup_batch_size < 4:
                    chance *= 1.5

                tech_day2 = get_least_busy_tech(resources, "tech_routine", "tech_new")
                with req_resource(tech_day2, spec_priority) as req:
                    yield req
                    tracker.log_event(spec_id, spec_type, "4a. Rapid Biochemical Screening ", env.now)
                    min_bio = p.min_biochem_screen_time
                    max_bio = p.max_biochem_screen_time
                    biochem_time = random.uniform(min_bio, max_bio)
                    yield env.timeout(biochem_time * workup_batch_size)
                    tracker.log_event(spec_id, spec_type, "4a. Direct Biochemical Screening Completed", env.now)

                additional_workup_chance = getattr(p, "additional_workup_percent", chance)
                chance = max(chance, additional_workup_chance)

                if random.random() < chance:
                    subculture_count += 1
                    batch_ok = yield from _perform_repeat_workup_batch(
                        env,
                        spec_id,
                        spec_type,
                        spec_cfg,
                        resources,
                        inventory,
                        tracker,
                        spec_priority,
                        "tech_routine",
                        workup_batch_size,
                        False,
                    )
                    if not batch_ok:
                        _finish_specimen(active_counter)
                        return
                else:
                    break

            if workup_batch_size > 1:
                tracker.log_event(spec_id, spec_type, f"4B. Multiple organisms worked up in parallel ({workup_batch_size})", env.now)


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