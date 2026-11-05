import random
import numpy as np
import params_config.params_d3 as p

from modules.spec_proc_helpers import req_resource, get_least_busy_tech
from params_config import event_name as EV

# ==================================================================================
# STOOL CULTURE WORKFLOW FUNCTIONS (Non-Restricted Pathogens)
# ==================================================================================

def process_ecoli_pathway(env, spec_id, spec_type, resources, tracker, spec_priority, n_isolates):
    """
    E. coli Workflow:
    1. Perform MALDI-TOF identification.
    2. Perform E. coli latex agglutination test after MALDI identification.
    """
    # 1. Run MALDI-TOF
    yield env.process(process_maldi_testing(env, spec_id, spec_type, resources, tracker, spec_priority, n_isolates))
    
    # 2. Perform E. coli latex agglutination
    tech = get_least_busy_tech(resources, "tech_routine", "tech_new")
    with req_resource(tech, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, getattr(EV, "ECOLI_LATEX_START", "ECOLI_LATEX_START"), env.now)
        # Setup duration parameters in your params file (e.g., p.min_latex_time)
        latex_time = random.uniform(getattr(p, "min_latex_time", 2.0), getattr(p, "max_latex_time", 5.0))
        yield env.timeout(latex_time)
        tracker.log_event(spec_id, spec_type, getattr(EV, "ECOLI_LATEX_DONE", "ECOLI_LATEX_DONE"), env.now)


def process_vibrio_pathway(env, spec_id, spec_type, resources, tracker, spec_priority):
    """
    Vibrio Workflow:
    1. TCBS Agar incubation: 18 hours at 35°C.
    2. Sweep Oxidase test.
    3. If Oxidase positive -> Inoculate TSI.
       - If TSI returns K/A (Alkaline slant / Acid butt) -> Proceed to Phoenix ID/AST and/or MALDI.
       - Otherwise, discard.
    4. If Oxidase negative -> Discard.
    """
    # 1. Primary Incubation (18 hours = 1080 minutes)
    tcbs_incubation_time = 18.0 * 60.0
    yield env.timeout(tcbs_incubation_time)
    
    # 2. Sweep Oxidase Test
    tech = get_least_busy_tech(resources, "tech_routine", "tech_new")
    with req_resource(tech, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, getattr(EV, "VIBRIO_OXIDASE_START", "VIBRIO_OXIDASE_START"), env.now)
        yield env.timeout(random.uniform(1.0, 3.0))
        tracker.log_event(spec_id, spec_type, getattr(EV, "VIBRIO_OXIDASE_DONE", "VIBRIO_OXIDASE_DONE"), env.now)
    
    # Simulate Oxidase outcome (Boolean flag or rule)
    is_oxidase_positive = getattr(p, "simulate_vibrio_oxidase_pos", True)
    
    if not is_oxidase_positive:
        tracker.log_event(spec_id, spec_type, getattr(EV, "VIBRIO_DISCARD", "VIBRIO_DISCARD"), env.now)
        return

    # 3. TSI Reaction Incubation (typically 18-24 hours)
    tsi_incubation_time = 18.0 * 60.0
    yield env.timeout(tsi_incubation_time)
    
    # Simulate TSI reaction evaluation (e.g., 'K/A')
    tsi_reaction = getattr(p, "simulate_vibrio_tsi_rxn", "K/A")
    
    if tsi_reaction == "K/A":
        # Proceed to Phoenix and/or MALDI
        yield env.process(process_maldi_testing(env, spec_id, spec_type, resources, tracker, spec_priority, n_isolates=1))
    else:
        tracker.log_event(spec_id, spec_type, getattr(EV, "VIBRIO_DISCARD", "VIBRIO_DISCARD"), env.now)


def process_plate_retention_rules(env, plate_type, has_growth):
    """
    General Incubation & Retention Rules:
    - Plate from Gram-Negative (GN) Broth must incubate for at least 2 days (2880 mins), even if no growth.
    - CVA agar (Campylobacter) follows its specific retention protocol.
    - All other plates are discarded at 2 days (48 hours) if no growth is observed.
    """
    two_days_minutes = 48.0 * 60.0

    if plate_type == "GN_Broth_Subculture":
        # Always hold for at least 48 hours regardless of growth state at 24h
        yield env.timeout(two_days_minutes)
        if not has_growth:
            return "DISCARD"
            
    elif plate_type == "CVA":
        # CVA agar microaerophilic incubation holds longer (e.g., 48-72 hours)
        cva_hold_time = getattr(p, "cva_incubation_minutes", 72.0 * 60.0)
        yield env.timeout(cva_hold_time)
        if not has_growth:
            return "DISCARD"
            
    else:
        # Standard routine plates (e.g., MacConkey, Hektoen)
        yield env.timeout(two_days_minutes)
        if not has_growth:
            return "DISCARD"
            
    return "PROCESS_COLONIES"



