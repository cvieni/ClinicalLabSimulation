import random
import numpy as np
import params_config.params_d2 as p

from modules.spec_proc_helpers import req_resource, get_least_busy_tech

def process_maldi_testing(env, spec_id, spec_type, resources, tracker, spec_priority):
    """Pathway D1: Reflex MALDI-TOF Identification."""
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


# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------

def process_GramStain(env, spec_id, spec_type, resources, tracker, spec_priority, requested_tech):
    """Gram Stain -> smear preparation, staining, reading, and rapid test reporting.
        Parameters:
        env: SimPy simulation environment
        spec_id: Unique identifier for the specimen
        spec_type: Type/category of the specimen
        resources: Dictionary of simulation resources
        tracker: SpecimenTracker instance for event logging
        spec_priority: Integer or float priority level for resource queuing
        requested_tech: String key for the required technician resource
    """

    tech_GramStain = resources.get(requested_tech)
    with req_resource(tech_GramStain, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, "Optional 1a: Gram Stain Setup", env.now)
        # Stochastic duration for smear prep, staining, reading, and rapid tests
        min_bio =  p.min_biochem_screen_time
        max_bio = p.max_biochem_screen_time
        # For gram stain a uniform distribution of a tight time window is probably most accurate
        bio_time = random.uniform(min_bio, max_bio)
        # mean_bio = p.mean_biochem_screen_time
        # bio_time = random.expovariate(1.0 / mean_bio)
        yield env.timeout(bio_time)

        tracker.log_event(spec_id, spec_type, "Optional 1b: Gram Stain Completed", env.now)



# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------

def process_BioFire(env, spec_id, spec_type, resources, tracker, spec_priority, requested_tech):

    tech_BioFire = resources.get(requested_tech)
    with req_resource(tech_BioFire, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, "Optional 2a: BioFire Setup", env.now)
        # Stochastic duration for smear prep, staining, reading, and rapid tests
        min_bio =  p.min_BioFire_screen_time
        max_bio = p.max_BioFire_screen_time
        # For a specific test (biofire) a uniform distribution of a tight time window is probably most accurate
        bio_time = random.uniform(min_bio, max_bio)

        # Probably more appropriate for simulating several different biochemical tests more generally
        # mean_bio = p.mean_biochem_screen_time
        # bio_time = random.expovariate(1.0 / mean_bio)
        yield env.timeout(bio_time)

        tracker.log_event(spec_id, spec_type, "Optional 2b: BioFire Completed", env.now)
