"""Bench (biochemical / rapid) tests and stool-specific primary incubation.

  process_biochem_phase(...)      run the steps BIOCHEM_PLAN lists for this specimen type and phase; returns False if a
                                  test with on_negative="stop" came back negative (caller closes the culture)
  hold_primary_incubation(...)    primary plate incubation: default model, or the per-type override
                                  SPECIMEN_TYPES[t]["primary_incubation"] = {"hours": 18, "incubator": True|False}

Isolates (modules/isolates.py): every test is claimed on an isolate of the specimen's IsolateSet, once per (isolate, test).
scope "specimen" tests one isolate (your "x % of cultures"); scope "isolate" gives every isolate its own draw.
Randomness: one stream per (specimen, phase, step), so adding or editing a test never shifts other draws.
"""
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


def _tech(spec_type, resources, phase):
    if phase == "presumptive":
        return get_tech_bench(spec_type, resources)             # the bench that read the plate
    up = spec_type.upper()
    if up.startswith("BCX") or up.startswith("BODYFLUID"):
        return resources["tech_blood"]
    return get_least_busy_tech(resources, "tech_routine", "tech_new")


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


def process_biochem_phase(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, phase, isolates):
    """Sequential steps of this phase (parallel steps are started by start_parallel_biochem). Returns False if a step with
    on_negative='stop' read negative on every isolate tested (the caller closes the culture)."""
    plan = BIOCHEM_PLAN.get(spec_type, {}).get(phase, [])
    if not plan or not p.biochem_tests_enabled:
        return True
    tech = _tech(spec_type, resources, phase)
    prev_positive = True
    for k, s in enumerate(plan):
        if s.get("parallel"):
            continue
        r = _step_rng(env, spec_type, spec_id, phase, k)
        if s.get("requires_prev") and not prev_positive:
            prev_positive = False
            continue
        results = []
        for iso in _claim(s, isolates, phase, r):
            yield from _run_test(env, s["test"], spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, tech, r)
            results.append(_positive(r, spec_cfg, s["test"]))
        prev_positive = any(results)
        if results and not prev_positive and s.get("on_negative") == "stop":
            tracker.log_event(spec_id, spec_type, EV.BIOCHEM_DISCARD, env.now)
            return False
    return True


def start_parallel_biochem(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, phase, isolates):
    """Start this phase's parallel steps (e.g. TSI) in the background NOW and return their processes; call join_parallel()
    before the final read.  Isolates are claimed immediately, so nothing can run the same test on them twice."""
    plan = BIOCHEM_PLAN.get(spec_type, {}).get(phase, [])
    if not plan or not p.biochem_tests_enabled:
        return []
    tech = _tech(spec_type, resources, phase)
    procs = []
    for k, s in enumerate(plan):
        if not s.get("parallel"):
            continue
        r = _step_rng(env, spec_type, spec_id, phase, k)
        chosen = _claim(s, isolates, phase, r)
        if chosen:
            procs.append(env.process(_parallel_runner(env, s["test"], len(chosen), spec_id, spec_type, spec_cfg, resources,
                                                      tracker, spec_priority, tech, r)))
    return procs


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
