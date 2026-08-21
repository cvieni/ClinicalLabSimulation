# modules/subpathways.py
import random
import numpy as np
import params_config.params_d2 as p
from modules.spec_proc_helpers import req_resource, consume_media_inventory, get_least_busy_tech
from modules.specimen_priority import get_specimen_priority


def process_accessioning(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, arrival_time):
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
        p_norm = np.array(probs, dtype=np.float64)
        p_norm /= p_norm.sum()
        bin_idx = np.random.choice(len(p_norm), p=p_norm)
        # 3. Draw duration and cap at your real-world max limit
        db_InLab_Min_CultSrt_time = np.random.uniform(edges[bin_idx], edges[bin_idx + 1])

        # -----------------------------------------------------
        # 2. Sample Plating Time (Triangular Distribution)
        # -----------------------------------------------------
        # Reviewing the way that Accession time was calculated from my SQL pull it seems like Accession is "IN_LAB_WHEN" - "CULTURE_START_WHEN"
        # And a lot of the times are just nonsense...
        proc_plating_time_cfg = spec_cfg.get("plating_time_range")
        min_plt_time = float(proc_plating_time_cfg[0])
        max_plating_time = float(proc_plating_time_cfg[1])
        mean_plating_time = (min_plt_time + max_plating_time)/2
        plating_duration = random.triangular(min_plt_time, max_plating_time, mean_plating_time)

        # 3. Deduct Plating Time safely with a 1.0 minute lower bound floor
        pure_accession_time = max(1.0, db_InLab_Min_CultSrt_time - plating_duration)

        yield env.timeout(pure_accession_time)
        
        tracker.log_event(spec_id, spec_type, "1d. Accessioning & Central Processing Completed", env.now)


# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------


def process_automated_bactec(env, spec_id, spec_type, spec_cfg, resources, tracker,
                             is_blood_culture, is_body_fluid):
    """Pathway A1: BCx / BodyFluid Bactec Instrument processing."""
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
            # Retrieve specimen specific Time To Positive (TTP) config
            cfg = spec_cfg.get("ttp_config")

            # 1. Randomly pick a bin based on the historical percentages
            selected_bin_idx = np.random.choice(len(cfg["bin_probabilities"]), p=cfg["bin_probabilities"])

            # 2. Uniformly sample a specific time within that chosen bin's boundaries
            low_edge = cfg["bin_edges"][selected_bin_idx]
            high_edge = cfg["bin_edges"][selected_bin_idx + 1]
            ttp_duration_hrs = np.random.uniform(low_edge, high_edge)
            # ttp = np.random.uniform(cfg["bin_edges"][selected_bin], cfg["bin_edges"][selected_bin + 1])

            yield env.timeout(ttp_duration_hrs * 60.0)
            tracker.log_event(spec_id, spec_type, "2b. BCx or BodyFluid Flagged POSITIVE", env.now)
            return True  # Proceed to subculturing
        
        else:
            # Holds the instrument slot for 5 days (120 hours) then frees slot
            yield env.timeout(120 * 60)
            tracker.log_event(spec_id, spec_type, "2c. BC Flagged NEGATIVE", env.now)
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
    tracker.log_event(spec_id, spec_type, "Accessioning (Automated System Prep) Started", env.now)

    # 0-2 minutes of extra accessioning time to load onto WASP machine
    extra_accession_time = random.uniform(0.0, 2.0)
    yield env.timeout(extra_accession_time)

    # 2. Consume required media (No lab tech resource needed)
    media_requirements = spec_cfg.get("media_req", {})
    media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_requirements)

    if not media_allocated:
        return False # Abort specimen processing immediately

    # 3. Automated Plating Execution
    tracker.log_event(spec_id, spec_type, "3B-1. Sample loaded for Automated Plating Started", env.now)

    # Simulate automated plating processing time (e.g., 1.5 - 3.0 min per sample)
    auto_plate_time = random.uniform(p.automatic_plating_time_min, p.automatic_plating_time_max)
    yield env.timeout(auto_plate_time)
    tracker.log_event(spec_id, spec_type, "3B-1. Automated Plating Completed", env.now)

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

    tech_plating = resources.get("tech_plating")
    with req_resource(tech_plating, spec_priority) as req:
        yield req

        media_requirements = spec_cfg.get("media_req", {})
        media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_requirements)

        if not media_allocated:
            return False

        # =========================================
        # 3A. PLATING STAGE (Move specimen to plating bench)
        # =========================================
        with req_resource(resources["plating_bench"], spec_priority) as p_req:
            yield p_req
            tracker.log_event(spec_id, spec_type, "3B-2. Plating from PrimarySpecimen Started", env.now)

            # mu = p.avg_plating_time
            # sigma = p.plating_std_time
            # plating_duration = max(mintime, random.normalvariate(mu, sigma))
            mintime = p.min_plating_time
            max_plating_time = p.max_plating_time
            mean_plating_time = p.avg_plating_time
            plating_duration = random.triangular(mintime, max_plating_time, mean_plating_time)
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
        tracker.log_event(spec_id, spec_type, "4. Tech Review Started (Plate - Day 2)", env.now)
        min_time, max_time = spec_cfg.get("tech_review_range", (p.min_tech_review_sub, p.max_tech_review_sub))
        yield env.timeout(random.uniform(min_time, max_time))

    # Optional extended re-incubation (~8% of samples)
    if random.random() < p.reincubation_percent:
        with resources["incubator"].request() as reinc_req:
            yield reinc_req
            tracker.log_event(spec_id, spec_type, "4a. Extended Re-Incubation", env.now)
            min_reinc = p.min_reincubate_time * 60
            max_reinc = p.max_reincubate_time * 60
            yield env.timeout(random.uniform(min_reinc, max_reinc))


# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------

