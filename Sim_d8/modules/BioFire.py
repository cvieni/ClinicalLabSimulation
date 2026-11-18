# modules/BioFire.py
import random

import params_config.params_d3 as p
from params_config import event_name as EV
from modules.spec_proc_helpers import req_resource


def process_BioFire(env, spec_id, spec_type, resources, tracker, spec_priority, requested_tech, rng=None):
    tech_BioFire = resources.get(requested_tech)
    with req_resource(tech_BioFire, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, EV.BIOFIRE_START, env.now)
        # no Gerada step for BioFire and no LIS stamp: assumed uniform tech time (params_d3 min/max_BioFire_screen_time)
        yield env.timeout(random.uniform(p.min_BioFire_screen_time, p.max_BioFire_screen_time))
        tracker.log_event(spec_id, spec_type, EV.BIOFIRE_DONE, env.now)
