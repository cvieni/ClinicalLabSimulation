"""Bench (biochemical / rapid) tests and stool-specific primary incubation.

  process_biochem_phase(...)      run the steps BIOCHEM_PLAN lists for this specimen type and phase; returns False if a
                                  test with on_negative="stop" came back negative (caller closes the culture)
  hold_primary_incubation(...)    primary plate incubation: default model, or the per-type override
                                  SPECIMEN_TYPES[t]["primary_incubation"] = {"hours": 18, "incubator": True|False}

Isolates (modules/isolates.py): every test is claimed on an isolate of the specimen's IsolateSet, once per (isolate, test).
scope "specimen" tests one isolate (your "x % of cultures"); scope "isolate" gives every isolate its own draw.
Randomness: one stream per (specimen, phase, step), so adding or editing a test never shifts other draws.
"""
import math
import random

import params_config.params_d3 as p
from params_config import event_name as EV
from params_config.biochem_config import BIOCHEM_PLAN
from modules.spec_proc_helpers import req_resource, get_tech_bench, get_least_busy_tech

# setup = (min_key, max_key) in minutes of tech time; wait = (min_key, max_key, minutes-per-unit); read = tech time after the wait
TEST_DEFS = {
    "oxidase":       dict(setup=("min_oxidase_time", "max_oxidase_time")),
    "indole":        dict(setup=("min_indole_time", "max_indole_time")),
    "catalase":      dict(setup=("min_catalase_time", "max_catalase_time")),
    "latex":         dict(setup=("min_latex_time", "max_latex_time")),
    "biochem_panel": dict(setup=("min_biochem_screen_time", "max_biochem_screen_time")),
    "tsi":           dict(setup=("min_tsi_setup_time", "max_tsi_setup_time"),
                          wait=("min_tsi_incubation_hours", "max_tsi_incubation_hours", 60.0), incubator=True,
                          read=("min_tsi_read_time", "max_tsi_read_time")),
    "pbp":           dict(setup=("min_pbp_setup_time", "max_pbp_setup_time"),
                          wait=("min_pbp_wait_minutes", "max_pbp_wait_minutes", 1.0), incubator=False,
                          read=("min_pbp_read_time", "max_pbp_read_time")),
}


def _val(spec_cfg, key):
    """per-specimen-type override wins, otherwise params_d3 (a typo raises AttributeError)"""
    return spec_cfg[key] if key in spec_cfg else getattr(p, key)


def note_processor(env, spec_id, spec_type, req, fallback):
    """Remember which bench actually read this specimen's plate (the member that served a pooled request, else the resource asked)."""
    served = getattr(req, "granted", None)
    env.__dict__.setdefault("processors", {})[(spec_type, spec_id)] = served[0] if served else fallback


def _type_bench(env, spec_type, resources):
    """The specimen type's own bench: bottles -> tech_blood, urine -> tech_urine, stool -> p.stool_review_bench, rest -> routine side."""
    up = spec_type.upper()
    if up.startswith(("BCX", "BODYFLUID", "URINE", "STOOL")):
        return get_tech_bench(spec_type, resources)
    return get_least_busy_tech(resources, "tech_routine", "tech_new")


def _tech(env, spec_id, spec_type, resources, phase, step):
    """Who runs a bench test.  step["bench"] (optional) overrides:  "processor" | "type" | "routine" | any resource key (e.g. "tech_urine").
    Default: presumptive tests (read with the plate) -> the tech who read this plate (falls back to the type's bench if that bench has
    no staff now); post-ID tests -> the type's own bench (bottles/urine/stool) or the routine side (everything else, as MALDI/AST prep)."""
    mode = step.get("bench") or ("processor" if phase == "presumptive" else "type")
    if mode == "processor":
        r = getattr(env, "processors", {}).get((spec_type, spec_id))
        if r is not None and r.capacity > 0:
            return r
        return _type_bench(env, spec_type, resources)
    if mode == "type":
        return _type_bench(env, spec_type, resources)
    if mode == "routine":
        return get_least_busy_tech(resources, "tech_routine", "tech_new")
    return resources[mode] if resources[mode].capacity > 0 else _type_bench(env, spec_type, resources)


