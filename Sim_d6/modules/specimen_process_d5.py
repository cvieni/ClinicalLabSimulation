import random
import zlib

import numpy as np

from modules.specimen_priority import get_specimen_priority
from modules.spec_proc_helpers import req_resource, get_tech_bench, get_least_busy_tech, consume_media_inventory
from modules.subpathways import process_automated_bactec, process_automated_wasp, process_manual_plating
from modules.MALDI_biochemicals import process_maldi_testing, process_BioFire, process_GramStain
from modules.AST_phoenix import process_phoenix_testing
from modules.accession_d2 import process_accessioning
from params_config import event_name as EV

# Centralized parameters file which has the adjustable variables
import params_config.params_d3 as p
from params_config.specimen_config_d2 import SPECIMEN_TYPES, resolve_specimen_tuning_value, resolve_time_range_override


# ==================================================================================
# Randomness: one independent stream per specimen
# ==================================================================================
class _SpecRng:
    """Per-specimen random streams keyed by (run seed, type, id).

    With the old global random.seed(), adding or removing ONE draw anywhere shifted every
    later draw in the run, so two scenarios could never share random numbers. Now a change
    to one specimen's logic only changes that specimen's draws, which makes paired
    (common-random-number) scenario comparisons possible.
    Limitation: submodules (accession, MALDI, ...) still draw from the global generator.
    env.run_seed is set in run_simulation; there is deliberately no default.
    """
    __slots__ = ("py", "np")

    def __init__(self, env, spec_type, spec_id):
        key = f"{env.run_seed}:{spec_type}:{spec_id}"
        self.py = random.Random(key)                              # str seeds are hashed deterministically
        self.np = np.random.default_rng(zlib.crc32(key.encode("utf-8")))


# ==================================================================================
# Parameter access (no silent defaults)
# ==================================================================================
def _rate(spec_cfg, key):
    """Per-specimen-type value in SPECIMEN_TYPES[...] wins; otherwise the global p.<key>.

    Lets urine / wound / stool / sputum have their own positivity, polymicrobial and workup
    rates (set them from the LIS) without touching the global defaults. A typo in `key`
    raises AttributeError instead of silently using a default.
    """
    return spec_cfg[key] if key in spec_cfg else getattr(p, key)


def _tuned(env, spec_cfg, key):
    """Specimen/shift tuning-matrix override if present, else p.<key> (fails loudly)."""
    v = resolve_specimen_tuning_value(spec_cfg, key, sim_minutes=env.now)
    return float(getattr(p, key) if v is None else v)


def _get_specimen_flags(spec_type, spec_cfg):
    return {
        "is_blood_culture": spec_type.upper().startswith("BCX") or spec_cfg.get("is_blood_culture", False),
        "is_body_fluid": spec_type.upper().startswith("BODYFLUID") or spec_cfg.get("is_BodyFluid", False),
        "is_stool_culture": spec_type.upper().startswith("STOOL") or spec_cfg.get("is_stool", False),
        "is_urine_culture": spec_type.upper().startswith("URINE") or spec_cfg.get("is_urine", False),
    }


# ==================================================================================
# Incubation: scheduled plate reads (5b) or explicit truncated lognormal
# ==================================================================================
def _truncated_lognormal(rng_np, mean, sd, lo, hi, tries=200):
    """Lognormal with the given mean and SD, resampled (not clipped) into [lo, hi]."""
    if mean <= 0:
        raise ValueError(f"incubation mean must be > 0, got {mean}")
    sigma2 = np.log(1.0 + (max(sd, 1e-6) / mean) ** 2)
    mu, sigma = np.log(mean) - sigma2 / 2.0, np.sqrt(sigma2)
    for _ in range(tries):
        x = rng_np.lognormal(mu, sigma)
        if lo <= x <= hi:
            return float(x)
    return float(min(max(mean, lo), hi))


