import random
import numpy as np
import params_config.params_d3 as p

from modules.spec_proc_helpers import req_resource, get_least_busy_tech
from params_config import event_name as EV
from modules.literature_times import gram_stain_minutes

# ==================================================================================
# MALDI-TOF: tech spots isolates, isolates from several specimens share one cartridge, a tech stays at the machine
# ==================================================================================
class MaldiBatcher:
    """One cartridge at a time. Specimens add their isolates after spotting; the cartridge is run when it holds its
    target number of isolates (drawn per cartridge from p.maldi_batch_isolates_range, default 30-50) or when its
    first isolate has waited p.maldi_batch_max_wait_minutes (default 360). A run occupies the MALDI instrument AND a
    tech (the tech stays by the machine) for n_isolates x p.maldi_run_min_per_isolate minutes (default 0.5, so about
    20 min for 40 isolates). Every specimen on the cartridge gets MALDI_RUN_START / MALDI_ID_DONE at the same times.
    p.maldi_batching_enabled = False: every specimen is run alone, immediately (still tech + instrument)."""

    def __init__(self, env, resources, tracker):
        self.env, self.res, self.tracker = env, resources, tracker
        self.rng = random.Random(f"{getattr(env, 'run_seed', 0)}:maldi_batch")
        self.pending, self.n_pending, self.batch_id, self.target = [], 0, 0, None
        self.runs = []                                   # (start, n_isolates, n_specimens) for diagnostics

    def _new_target(self):
        if not getattr(p, "maldi_batching_enabled", True):
            return 1
        lo, hi = getattr(p, "maldi_batch_isolates_range", (30, 50))
        return self.rng.randint(int(lo), int(hi))

    def submit(self, spec_id, spec_type, spec_priority, n_isolates):
        """Returns an event that fires when this specimen's isolates have been identified."""
        done = self.env.event()
        if not self.pending:
            self.target = self._new_target()
            self.batch_id += 1
            self.env.process(self._timeout(self.batch_id))
        self.pending.append(dict(spec_id=spec_id, spec_type=spec_type, priority=spec_priority, n=n_isolates, done=done))
        self.n_pending += n_isolates
        if self.n_pending >= self.target:
            self._launch()
        return done

    def _timeout(self, batch_id):
        yield self.env.timeout(float(getattr(p, "maldi_batch_max_wait_minutes", 360.0)))
        if self.pending and self.batch_id == batch_id:
            self._launch()

    def _launch(self):
        batch, self.pending, self.n_pending = self.pending, [], 0
        self.env.process(self._run(batch))

    def _run(self, batch):
        n_iso = sum(b["n"] for b in batch)
        prio = min(b["priority"] for b in batch)
        tech = get_least_busy_tech(self.res, "tech_routine", "tech_new")
        with req_resource(self.res["maldi_instrument"], prio) as m_req:
            yield m_req
            with tech.request(priority=prio) as t_req:          # tech stays at the machine for the whole run
                yield t_req
                t0 = self.env.now
                for b in batch:
                    self.tracker.log_event(b["spec_id"], b["spec_type"], EV.MALDI_RUN_START, t0)
                yield self.env.timeout(n_iso * float(getattr(p, "maldi_run_min_per_isolate", 0.5)))
                for b in batch:
                    self.tracker.log_event(b["spec_id"], b["spec_type"], EV.MALDI_ID_DONE, self.env.now)
                self.runs.append((t0, n_iso, len(batch)))
        for b in batch:
            b["done"].succeed()


def _get_batcher(env, resources, tracker):
    b = getattr(env, "_maldi_batcher", None)
    if b is None:
        b = env._maldi_batcher = MaldiBatcher(env, resources, tracker)
    return b


def process_maldi_testing(env, spec_id, spec_type, resources, tracker, spec_priority, n_isolates):
    """Pathway D1: Reflex MALDI-TOF identification.

    1. A tech spots each isolate onto the target: p.min_MALDI_prep_time..p.max_MALDI_prep_time minutes PER ISOLATE
       (set these to 1.0 and 2.0). The tech is released afterwards.
    2. The isolates join the current cartridge (MaldiBatcher); the specimen waits for that cartridge's run.
    """
    chosen_tech = get_least_busy_tech(resources, "tech_routine", "tech_new")
    with chosen_tech.request(priority=spec_priority) as tech_req:
        yield tech_req
        tracker.log_event(spec_id, spec_type, EV.MALDI_SPOT_START, env.now)
        yield env.timeout(random.uniform(p.min_MALDI_prep_time, p.max_MALDI_prep_time) * n_isolates)
        tracker.log_event(spec_id, spec_type, EV.maldi_spot_done(n_isolates), env.now)

    yield _get_batcher(env, resources, tracker).submit(spec_id, spec_type, spec_priority, n_isolates)


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
        tracker.log_event(spec_id, spec_type, EV.GRAM_STAIN_START, env.now)
        # Stochastic duration for smear prep, staining, reading, and rapid tests
        min_bio =  p.min_biochem_screen_time
        max_bio = p.max_biochem_screen_time
        # For gram stain a uniform distribution of a tight time window is probably most accurate
        bio_time = (gram_stain_minutes(random) if getattr(p, 'use_literature_task_times', False)   # smear + stain + dry + read, Gerada 2024
                    else random.uniform(min_bio, max_bio))
        # mean_bio = p.mean_biochem_screen_time
        # bio_time = random.expovariate(1.0 / mean_bio)
        yield env.timeout(bio_time)

        tracker.log_event(spec_id, spec_type, EV.GRAM_STAIN_DONE, env.now)



# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------------------------------------------------------

def process_BioFire(env, spec_id, spec_type, resources, tracker, spec_priority, requested_tech):

    tech_BioFire = resources.get(requested_tech)
    with req_resource(tech_BioFire, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, EV.BIOFIRE_START, env.now)
        # Stochastic duration for smear prep, staining, reading, and rapid tests
        min_bio =  p.min_BioFire_screen_time
        max_bio = p.max_BioFire_screen_time
        # For a specific test (biofire) a uniform distribution of a tight time window is probably most accurate
        bio_time = random.uniform(min_bio, max_bio)

        # Probably more appropriate for simulating several different biochemical tests more generally
        # mean_bio = p.mean_biochem_screen_time
        # bio_time = random.expovariate(1.0 / mean_bio)
        yield env.timeout(bio_time)

        tracker.log_event(spec_id, spec_type, EV.BIOFIRE_DONE, env.now)
