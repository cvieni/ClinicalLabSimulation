"""Literature task and process times (Gerada et al. 2024, tables kept in params_d3.py) as samplers.

Table 1 (bench tasks) : p.<task>_task_time (median/IQR, MINUTES)   and p.<task>_distrib fitted in SECONDS
Table 2 (process steps): p.<step>_process_time (median, own unit) and p.<step>_distrib fitted in MINUTES
Distributions: uniform(a, b) | lognormal(mean, sd on the LOG scale) | gamma(shape, rate) | weibull(shape, scale)

`python -m modules.literature_times` prints, for every fitted distribution, the median it implies next to the median reported in the
paper, so the unit assumption above is checked against your own numbers (a large ratio = wrong unit or a transcription error).

Use in the sim: gram_stain_minutes(rng) is called by process_GramStain when p.use_literature_task_times is True.
"""
import math

import params_config.params_d3 as p

TABLE1 = ("label_with_lab_number", "lims", "combine_labels", "scan_request_form", "move_location", "load_onto_analyzer",
          "unload_from_analyzer", "hazard_check", "vent_sample", "prep_initial_culture_smear", "gram_stain_smear",
          "dry_gram_smear", "read_report_gram_smear")
TABLE2 = ("collection_receipt", "receipt_load_incubator", "load_incubator_flag_positive", "flag_positive_unload",
          "unload_gram_stain", "gram_stain_24h_report", "report_24h_48h_report", "report_48h_final_report")
GRAM_SMEAR_TASKS = ("prep_initial_culture_smear", "gram_stain_smear", "dry_gram_smear", "read_report_gram_smear")
# blood-culture chain, receipt -> final report (minutes). load->flag-positive is the TTP your lab calibrated (TTP_CONFIGS), so it is
# NOT drawn here unless include_ttp=True.
BCX_CHAIN = ("receipt_load_incubator", "load_incubator_flag_positive", "flag_positive_unload", "unload_gram_stain",
             "gram_stain_24h_report", "report_24h_48h_report", "report_48h_final_report")
_UNIT_TO_MIN = {"minutes": 1.0, "hours": 60.0, "days": 1440.0}


def _dist(name):
    return getattr(p, f"{name}_distrib")


def draw(d, rng):
    """one draw in the distribution's own unit (seconds for Table 1, minutes for Table 2)"""
    k = d["distribution"]
    if k == "uniform":
        return rng.uniform(d["a"], d["b"])
    if k == "lognormal":
        return math.exp(rng.gauss(d["mean"], d["sd"]))
    if k == "gamma":
        return rng.gammavariate(d["shape"], 1.0 / d["rate"])
    if k == "weibull":
        return rng.weibullvariate(d["scale"], d["shape"])
    raise ValueError(f"unknown distribution '{k}'")


def median_of(d):
    """median of the fitted distribution, own unit"""
    k = d["distribution"]
    if k == "uniform":
        return (d["a"] + d["b"]) / 2
    if k == "lognormal":
        return math.exp(d["mean"])
    if k == "weibull":
        return d["scale"] * math.log(2) ** (1 / d["shape"])
    if k == "gamma":                                   # numeric bisection on the regularised incomplete gamma (no scipy needed)
        from scipy.stats import gamma
        return float(gamma.ppf(0.5, d["shape"], scale=1 / d["rate"]))
    raise ValueError(k)


def task_minutes(name, rng):
    """Table 1 bench task, minutes"""
    return draw(_dist(name), rng) / 60.0


def process_minutes(name, rng):
    """Table 2 process step, minutes"""
    return draw(_dist(name), rng)


def gram_stain_minutes(rng):
    """One Gram stain of one isolate: prepare smear + stain + dry + read/report (Table 1), minutes."""
    return sum(task_minutes(t, rng) for t in GRAM_SMEAR_TASKS)


def bcx_chain_hours(rng, include_ttp=True, hub=True):
    """Receipt -> final report for a positive blood culture, hours (one random draw per step)."""
    steps = [s for s in BCX_CHAIN if include_ttp or s != "load_incubator_flag_positive"]
    if not hub:
        steps = [("unload_gram_stain_satellite" if s == "unload_gram_stain" else s) for s in steps]
    return sum(process_minutes(s, rng) for s in steps) / 60.0


def check_units():
    rows = []
    for t, names, to_min, unit_in in ((1, TABLE1, 1 / 60.0, "s"), (2, TABLE2 + ("unload_gram_stain_hub", "unload_gram_stain_satellite"), 1.0, "min")):
        for n in names:
            rep = getattr(p, f"{n}_task_time" if t == 1 else f"{n}_process_time")
            rep_min = rep["median"] * (1.0 if t == 1 else _UNIT_TO_MIN[rep["unit"]])
            fit_min = median_of(_dist(n)) * to_min
            rows.append((f"T{t}", n, rep_min, fit_min, fit_min / rep_min))
    return rows


if __name__ == "__main__":
    print(f"{'':3}{'step':36}{'reported median (min)':>22}{'fitted median (min)':>21}{'ratio':>7}")
    for t, n, r, f, q in check_units():
        print(f"{t:3}{n:36}{r:22.2f}{f:21.2f}{q:7.2f}{'   <-- check' if not 0.7 <= q <= 1.4 else ''}")