def _next_read_time(t_min):
    """First scheduled plate-read slot at or after sim time t_min (minutes).

    Slots come from p.plate_read_hours_weekday / _weekend. Sim t=0 is midnight on weekday
    p.sim_start_weekday (0=Mon) -- keep that consistent with your shift manager.
    """
    day0 = int(t_min // 1440)
    for d in range(day0, day0 + 8):
        weekday = (int(p.sim_start_weekday) + d) % 7
        hours = p.plate_read_hours_weekend if weekday >= 5 else p.plate_read_hours_weekday
        for h in sorted(hours):
            slot = d * 1440 + float(h) * 60.0
            if slot >= t_min:
                return slot
    raise RuntimeError("No plate-read slot within 8 days: check plate_read_hours_weekday/weekend")


_INCUBATION_KINDS = {
    # kind: (avg, sd, floor) keys for the unscheduled model, key for the scheduled model's minimum
    "primary": ("avg_incubation_time_Other", "std_incubation_time_Other", "min_incubation_time_Other",
                "read_min_incubation_primary_hours"),
    "blood":   ("incubation_1_time_avg", "incubation_1_time_sd", "incubation_1_time_min",
                "read_min_incubation_blood_hours"),
    "repeat":  ("incubation_2_time_avg", "incubation_2_time_sd", "incubation_2_time_min",
                "read_min_incubation_repeat_hours"),
}


def _sample_incubation_minutes(env, spec_cfg, rng, kind):
    """Minutes this plate stays in the incubator.

    scheduled_reads_enabled=True : plates are not read before `read_min_incubation_*_hours`,
        and are then read at the NEXT scheduled slot. The slot (not an independent random
        duration) sets the finish time, so TATs cluster by time of day like real data.
    scheduled_reads_enabled=False: truncated lognormal with real mean/SD/floor/cap.
    """
    avg_k, sd_k, floor_k, read_min_k = _INCUBATION_KINDS[kind]
    if p.scheduled_reads_enabled:
        earliest = env.now + _tuned(env, spec_cfg, read_min_k) * 60.0
        return _next_read_time(earliest) - env.now
    return _truncated_lognormal(
        rng.np,
        _tuned(env, spec_cfg, avg_k) * 60.0,
        _tuned(env, spec_cfg, sd_k) * 60.0,
        _tuned(env, spec_cfg, floor_k) * 60.0,
        p.incubation_max_hours * 60.0,
    )


# ==================================================================================
# Positivity -> organisms -> repeat workup (each parameter is used exactly once)
# ==================================================================================
def _sample_num_colonies(spec_cfg, rng, is_blood):
    """Organism count for a POSITIVE specimen. P(>=2) = multiple_organism_rate; the 2/3/4
    split is conditional on >=2 (weights are renormalised)."""
    if rng.py.random() >= _rate(spec_cfg, "multiple_organism_rate"):
        return 1
    suffix = "_blood_percent" if is_blood else "_percent"
    w2 = _rate(spec_cfg, f"second_colony{suffix}")
    w3 = _rate(spec_cfg, f"third_colony{suffix}")
    w4 = _rate(spec_cfg, f"four_colony{suffix}")
    r = rng.py.random() * (w2 + w3 + w4)
    return 4 if r < w4 else 3 if r < w4 + w3 else 2


def _sample_repeat_workup_profile(spec_cfg, rng, num_organisms):
    """Called only for positive specimens. Returns (needs_workup, n_organisms_plated).
    monomicrobial_additional_workup_rate / polymicrobial_workup_required_rate mean exactly
    P(repeat workup | positive, mono/poly)."""
    n = max(1, int(num_organisms))
    if n == 1:
        needs = rng.py.random() < _rate(spec_cfg, "monomicrobial_additional_workup_rate")
        return needs, (1 if needs else 0)
    if rng.py.random() >= _rate(spec_cfg, "polymicrobial_workup_required_rate"):
        return False, 0
    if rng.py.random() < _rate(spec_cfg, "polymicrobial_all_organisms_worked_rate"):
        return True, n
    return True, rng.py.randint(1, n - 1)


def _colony_factor(n_organisms):
    return 1.0 + (n_organisms - 1) * p.colony_workup_time_factor


def _perform_repeat_workup_batch(env, spec_id, spec_type, spec_cfg, rng, resources, inventory, tracker,
                                 spec_priority, tech_key, n_organisms):
    """Subculture -> incubate to next read slot -> tech reads the plate."""
    if n_organisms <= 0:
        return True

    media_requirements = {k: v * n_organisms for k, v in spec_cfg["media_req"].items()}
    media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_requirements)
    if not media_allocated:
        return False

    tech_resource = resources[tech_key]
    with req_resource(tech_resource, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, EV.repeat_workup(n_organisms), env.now)
        yield env.timeout(rng.py.uniform(p.min_subculture_time, p.max_subculture_time) * _colony_factor(n_organisms))

    with resources["incubator"].request() as inc_req:
        yield inc_req
        tracker.log_event(spec_id, spec_type, EV.REPEAT_WORKUP_INCUBATION, env.now)
        yield env.timeout(_sample_incubation_minutes(env, spec_cfg, rng, "repeat"))

    # Previously missing: the tech has to read the subculture plate, which consumes tech time.
    with req_resource(tech_resource, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, EV.REPEAT_WORKUP_READ, env.now)
        yield env.timeout(rng.py.uniform(p.min_repeat_read_time, p.max_repeat_read_time) * _colony_factor(n_organisms))

    return True


