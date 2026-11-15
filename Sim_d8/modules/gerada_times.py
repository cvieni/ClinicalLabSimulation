"""Gerada et al. 2024 task times (params_d3 Table 1), one function per step, in MINUTES.

    step_minutes("gram_stain_smear")                    -> one draw for ONE batch of the step (what Gerada timed)
    step_minutes("label_with_lab_number", per_specimen=True)  -> that draw divided by the paper's mean batch size

Why per_specimen: Table 1 times are per BATCH (labels were applied to ~5.6 specimens at once, a Gram stain is ~1.1
slides, ...). The sim handles one specimen at a time, so batch steps are divided by the mean batch size.

Sampling (p.gerada_sampling):
  "iqr_lognormal" (default)  lognormal with the published median and IQR. Always in minutes, never a unit problem.
  "fitted"                   the fitted distribution in <step>_distrib (lognormal/gamma/uniform are in SECONDS).
                             The fitted uniforms for label / lims / combine_labels / scan_request_form do NOT reproduce
                             the published medians (off by 56-79 %), which is why the default is the IQR lognormal.
Draws are capped at p.gerada_cap_multiple (default 10) x the median so a lognormal tail cannot produce an hour-long label.
"""
import math
import random as _random
import params_config.params_d3 as p

# mean batch size per step, from the Table 1 comments in params_d3 (1.0 where the paper reports single items)
GERADA_BATCH_SIZE = {
    "label_with_lab_number": 5.59, "lims": 5.59, "combine_labels": 3.53, "scan_request_form": 4.29,
    "move_location": 5.24, "load_onto_analyzer": 4.63, "unload_from_analyzer": 1.17, "hazard_check": 1.15,
    "vent_sample": 1.13, "prep_initial_culture_smear": 1.13, "gram_stain_smear": 1.13, "dry_gram_smear": 1.13,
    "read_report_gram_smear": 1.00,
}
_Z75 = 0.6745          # standard-normal 75th percentile


def _spec(step):
    tt = getattr(p, f"{step}_task_time", None)
    if tt is None:
        raise AttributeError(f"params_d3 has no {step}_task_time (Gerada Table 1)")
    return tt


def _iqr_lognormal(rng, tt):
    med, q1, q3 = tt["median"], tt.get("iqr_min"), tt.get("iqr_max")
    sigma = (math.log(q3) - math.log(q1)) / (2 * _Z75) if q1 and q3 else 0.4
    return rng.lognormvariate(math.log(med), sigma)


def _fitted(rng, step):
    d = getattr(p, f"{step}_distrib", None)
    if d is None:
        raise AttributeError(f"params_d3 has no {step}_distrib")
    kind = d["distribution"]
    if kind == "lognormal":
        return rng.lognormvariate(d["mean"], d["sd"]) / 60.0            # log-seconds -> minutes
    if kind == "gamma":
        return rng.gammavariate(d["shape"], 1.0 / d["rate"]) / 60.0      # rate per second
    if kind == "uniform":
        return rng.uniform(d["a"], d["b"]) / 60.0
    raise ValueError(f"unsupported distribution '{kind}' for {step}")


def step_minutes(step, rng=None, per_specimen=False):
    rng = rng or _random
    tt = _spec(step)
    if getattr(p, "gerada_sampling", "iqr_lognormal") == "fitted":
        x = _fitted(rng, step)
    else:
        x = _iqr_lognormal(rng, tt)
    x = min(x, float(getattr(p, "gerada_cap_multiple", 10.0)) * tt["median"])
    if per_specimen:
        x /= float(getattr(p, f"{step}_batch_size_mean", GERADA_BATCH_SIZE.get(step, 1.0)))
    return x


def steps_minutes(steps, rng=None, per_specimen=False):
    """[(step, minutes), ...] in order."""
    return [(s, step_minutes(s, rng, per_specimen)) for s in steps]


def step_weight(step):
    """Published median per specimen (task time / mean batch size), minutes. Used only as a RELATIVE weight to split a
    LIS-calibrated total across steps."""
    return _spec(step)["median"] / float(getattr(p, f"{step}_batch_size_mean", GERADA_BATCH_SIZE.get(step, 1.0)))