def _run_test(env, test, spec_id, spec_type, spec_cfg, resources, tracker, prio, tech, r):
    d, ev = TEST_DEFS[test], EV.BENCH_TEST_EVENTS[test]
    lo, hi = d["setup"]
    with req_resource(tech, prio) as req:
        yield req
        tracker.log_event(spec_id, spec_type, ev["setup"], env.now)
        yield env.timeout(r.uniform(_val(spec_cfg, lo), _val(spec_cfg, hi)))
    if "wait" in d:
        wlo, whi, unit = d["wait"]
        minutes = r.uniform(_val(spec_cfg, wlo), _val(spec_cfg, whi)) * unit
        if d.get("incubator"):
            with resources["incubator"].request() as inc:
                yield inc
                tracker.log_event(spec_id, spec_type, ev["wait"], env.now)
                yield env.timeout(minutes)
        else:                                                    # bench wait: the tech is free to do other work
            tracker.log_event(spec_id, spec_type, ev["wait"], env.now)
            yield env.timeout(minutes)
    if "read" in d:
        rlo, rhi = d["read"]
        with req_resource(tech, prio) as req:
            yield req
            yield env.timeout(r.uniform(_val(spec_cfg, rlo), _val(spec_cfg, rhi)))
    tracker.log_event(spec_id, spec_type, ev["done"], env.now)


def _step_rng(env, spec_type, spec_id, phase, k):
    """One stream per (specimen, phase, step): editing one step never shifts another step's draws."""
    return random.Random(f"{env.run_seed}:{spec_type}:{spec_id}:biochem:{phase}:{k}")


def _claim(step, isolates, phase, r):
    """Isolates this step will test (already marked on the isolate set). scope 'specimen': at most one isolate, with probability
    p; scope 'isolate': an independent draw per isolate.  post_id steps and from='identified' only consider MALDI-identified isolates."""
    test = step["test"]
    cand = isolates.pending(test, identified_only=(phase == "post_id" or step.get("from") == "identified"))
    pct = float(step.get("p", 1.0))
    if step.get("scope", "specimen") == "isolate":
        chosen = [i for i in cand if r.random() < pct]
    else:
        chosen = [r.choice(cand)] if cand and r.random() < pct else []
    for i in chosen:
        isolates.mark(i, test)
    return chosen


def _positive(r, spec_cfg, test):
    return r.random() < float(_val(spec_cfg, f"{test}_positive_rate"))


class Job:
    """One planned bench test: which step, the isolates it was claimed on, and the random stream it keeps drawing results from."""
    __slots__ = ("k", "step", "isolates", "r")

    def __init__(self, k, step, isolates, r):
        self.k, self.step, self.isolates, self.r = k, step, isolates, r


def plate_incubations(spec_cfg, reincubated):
    """Incubations the plate has had when it is read: the type's configured hold (48 h -> 2, 72 h -> 3; default 1) + 1 if re-incubated."""
    ov = spec_cfg.get("primary_incubation")
    base = max(1, math.ceil(float(ov["hours"]) / 24.0 - 0.01)) if ov else 1
    return base + (1 if reincubated else 0)


def plan_biochem(env, spec_id, spec_type, spec_cfg, phase, isolates):
    """Decide (once, deterministically) which tests this specimen gets and on which isolates; they are claimed now so nothing can repeat."""
    if not p.biochem_tests_enabled:
        return []
    return [Job(k, s, _claim(s, isolates, phase, _step_rng(env, spec_type, spec_id, phase, k)), _step_rng(env, spec_type, spec_id, phase, k))
            for k, s in enumerate(BIOCHEM_PLAN.get(spec_type, {}).get(phase, []))]


def split_jobs(jobs, isolates):
    """(run now at the plate read, defer to the next plate).  Rule: the tech who read the plate runs the test only if it is the isolate's
    first plate and it has not been incubated twice; step option at_read=True forces 'now'.  Otherwise the test waits for the next plate that
    has been incubated once, i.e. the subculture, and is run by whoever reads it."""
    if isolates.eligible_at_read():
        return list(jobs), []
    return [j for j in jobs if j.step.get("at_read")], [j for j in jobs if not j.step.get("at_read")]