def _run_workup_rounds(env, spec_id, spec_type, spec_cfg, rng, resources, inventory, tracker, spec_priority,
                       tech_key, batch_size, max_rounds, with_biochem):
    """Round 0 was already decided by the profile; later rounds use third/additional_workup_percent."""
    for rnd in range(max_rounds):
        if rnd > 0:
            chance = p.third_workup_percent if rnd == 1 else p.additional_workup_percent
            if rng.py.random() >= chance:
                break
        if with_biochem:
            tech = get_least_busy_tech(resources, "tech_routine", "tech_new")
            with req_resource(tech, spec_priority) as req:
                yield req
                tracker.log_event(spec_id, spec_type, EV.RAPID_BIOCHEM_SCREEN, env.now)
                yield env.timeout(rng.py.uniform(p.min_biochem_screen_time, p.max_biochem_screen_time) * batch_size)
                tracker.log_event(spec_id, spec_type, EV.DIRECT_BIOCHEM_DONE, env.now)
        ok = yield from _perform_repeat_workup_batch(
            env, spec_id, spec_type, spec_cfg, rng, resources, inventory, tracker,
            spec_priority, tech_key, batch_size)
        if not ok:
            return False
    return True


# ==================================================================================
# Pathways
# ==================================================================================
def _handle_blood_culture_path(env, spec_id, spec_type, spec_cfg, rng, resources, inventory, tracker,
                               spec_priority, priority_plating_store):
    """Bactec -> (positive bottles only) plate, BioFire, Gram stain, incubate. Returns True if the
    specimen continues to the Day-2 review."""
    is_blood_culture = spec_cfg.get("is_blood_culture", False) or spec_type.upper().startswith("BCX")
    is_body_fluid = spec_cfg.get("is_BodyFluid", False) or spec_type.upper().startswith("BODYFLUID")

    is_positive = yield from process_automated_bactec(env, spec_id, spec_type, spec_cfg, resources, tracker,
                                                      is_blood_culture, is_body_fluid)
    if not is_positive:
        tracker.log_event(spec_id, spec_type, EV.BACTEC_NEGATIVE, env.now)
        # Negatives are finished specimens and must count toward TAT.
        # Assumes process_automated_bactec waits the full protocol for negatives.
        tracker.log_event(spec_id, spec_type, EV.COMPLETED, env.now)
        return False
    tracker.log_event(spec_id, spec_type, EV.BACTEC_POSITIVE, env.now)

    media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type, spec_cfg["media_req"])
    if not media_allocated:
        tracker.log_event(spec_id, spec_type, EV.ABORTED, env.now)
        return False

    plating_done_event = env.event()
    yield priority_plating_store.put({
        'spec_id': spec_id,
        'spec_type': spec_type,
        'spec_cfg': spec_cfg,
        'priority': spec_priority,
        'done_event': plating_done_event,
        'accession_completed_at': env.now,
    })
    yield plating_done_event

    yield from process_BioFire(env, spec_id, spec_type, resources, tracker, spec_priority, "tech_blood")
    yield from process_GramStain(env, spec_id, spec_type, resources, tracker, spec_priority, "tech_blood")

    with resources["incubator"].request() as inc_req:
        yield inc_req
        tracker.log_event(spec_id, spec_type, EV.BLOOD_PLATE_INCUBATION, env.now)
        yield env.timeout(_sample_incubation_minutes(env, spec_cfg, rng, "blood"))
    return True


