# modules/subpathways.py
import random
import numpy as np
import params_config.params_d3 as p
from modules.spec_proc_helpers import req_resource, consume_media_inventory, get_least_busy_tech
from modules.specimen_priority import get_specimen_priority
from modules.spec_proc_helpers import get_least_busy_tech_accession
from params_config import event_name as EV

DEBUG_BOTTLENECKS = False   # per-specimen prints; leave off for Monte Carlo



# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------


def process_automated_bactec(env, spec_id, spec_type, spec_cfg, resources, tracker,
                             is_blood_culture, is_body_fluid):
    """Pathway A1: BCx / BodyFluid Bactec Instrument processing."""
    # Define Positivity probability (~10-15% of blood cultures are positive)
    if is_blood_culture is True:
        pos_rate = spec_cfg.get("positivity_rate", p.BCx_positivity)
    elif is_body_fluid is True:
        pos_rate = spec_cfg.get("positivity_rate", p.BdyFlid_positivity)
    else:
        raise ValueError(f"process_automated_bactec called for non-bottle specimen {spec_id} ({spec_type})")
        
    is_positive = random.random() < pos_rate

    # -------------------------------------------
    # --- BACTEC MACHINE CAPACITY HELD HERE ---
    # Previously "Loaded into Automated Bactec Instrument" was logged BEFORE the slot was requested, so a
    # specimen queueing for a full instrument looked loaded. Now: wait event, then loaded event after the grant.
    tracker.log_event(spec_id, spec_type, EV.BACTEC_SLOT_WAIT, env.now)
    with resources["bc_instrument"].request() as bc_req:
        yield bc_req
        tracker.log_event(spec_id, spec_type, EV.BACTEC_LOADED, env.now)

        if is_positive:    
            # Retrieve specimen specific Time To Positive (TTP) config
            cfg = spec_cfg.get("ttp_config")

            # -------------------------------------------------------------
            # LOG-NORMAL TTP FOR BLOOD CULTURES (BCx)
            # -------------------------------------------------------------
            if is_blood_culture:
                mu = cfg["lognormal_mu"]
                sigma = cfg["lognormal_sigma"]
                
                # Sample incubation hours from log-normal distribution
                ttp_duration_hrs = random.lognormvariate(mu, sigma)
                
                # Apply bounds if present in config
                if "min_accession_min" in cfg and "max_accession_min" in cfg:
                    min_hrs = cfg["min_accession_min"] / 60.0
                    max_hrs = cfg["max_accession_min"] / 60.0
                    ttp_duration_hrs = max(min_hrs, min(ttp_duration_hrs, max_hrs))

            # -------------------------------------------------------------
            # DIRECT DISCRETE BINNING FOR BODY FLUIDS
            # -------------------------------------------------------------
            elif is_body_fluid:
                # 1. Randomly pick a bin based on the historical percentages
                probs = cfg["bin_probabilities"]
                edges = cfg["bin_edges"]
                selected_bin_idx = np.random.choice(len(probs), p=probs)

                # 2. Uniformly sample a specific time within that chosen bin's boundaries
                low_edge = edges[selected_bin_idx]
                high_edge = edges[selected_bin_idx + 1]
                ttp_duration_hrs = np.random.uniform(low_edge, high_edge)
                # ttp = np.random.uniform(cfg["bin_edges"][selected_bin], cfg["bin_edges"][selected_bin + 1])

            yield env.timeout(ttp_duration_hrs * 60.0)
            tracker.log_event(spec_id, spec_type, EV.BC_FLAGGED_POSITIVE, env.now)
            return True  # Proceed to subculturing
        
        else:
            # Holds the instrument slot for 5 days (120 hours) then frees slot
            yield env.timeout(120 * 60)
            tracker.log_event(spec_id, spec_type, EV.BC_FLAGGED_NEGATIVE, env.now)
            return False  # Negative culture completes workflow
        # --- OUT OF MACHINE: Slot is now free for new samples ---
        # --------------------------------------------------------


# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
         

