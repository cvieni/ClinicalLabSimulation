"""Final-report stage.

Two separate things happen between the end of the simulated bench work and "10. Completed":

1. NEGATIVE cultures (bottle negatives and plates with no significant growth): NO second read and no tech time.
   They are only held until their final-report time (per-type hold, see final_read_snippet.py), rounded up to the
   next scheduled read slot.  While held they occupy no resource.
2. POSITIVE cultures: wait a short delay after the workup finishes, then ONE final read/verify by a tech
   (tech_supervisor first; see pick_final_read_tech).  The delay depends on the specimen:
       blood cultures / body-fluid bottles            p.final_read_delay_blood_hours   (default 1-2 h)
       types with "positive_delay_hours" in config    that range (e.g. Wound, Wound_Genital: 8-10 h)
       any positive that had AST (n_ast > 0)          p.final_read_delay_ast_hours     (default 8-10 h)
       other positives                                p.final_read_delay_other_hours   (default 1-2 h)
   A positive is never finalled before its type's hold/extended time either (max of the two).

Per-type SPECIMEN_TYPES[type]["final_read"] (optional):
    {"hold_hours": (lo, hi), "extended_fraction": f, "extended_hours": (lo, hi), "positive_delay_hours": (lo, hi)}
Own random stream per specimen: it never shifts any other draw.  Disable everything: p.final_read_enabled = False.
All delay ranges, the verify time (p.min/max_final_read_time, default 1-3 min) are ASSUMPTIONS.
"""
import random

import params_config.params_d3 as p
from modules.spec_proc_helpers import req_resource, get_least_busy_tech

EV_FINAL_HOLD = "9a. Final Read Hold (waiting for final-report time)"
EV_EXTENDED_HOLD = "9b. Extended Hold (AFB/fungal-dependent final)"
EV_FINAL_READ = "9c. Final Read / Verify"
EV_POSITIVE_WAIT = "9d. Positive Final Wait (before verify)"


def _free(r):
    return r is not None and r.capacity > 0 and r.count < r.capacity and not r.queue


def pick_final_read_tech(resources):
    """tech_supervisor if one is free; else a free tech_routine / tech_new; else queue on the supervisor
    (or, when no supervisor is on shift, the less busy of routine/new)."""
    sup = resources.get("tech_supervisor")
    if _free(sup):
        return sup
    free = [r for r in (resources.get("tech_routine"), resources.get("tech_new")) if _free(r)]
    if free:
        return min(free, key=lambda r: r.count / r.capacity)
    if sup is not None and sup.capacity > 0:
        return sup
    return get_least_busy_tech(resources, "tech_routine", "tech_new")


def _delay_range(spec_cfg, cfg, n_ast):
    if cfg.get("positive_delay_hours"):
        return cfg["positive_delay_hours"]
    if spec_cfg.get("is_blood_culture") or spec_cfg.get("is_BodyFluid"):
        return getattr(p, "final_read_delay_blood_hours", (1.0, 2.0))
    if n_ast and n_ast > 0:
        return getattr(p, "final_read_delay_ast_hours", (8.0, 10.0))
    return getattr(p, "final_read_delay_other_hours", (1.0, 2.0))


def process_final_read(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority,
                       arrival_time, next_slot=None, positive=False, n_ast=0):
    """Generator: `yield from process_final_read(...)` right before logging EV.COMPLETED."""
    if not getattr(p, "final_read_enabled", True) or arrival_time is None:
        return
    cfg = spec_cfg.get("final_read") or {}
    rng = random.Random(f"{env.run_seed}:{spec_type}:{spec_id}:final")

    # --- earliest final-report time for the type (draws are always made -> stable stream) ---
    lo, hi = cfg.get("hold_hours", (0.0, 0.0))
    target = arrival_time + rng.uniform(lo, hi) * 60.0
    extended = rng.random() < float(cfg.get("extended_fraction", 0.0) or 0.0)
    elo, ehi = cfg.get("extended_hours", (0.0, 0.0))
    ext_target = arrival_time + rng.uniform(elo, ehi) * 60.0
    if extended:
        target = max(target, ext_target)
    dlo, dhi = _delay_range(spec_cfg, cfg, n_ast)
    delay = rng.uniform(dlo, dhi) * 60.0
    verify = rng.uniform(float(getattr(p, "min_final_read_time", 1.0)), float(getattr(p, "max_final_read_time", 3.0)))

    if positive:
        target = max(target, env.now + delay)      # delay after the workup finished
    elif next_slot is not None and getattr(p, "scheduled_reads_enabled", False) and target > env.now:
        target = max(target, next_slot(target))    # negatives are released at a scheduled read slot

    if target > env.now:
        if positive and target <= env.now + delay + 1e-9:
            ev = EV_POSITIVE_WAIT
        else:
            ev = EV_EXTENDED_HOLD if extended else EV_FINAL_HOLD
        tracker.log_event(spec_id, spec_type, ev, env.now)
        yield env.timeout(target - env.now)

    if not positive:
        return                                      # negatives: no second read

    tech = pick_final_read_tech(resources)
    with req_resource(tech, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, EV_FINAL_READ, env.now)
        yield env.timeout(verify)