def process_yersinia_enterocolitica_pathway(env, spec_id, spec_type, resources, tracker, spec_priority, n_isolates=1):
    """
    Yersinia enterocolitica Workflow:
    1. Primary Isolation & Incubation: MAC/CIN plate incubated at room temp (22-25°C) for 48 hours.
    2. Examine plate at 48 hours. If characteristic colonies are present:
       - Inoculate TSI slant (incubate at 37°C for 18-24 hours).
       - Inoculate 2 MIO (Motility-Indole-Ornithine) tubes (incubate one at 22°C and one at 37°C for motility comparison).
    3. Biochemical Screening:
       - Perform Oxidase (negative), Catalase (positive), Indole, and Urease (positive) testing.
    4. Automated Identification & AST:
       - Process on Phoenix system.
       - Confirm ID with MALDI-TOF or 16S sequencing.
    """
    # 1. Primary Incubation at Room Temperature (48 hours = 2880 minutes)
    room_temp_incubation_time = 48.0 * 60.0
    yield env.timeout(room_temp_incubation_time)

    # 2. Plate Examination at 48 Hours
    tech = get_least_busy_tech(resources, "tech_routine", "tech_new")
    with req_resource(tech, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, getattr(EV, "YERSINIA_PLATE_READ_START", "YERSINIA_PLATE_READ_START"), env.now)
        yield env.timeout(random.uniform(2.0, 5.0))  # Plate reading duration
        tracker.log_event(spec_id, spec_type, getattr(EV, "YERSINIA_PLATE_READ_DONE", "YERSINIA_PLATE_READ_DONE"), env.now)

    # Check for target colony growth
    has_characteristic_colonies = getattr(p, "simulate_yersinia_growth", True)
    if not has_characteristic_colonies:
        tracker.log_event(spec_id, spec_type, getattr(EV, "YERSINIA_DISCARD", "YERSINIA_DISCARD"), env.now)
        return

    # 3. Subculture to TSI & Dual MIO Tubes (Incubate 18-24 hours = ~1080 minutes)
    with req_resource(tech, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, getattr(EV, "YERSINIA_INOCULATION_START", "YERSINIA_INOCULATION_START"), env.now)
        yield env.timeout(random.uniform(3.0, 7.0))  # Set up TSI & MIO tubes
        tracker.log_event(spec_id, spec_type, getattr(EV, "YERSINIA_INOCULATION_DONE", "YERSINIA_INOCULATION_DONE"), env.now)

    tube_incubation_time = 24.0 * 60.0
    yield env.timeout(tube_incubation_time)

    # 4. Biochemical Screening Panel (Oxidase, Catalase, Indole, Urease)
    with req_resource(tech, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, getattr(EV, "YERSINIA_BIOCHEM_START", "YERSINIA_BIOCHEM_START"), env.now)
        biochem_duration = random.uniform(
            getattr(p, "min_biochem_screen_time", 5.0),
            getattr(p, "max_biochem_screen_time", 15.0)
        )
        yield env.timeout(biochem_duration)
        tracker.log_event(spec_id, spec_type, getattr(EV, "YERSINIA_BIOCHEM_DONE", "YERSINIA_BIOCHEM_DONE"), env.now)

    # 5. Automated Identification & AST (Phoenix) + Confirmation (MALDI-TOF)
    # Phoenix setup/run
    with req_resource(tech, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, getattr(EV, "PHOENIX_SETUP_START", "PHOENIX_SETUP_START"), env.now)
        yield env.timeout(random.uniform(2.0, 5.0))
        tracker.log_event(spec_id, spec_type, getattr(EV, "PHOENIX_SETUP_DONE", "PHOENIX_SETUP_DONE"), env.now)

    # Phoenix instrument incubation/reading (typically 12-16 hours)
    phoenix_run_time = getattr(p, "phoenix_incubation_minutes", 12.0 * 60.0)
    yield env.timeout(phoenix_run_time)
    tracker.log_event(spec_id, spec_type, getattr(EV, "PHOENIX_ID_DONE", "PHOENIX_ID_DONE"), env.now)

    # Reflex/Confirmatory MALDI-TOF testing
    yield env.process(process_maldi_testing(env, spec_id, spec_type, resources, tracker, spec_priority, n_isolates))