def process_automated_wasp(env, spec_id, spec_type, spec_cfg, inventory, tracker):
    """Pathway B1: WASP Automated Plating."""
    # =========================================================
    # AUTOMATED SYSTEM PATHWAY (e.g., WASP: Most Stools or Urine)
    # =========================================================
    # 1. Extra 2 minutes during accessioning stage
    tracker.log_event(spec_id, spec_type, EV.WASP_PREP_START, env.now)

    # 0-2 minutes of extra accessioning time to load onto WASP machine
    max_wasp_load_time = p.wasp_load_time_max
    # Take 15 sec to 1 min to load onto wasp
    extra_accession_time = random.uniform(0.25, max_wasp_load_time)
    yield env.timeout(extra_accession_time)

    # 2. Consume required media (No lab tech resource needed)
    media_requirements = spec_cfg.get("media_req", {})
    media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_requirements)

    if not media_allocated:
        return False # Abort specimen processing immediately

    # 3. Automated Plating Execution
    tracker.log_event(spec_id, spec_type, EV.AUTOMATED_PLATING_STARTED, env.now)

    # Simulate automated plating processing time (e.g., 1.5 - 3.0 min per sample)
    auto_plate_time = random.uniform(p.automatic_plating_time_min, p.automatic_plating_time_max)
    yield env.timeout(auto_plate_time)
    tracker.log_event(spec_id, spec_type, EV.AUTOMATED_PLATING_DONE, env.now)

    return True


# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
         

def process_manual_plating(env, spec_id, spec_type, spec_cfg, resources, inventory, tracker, spec_priority, plating_batcher):
    """Pathway B2: Manual Direct Plating."""
    # ==========================================
    # STANDARD DIRECT-PLATING WORKFLOW: PERFORMED BY TECHNICIAN
    # ==========================================
    # Wait for batch of 10 or max 15 minutes before requesting plating bench
    yield plating_batcher.wait_for_batch()

    # Media is taken BEFORE a tech/bench is requested. It used to be consumed inside `with req_resource(plating_tech)`,
    # so a specimen waiting out a media stockout kept a plating tech seat the whole time, which starves the
    # bench for every other specimen (your 10-day funnel: 5,624 stockout delays, only 108 manual plates started).
    media_requirements = spec_cfg.get("media_req", {})
    media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_requirements)
    if not media_allocated:
        return False

    # Dynamic allocation: Grab whichever bench (Plating vs Accession) is less backed up
    plating_tech = get_least_busy_tech_accession(resources, primary_key="tech_plating", fallback_key="tech_accession")
    with req_resource(plating_tech, spec_priority) as req:
        yield req

        # =========================================
        # 3A. PLATING STAGE (Move specimen to plating bench)
        # =========================================
        with req_resource(resources["plating_bench"], spec_priority) as p_req:
            yield p_req
            tracker.log_event(spec_id, spec_type, EV.MANUAL_PLATING_STARTED, env.now)

            plating_duration = random.triangular(p.min_plating_time, p.max_plating_time, p.avg_plating_time)
            if DEBUG_BOTTLENECKS:
                print(f"DEBUG_BOTTLENECK [ManualPlating] spec_id={spec_id} queue_len={len(plating_tech.queue)} "
                      f"bench_queue={len(resources['plating_bench'].queue)} plating_duration_min={plating_duration:.2f}")
            yield env.timeout(plating_duration)

    return True


# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
      
def process_tech_review(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority):
    """Pathway C: Unified Tech Review (Day 2) + Optional Re-incubation."""
    tech_resource = get_tech_bench(spec_type, resources)

    with req_resource(tech_resource, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, EV.TECH_REVIEW, env.now)
        min_time, max_time = spec_cfg.get("tech_review_range", (p.min_tech_review_sub, p.max_tech_review_sub))
        review_duration = random.uniform(min_time, max_time)
        if DEBUG_BOTTLENECKS:
            print(f"DEBUG_BOTTLENECK [TechReview] spec_id={spec_id} tech={tech_resource} queue_len={len(tech_resource.queue)} review_duration_min={review_duration:.2f}")
        yield env.timeout(review_duration)

    # Optional extended re-incubation (~8% of samples)
    if random.random() < p.reincubation_percent:
        with resources["incubator"].request() as reinc_req:
            yield reinc_req
            tracker.log_event(spec_id, spec_type, EV.EXTENDED_REINCUBATION, env.now)
            min_reinc = p.min_reincubate_time * 60
            max_reinc = p.max_reincubate_time * 60
            reincubation_duration = random.uniform(min_reinc, max_reinc)
            if DEBUG_BOTTLENECKS:
                print(f"DEBUG_BOTTLENECK [Reincubation] spec_id={spec_id} incubator_queue={len(resources['incubator'].queue)} duration_min={reincubation_duration/60:.2f}")
            yield env.timeout(reincubation_duration)


# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------