def _handle_direct_plating_path(env, spec_id, spec_type, spec_cfg, rng, resources, inventory, tracker,
                                spec_priority, plating_batcher):
    """Direct plating (urine, wound, stool, sputum, ...). Returns True if the specimen continues."""
    is_stool_culture = spec_cfg.get("is_stool", False) or spec_type.upper().startswith("STOOL")
    is_urine_culture = spec_cfg.get("is_urine", False) or spec_type.upper().startswith("URINE")

    use_automated_system = rng.py.random() < p.auto_plating_probability
    if (is_stool_culture or is_urine_culture) and use_automated_system:
        success = yield from process_automated_wasp(env, spec_id, spec_type, spec_cfg, inventory, tracker)
    else:
        success = yield from process_manual_plating(env, spec_id, spec_type, spec_cfg, resources, inventory,
                                                    tracker, spec_priority, plating_batcher)
    if not success:
        return False

    if is_stool_culture:
        tracker.log_event(spec_id, spec_type, EV.GN_BROTH_INCUBATION_START, env.now)
        yield env.timeout(6.0 * 60.0)
        tracker.log_event(spec_id, spec_type, EV.GN_BROTH_INCUBATION_DONE, env.now)

        with req_resource(resources["tech_plating"], spec_priority) as req:
            yield req
            with req_resource(resources["plating_bench"], spec_priority) as p_req:
                yield p_req
                tracker.log_event(spec_id, spec_type, EV.GN_BROTH_SUBCULTURE_START, env.now)
                media_allocated = yield from consume_media_inventory(env, inventory, tracker, spec_id, spec_type,
                                                                     {"HE_Agar": 1})
                if not media_allocated:
                    tracker.log_event(spec_id, spec_type, EV.ABORTED, env.now)
                    return False
                yield env.timeout(rng.py.uniform(2.0, 4.0))
                tracker.log_event(spec_id, spec_type, EV.GN_BROTH_SUBCULTURE_DONE, env.now)

    with resources["incubator"].request() as inc_req:
        yield inc_req
        tracker.log_event(spec_id, spec_type, EV.PRIMARY_INCUBATION, env.now)
        yield env.timeout(_sample_incubation_minutes(env, spec_cfg, rng, "primary"))
    return True


# ==================================================================================
# Specimen workflow
# ==================================================================================
def specimen_process(env, spec_id, spec_type, resources, inventory, tracker, active_counter,
                     routine_plating_store, priority_plating_store, accession_incoming_store,
                     plating_batcher):
    """The active counter is incremented here and decremented in `finally`, so every exit path
    (rejection, abort, early return, exception) is balanced without per-branch bookkeeping."""
    active_counter['count'] += 1
    try:
        yield from _specimen_workflow(env, spec_id, spec_type, resources, inventory, tracker,
                                      routine_plating_store, priority_plating_store,
                                      accession_incoming_store, plating_batcher)
    finally:
        active_counter['count'] -= 1


