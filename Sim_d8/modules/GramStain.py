# modules/GramStain.py
import random

import params_config.params_d3 as p          # noqa: F401  (kept for parameter-table tracing)
from params_config import event_name as EV
from params_config import accession_steps as AS
from modules.spec_proc_helpers import req_resource
from modules.gerada_times import step_minutes


def process_GramStain(env, spec_id, spec_type, resources, tracker, spec_priority, requested_tech, rng=None):
    """Gram stain of a positive bottle, as Gerada et al. 2024 (Table 1) steps: [bottle handling for BCx/BodyFluid:
    unload, hazard check, vent] -> prepare smear -> stain -> dry -> read/report. One timeout per step, tech held
    throughout (Gerada timed the tech's task). Step lists live in params_config/accession_steps.py.

        env, spec_id, spec_type, resources, tracker, spec_priority as elsewhere;
        requested_tech: key of the tech resource that does the stain (e.g. "tech_blood")
    """
    tech_GramStain = resources.get(requested_tech)
    with req_resource(tech_GramStain, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, EV.GRAM_STAIN_START, env.now)
        steps = (list(AS.GRAM_BOTTLE_PREP_STEPS) if spec_type in AS.GRAM_BOTTLE_TYPES else []) + list(AS.GRAM_STEPS)
        for step in steps:
            yield env.timeout(step_minutes(step, rng if rng is not None else random, per_specimen=True))
            ev = getattr(EV, f"STEP_{step.upper()}_DONE", None)      # optional sub-step events
            if ev:
                tracker.log_event(spec_id, spec_type, ev, env.now)
        tracker.log_event(spec_id, spec_type, EV.GRAM_STAIN_DONE, env.now)