def run_biochem_jobs(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, phase, isolates, jobs, bench_key=None):
    """Run planned tests in order.  Returns (continue?, [background processes]); continue is False when a step with on_negative='stop'
    read negative on every isolate tested (the caller closes the culture).  bench_key forces the bench (the tech who read the subculture plate)
    unless the step names its own."""
    procs = []
    prev = isolates.bio_prev
    for j in jobs:
        s = j.step
        if s.get("requires_prev") and not prev:
            prev = False
            continue
        tech = (resources[bench_key] if bench_key and not s.get("bench") and resources[bench_key].capacity > 0
                else _tech(env, spec_id, spec_type, resources, phase, s))
        if s.get("parallel"):
            if j.isolates:
                procs.append(env.process(_parallel_runner(env, s["test"], len(j.isolates), spec_id, spec_type, spec_cfg, resources,
                                                          tracker, spec_priority, tech, j.r)))
            prev = bool(j.isolates)
            continue
        results = []
        for _ in j.isolates:
            yield from _run_test(env, s["test"], spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, tech, j.r)
            results.append(_positive(j.r, spec_cfg, s["test"]))
        prev = any(results)
        isolates.bio_prev = prev
        if results and not prev and s.get("on_negative") == "stop":
            tracker.log_event(spec_id, spec_type, EV.BIOCHEM_DISCARD, env.now)
            return False, procs
    isolates.bio_prev = prev
    return True, procs


def process_biochem_phase(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, phase, isolates):
    """Plan + run a whole phase now (used for post_id tests).  Background tests are joined before returning."""
    jobs = plan_biochem(env, spec_id, spec_type, spec_cfg, phase, isolates)
    ok, procs = yield from run_biochem_jobs(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, phase, isolates, jobs)
    yield from join_parallel(env, procs)
    return ok


def start_parallel_biochem(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, phase, isolates):
    """Compatibility (v3-v5 call site): plan + start only the parallel steps of a phase.  The v6 call site uses plan/split/run instead."""
    jobs = [j for j in plan_biochem(env, spec_id, spec_type, spec_cfg, phase, isolates) if j.step.get("parallel")]
    _, procs = yield_free_run(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, phase, isolates, jobs)
    return procs


def yield_free_run(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, phase, isolates, jobs):
    procs = []
    for j in jobs:
        tech = _tech(env, spec_id, spec_type, resources, phase, j.step)
        if j.isolates:
            procs.append(env.process(_parallel_runner(env, j.step["test"], len(j.isolates), spec_id, spec_type, spec_cfg, resources,
                                                      tracker, spec_priority, tech, j.r)))
    return True, procs


def _parallel_runner(env, test, n, spec_id, spec_type, spec_cfg, resources, tracker, prio, tech, r):
    for _ in range(n):
        yield from _run_test(env, test, spec_id, spec_type, spec_cfg, resources, tracker, prio, tech, r)


def join_parallel(env, procs):
    pending = [x for x in procs if not x.triggered]
    if pending:
        yield env.all_of(pending)


def hold_primary_incubation(env, spec_id, spec_type, spec_cfg, resources, tracker, default_minutes):
    """default_minutes: zero-argument callable, evaluated AFTER the incubator slot is granted (scheduled-read model needs env.now)."""
    ov = spec_cfg.get("primary_incubation")
    if ov and not ov.get("incubator", True):                     # e.g. Yersinia at room temperature: no incubator slot
        tracker.log_event(spec_id, spec_type, EV.PRIMARY_INCUBATION, env.now)
        yield env.timeout(float(ov["hours"]) * 60.0)
        return
    with resources["incubator"].request() as inc:
        yield inc
        tracker.log_event(spec_id, spec_type, EV.PRIMARY_INCUBATION, env.now)
        yield env.timeout(float(ov["hours"]) * 60.0 if ov else default_minutes())