def _specimen_workflow(env, spec_id, spec_type, resources, inventory, tracker,
                       routine_plating_store, priority_plating_store, accession_incoming_store,
                       plating_batcher):
    arrival_time = env.now
    spec_cfg = SPECIMEN_TYPES[spec_type]
    rng = _SpecRng(env, spec_type, spec_id)
    flags = _get_specimen_flags(spec_type, spec_cfg)
    is_blood_culture = flags["is_blood_culture"]
    is_body_fluid = flags["is_body_fluid"]
    spec_priority = get_specimen_priority(spec_cfg)

    # ---- 1. arrival & pre-analytical rejection --------------------------------------
    tracker.log_event(spec_id, spec_type, EV.ARRIVED, env.now)
    if rng.py.random() < p.rejection_percent:
        tracker.log_event(spec_id, spec_type, EV.REJECTED, env.now)
        return

    # ---- 1c. accessioning -----------------------------------------------------------
    yield from process_accessioning(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority,
                                    arrival_time, routine_plating_store, accession_incoming_store)

    # ---- 2. primary pathway ---------------------------------------------------------
    if is_blood_culture or is_body_fluid:
        path_ok = yield from _handle_blood_culture_path(
            env, spec_id, spec_type, spec_cfg, rng, resources, inventory, tracker,
            spec_priority, priority_plating_store)
    else:
        path_ok = yield from _handle_direct_plating_path(
            env, spec_id, spec_type, spec_cfg, rng, resources, inventory, tracker,
            spec_priority, plating_batcher)
    if not path_ok:
        return

    # ---- 4. tech review (after first incubation) ------------------------------------
    tech_resource = get_tech_bench(spec_type, resources)
    with req_resource(tech_resource, spec_priority) as req:
        yield req
        tracker.log_event(spec_id, spec_type, EV.TECH_REVIEW, env.now)
        override_range = resolve_time_range_override(
            spec_cfg, "tech_review_range", sim_minutes=env.now,
            default_range=(p.min_tech_review_sub, p.max_tech_review_sub))
        min_time, max_time = override_range if override_range is not None else (p.min_tech_review_sub, p.max_tech_review_sub)
        yield env.timeout(rng.py.uniform(min_time, max_time))

    # 4B. stochastic re-incubation
    if rng.py.random() < p.reincubation_percent:
        with resources["incubator"].request() as reinc_req:
            yield reinc_req
            tracker.log_event(spec_id, spec_type, EV.EXTENDED_REINCUBATION, env.now)
            yield env.timeout(rng.py.uniform(p.min_reincubate_time * 60, p.max_reincubate_time * 60))

    # ---- 6a. day-2 outcome + repeat workup ------------------------------------------
    if is_blood_culture:
        with req_resource(resources["tech_blood"], spec_priority) as req:
            yield req
            tracker.log_event(spec_id, spec_type, EV.EVALUATE_BLOOD_SUBCULTURE, env.now)
            yield env.timeout(rng.py.uniform(p.min_subcultEval_time, p.max_subcultEval_time))

    # Bottle-based specimens were already gated by Bactec positivity: do NOT roll again.
    if is_blood_culture or is_body_fluid:
        positive_specimen = True
    else:
        positive_specimen = rng.py.random() < _rate(spec_cfg, "positive_specimen_rate")

    if not positive_specimen:
        tracker.log_event(spec_id, spec_type, EV.NO_SIGNIFICANT_GROWTH, env.now)
        tracker.log_event(spec_id, spec_type, EV.COMPLETED, env.now)   # negatives count toward TAT
        return

    num_colonies = _sample_num_colonies(spec_cfg, rng, is_blood_culture)
    if num_colonies >= 4:
        tracker.log_event(spec_id, spec_type, EV.MIXED_FLORA, env.now)

    needs_workup, batch_size = _sample_repeat_workup_profile(spec_cfg, rng, num_colonies)
    if not needs_workup:
        tracker.log_event(spec_id, spec_type, EV.POSITIVE_NO_WORKUP, env.now)
    else:
        ok = yield from _run_workup_rounds(
            env, spec_id, spec_type, spec_cfg, rng, resources, inventory, tracker, spec_priority,
            tech_key="tech_blood" if is_blood_culture else "tech_routine",
            batch_size=batch_size,
            max_rounds=p.max_subculture_limit_blood if is_blood_culture else p.max_subculture_limit_other,
            with_biochem=not is_blood_culture)
        if not ok:
            tracker.log_event(spec_id, spec_type, EV.ABORTED, env.now)
            return
        if batch_size > 1:
            tracker.log_event(spec_id, spec_type, EV.multi_organism_parallel(batch_size), env.now)

    # ---- 6b/6c. identification and AST, driven by the isolates actually present -----
    # Old logic: two independent per-specimen coin flips (MALDI 70%, Phoenix 40%) regardless of
    # how many organisms grew, and AST could happen with no ID. Now:
    #   isolates identified ~ Binomial(min(n_organisms, cap), maldi_testing_percent)
    #   isolates sent to AST ~ Binomial(isolates identified, Phoenix_test_percent)
    # `maldi_testing_percent` is therefore P(isolate is identified by MALDI | positive specimen) and
    # `Phoenix_test_percent` is P(AST | identified isolate). Re-estimate both from the LIS on that basis.
    n_candidates = min(num_colonies, p.max_isolates_identified)
    maldi_rate = _rate(spec_cfg, "maldi_testing_percent")
    n_identified = sum(rng.py.random() < maldi_rate for _ in range(n_candidates))
    if n_identified > 0:
        # NOTE: process_maldi_testing has no isolate-count argument, so it runs once per specimen.
        # Add an n_isolates parameter there if prep/run time should scale with n_identified.
        # yield from process_maldi_testing(env, spec_id, spec_type, resources, tracker, spec_priority)
        
        # NOTE: Pass n_identified to scale MALDI prep and run times
        yield from process_maldi_testing(
            env, spec_id, spec_type, resources, tracker, spec_priority, n_isolates = n_identified
        )


    phoenix_rate = _rate(spec_cfg, "Phoenix_test_percent")
    n_ast = sum(rng.py.random() < phoenix_rate for _ in range(n_identified))
    if n_ast > 0:
        yield from process_phoenix_testing(env, spec_id, spec_type, resources, tracker, spec_priority, n_ast)

    # ---- 10. complete ---------------------------------------------------------------
    tracker.log_event(spec_id, spec_type, EV.COMPLETED, env.now)
