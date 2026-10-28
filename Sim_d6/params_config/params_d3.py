# params.py
import os
import json
import numpy as np
import scipy.stats as stats
import warnings


# ==============================================================================
# Load calibrated parameters from ARUP data
# ==============================================================================
file_dir = os.path.dirname(os.path.abspath(__file__))
# print("file_dir = ", file_dir)

# Sim root directory
PROJECT_ROOT = os.path.dirname(file_dir)
# print("PROJECT_ROOT = ", PROJECT_ROOT)

# Directory with ARUP_data (one above project root)
PARENT_DIR = os.path.dirname(PROJECT_ROOT)
# print("PARENT_DIR = ", PARENT_DIR)

json_year = 2025

json_dir = os.path.join(PARENT_DIR, "ARUP_data", f"json_clned_data_{json_year}")
# print("json_dir = ", json_dir)

# First define fallback time to positive params:
DEFAULT_TTP_PARAMS = {"shape": 0.55, "loc": 2.0, "scale": 20.0}
DEFAULT_MIN_TTP = 4.0
DEFAULT_MAX_TTP = 120.0

# Store TTP configurations per specimen type
TTP_CONFIGS = {
    "BloodCult": {
        "params": DEFAULT_TTP_PARAMS,
        "min_ttp_hrs": DEFAULT_MIN_TTP,
        "max_ttp_hrs": DEFAULT_MAX_TTP
    },
    "BodyFluid": {
        "params": DEFAULT_TTP_PARAMS,
        "min_ttp_hrs": DEFAULT_MIN_TTP,
        "max_ttp_hrs": DEFAULT_MAX_TTP
    }
}


# ---------------------------------------------------
# ---------------------------------------------------
# Specimen configurations to load
configs_to_load = {
    "BloodCult": f"BCx_{json_year}_calibrated_params.json",
    "BodyFluid": f"BodyFluid_{json_year}_calibrated_params.json",
}

# ---------------------------------------------------
# ---------------------------------------------------

# Set LABSIM_ALLOW_DEFAULT_TTP=1 to run on the UNCALIBRATED defaults above on purpose
# (e.g. a laptop without the ARUP_data folder). Otherwise a missing file is an error,
# because a run that silently uses defaults looks calibrated but is not.
ALLOW_DEFAULT_TTP = os.environ.get("LABSIM_ALLOW_DEFAULT_TTP", "0") == "0"
# ALLOW_DEFAULT_TTP = os.environ.get("LABSIM_ALLOW_DEFAULT_TTP", "0") == "1"


# Where each TTP config came from; stamp this into run outputs.
TTP_SOURCE = {}
loaded_data = {}


# ---------------------------------
# JSON load
# ---------------------------------
for specimen_key, filename in configs_to_load.items():
    json_path = os.path.join(json_dir, filename)

    ttp_section = {}
    if os.path.exists(json_path):
        with open(json_path, "r") as f:
            data = json.load(f)
        loaded_data[specimen_key] = data
        ttp_section = data.get("ttp_config", {})
    else:
        loaded_data[specimen_key] = {}

    if ttp_section:
        TTP_CONFIGS[specimen_key] = {
            "params": ttp_section.get("params", DEFAULT_TTP_PARAMS),
            "min_ttp_hrs": ttp_section.get("min_ttp_hrs", DEFAULT_MIN_TTP),
            "max_ttp_hrs": ttp_section.get("max_ttp_hrs", DEFAULT_MAX_TTP)
        }
    elif ALLOW_DEFAULT_TTP:
            TTP_SOURCE[specimen_key] = "DEFAULT (uncalibrated)"
            warnings.warn(f"Using UNCALIBRATED default TTP params for '{specimen_key}' "
                            f"(no usable ttp_config in {json_path}).")
    else:
        raise FileNotFoundError(
            f"No usable 'ttp_config' for '{specimen_key}' at {json_path}. "
            f"Fix the path, or set LABSIM_ALLOW_DEFAULT_TTP=1 to run on uncalibrated defaults."
        )

_warned_ttp_keys = set()
    
def sample_time_to_positive(specimen_type="BloodCult", rng=None):
    """
    Generates a Time-to-Positivity duration (in hours) sampled directly from 
    the fitted Log-Normal distribution for the given specimen type.
    
    Time-to-positivity (hours) from the fitted shifted lognormal, RESAMPLED into
    [min_ttp_hrs, max_ttp_hrs]. (The old np.clip piled probability mass into spikes at
    exactly 4 h and 120 h.) `rng` may be a numpy Generator for reproducible streams;
    the default uses the global np.random state.

    Equivalent to scipy lognorm(s, loc, scale).rvs() but without scipy's large per-call overhead:
        X = loc + scale * exp(s * Z),  Z ~ N(0, 1)
    """

    config = TTP_CONFIGS.get(specimen_type)
    if config is None:
        if specimen_type not in _warned_ttp_keys:
            _warned_ttp_keys.add(specimen_type)
            warnings.warn(f"No TTP config for '{specimen_type}'; using 'BloodCult'.")
        config = TTP_CONFIGS["BloodCult"]

    params = config["params"]
    s, loc, scale = params["shape"], params["loc"], params["scale"]
    lo, hi = config["min_ttp_hrs"], config["max_ttp_hrs"]
    src = np.random if rng is None else rng

    x = lo
    for _ in range(1000):
        x = loc + scale * src.lognormal(0.0, s)
        if lo <= x <= hi:
            return float(x)
    return float(np.clip(x, lo, hi))   # pathological parameters only

# ==============================================================================
# All other SIMULATION RUNTIME & CONTROL PARAMS
# ==============================================================================

# -------------------------
# Overall Simulation Parameters
# -------------------------
# sim_max_time = 31
sim_max_time = 43 # given 5 day warm up and 7 day cool down --> 43 - 5 - 7 = 31 total days
seed_input = 42

# -------------------------
# Measurement window (items: warm-up and right-censoring)
# -------------------------
# Metrics only use specimens that ARRIVED inside [warmup_days, sim_days - cooldown_days).
#  - warmup_days: the lab starts empty, so early specimens see no backlog. Ignored (0) when an
#    initial-conditions JSON is loaded, since that already seeds the backlog.
#  - cooldown_days: specimens arriving near the end cannot finish before the run stops, which
#    biases completed-only TAT low in the tail. Set it >= your longest realistic workup chain.
# The window is (sim_days - warmup - cooldown) long: with the defaults, use sim_days >= 37 for a
# 30-day measured window. n_incomplete_in_window in the run stats should be ~0.
warmup_days = 5.0
cooldown_days = 7.0
sim_start_weekday = 0     # sim t=0 is midnight on this weekday (0=Mon). Must match shift_manager.

# -------------------------
# Workflow Probability Rates
# -------------------------
reincubation_percent = 0.08
# Probability of plating stool or urine on the WASP (automatic plating vs. manual plating)
auto_plating_probability = 0.85

# -------------------------
# Shift Manager Module
# -------------------------
shift_1_start, shift_1_end = 7, 15
shift_2_start, shift_2_end = 15, 23

# Shift break
break1_wind_min = 30
break1_wind_max = 90

# -------------------------
# Run_simulation Module & class BatchAccumulator
# -------------------------
# Variable for how many plates a tech waits for to take a "batch" of plates
batch_size=10
# If a batch is taking more then max_wait time, tech takes all available plates for workup
max_wait=10


# ==============================================================================
# Operational/Global Parameters
# ==============================================================================
# 1. preprocessing -----
rejection_percent = 0.02      # 2% of samples are rejected before processing

# 2. Check and consume inventory
inventory_stockout_recheck = 480 # recheck delivery

# 3. Blood Culture / body fluid positivity Rates
BCx_positivity = 0.10
BdyFlid_positivity = 0.10
# avg_time2posBcx = 18.0
# std_time2posBcx = 6.0

# time 2 positive for body fluid is in ***hours***
avg_time2posBdyFld = 20 #
std_time2posBdyFld = 10.0

# ------------------------------------------------------------------------------
# Plate incubation / reading (item 5 and 5b)
# ------------------------------------------------------------------------------
# MODEL A (default): plates are read on a schedule. A plate is not read before
# read_min_incubation_*_hours and is then read at the NEXT slot in plate_read_hours_*.
# Slot hours are hours-of-day (7.5 = 07:30). PLACEHOLDERS: set from the time-of-day histogram of
# your LIS "plate read" / "Day-2 review" timestamps.
scheduled_reads_enabled = True
plate_read_hours_weekday = (7.0, 15.0)
plate_read_hours_weekend = (8.0,)
read_min_incubation_primary_hours = 16.0   # direct-plated routine specimens
read_min_incubation_blood_hours = 16.0     # BCx / body-fluid subculture plates
read_min_incubation_repeat_hours = 12.0    # repeat-workup subcultures (5b)

# MODEL B (scheduled_reads_enabled=False): independent random duration. avg/sd are the real mean
# and SD (hours); *_min is a TRUE floor; incubation_max_hours is a cap. Draws are resampled into
# [min, max], not clipped. (Before, "*_std" was used as the floor and SD was hard-coded to 120 min.)
incubation_1_time_avg = 18.0   # blood / body fluid plate
incubation_1_time_sd = 4.0
# incubation_1_time_sd = 6.0
# incubation_1_time_min = 6.0
incubation_2_time_avg = 18.0   # repeat workup plate
incubation_2_time_sd = 2.0
# incubation_2_time_sd = 6.0
# incubation_2_time_min = 6.0

# Routine Urine, Wound, Tissu
avg_incubation_time_Other = 16.0   # routine direct plating
std_incubation_time_Other = 6.0
min_incubation_time_Other = 12.0
incubation_max_hours = 48.0

# min_subcult_incbtion_time_Bcx = 18.0 # in hours


# ==============================================================================
# Tech/Runtime Parameters
# ==============================================================================
# Extra time per additional colony worked in one batch: time = base * (1 + (n-1) * factor).
# The comment used to say "35% more" but the value was 1.25 (4 colonies = 4.75x). Set to match the
# comment. If 1.25 was deliberate / tuned, put it back.
# if more colonies then require 35% more time for workup
colony_workup_time_factor = 0.35
# colony_workup_time_factor = 1.25

# Per-ISOLATE semantics now (see specimen_process): P(isolate identified by MALDI | positive specimen)
# and P(AST | identified isolate). At most max_isolates_identified isolates per specimen are
# identified (4+ organisms = mixed flora).
max_isolates_identified = 3

# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# 2. Tech touch time during accessioning
# touch_time_min = 0.5
# touch_time_max = 1.5
# # touch_time_max = 3.0
# bld_touch_time_min = 0.5
# bld_touch_time_max = 2.0
accession_batch_max_wait_minutes = 10.0
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!


# Time to perform Misc testing
gram_stain_time = 5.0
min_BioFire_screen_time = 0.5
max_BioFire_screen_time = 5.0
min_biochem_screen_time = 5.0 # minutes
max_biochem_screen_time = 20.0 # minutes
mean_biochem_screen_time = 10.0

# Phenix & MALDI workup
phoenix_max_wait = 12 * 60 # wait 12 hours max before timing out phoenix
maldi_testing_percent = 0.70
Phoenix_test_percent = 0.4
min_MALDI_prep_time = 15.0
max_MALDI_prep_time = 60.0
MALDI_runtime = 20.0  # in minutes
MALDI_runtime_per_colony = 0.15  # ~20 seconds per run?
min_PHENIXprep_time = 5.0
max_PHENIXprep_time = 15.0
phoenix_run_time_hours = 6.0 # in hours

# Time to set up a plate ------
avg_plating_time = 3.0
plating_std_time = 1.0
min_plating_time = 0.5
max_plating_time = 3.0

# Amount of time that it takes the WASP to plate a sample (before taking an incubation spot)
automatic_plating_time_min = 1.0
automatic_plating_time_max = 3.0
wasp_load_time_max =  0.25 # time to load plate into the wasp

min_allowed_incubation = 300 # in minutes

# 6. Subcultring:
subculture_count = 0
min_subcultEval_time = 0.5
max_subcultEval_time = 1.5
min_subculture_time = 0.05
max_subculture_time = 3.0
# Tech time to read a repeat-workup plate after 5b incubation (minutes, per plate-batch)
min_repeat_read_time = 0.5
max_repeat_read_time = 3.0


# ============================================================================== 
# Repeat subculture / work-up calibration against observed LIS data
# ============================================================================== 
# This hierarchy matches the pattern you described:
#   X% of specimens are culture-positive
#   Y% of positive specimens have multiple organisms
#   Z% of positive / multi-organism specimens require repeat workup
# These defaults are intentionally tunable and should be replaced with observed LIS
# estimates once your monthly summary data is reviewed.
#
# The workup logic is now explicit for three different scenarios:
#   1) positive specimen -> polymicrobial -> multiple organisms require workup
#   3) positive specimen -> polymicrobial -> not all organisms are worked up
#   2) positive specimen -> monomicrobial -> additional workup still possible
positive_specimen_rate = 0.12      # X: proportion of specimens that are culture-positive
multiple_organism_rate = 0.20      # Y: proportion of positive specimens with >1 organism

# workup_required_rate = 0.30        # Z: proportion of positive / multi-organism samples that need repeat workup

monomicrobial_additional_workup_rate = 0.15  # positive monomicrobial specimens that still need a follow-up workup
polymicrobial_workup_required_rate = 0.25    # positive polymicrobial specimens that require additional workup
polymicrobial_all_organisms_worked_rate = 0.65  # fraction of polymicrobial workups that plate all organisms, not just a subset

# Legacy distributional probabilities retained for compatibility with the existing
# specimen workflow. They are interpreted as the underlying distribution driving the
# above three-stage calibration layer.
second_colony_blood_percent = 0.12
third_colony_blood_percent = 0.05
four_colony_blood_percent = 0.01

second_colony_percent = 0.20
third_colony_percent = 0.1
four_colony_percent = 0.05


# -------- Need to subculture
# number of times bloods can be subcultured
max_subculture_limit_blood = 2
max_subculture_limit_other = 3
# chance of setting up a 2nd or third subculture (after first culture from primary specimen)
second_workup_percent = 0.35  # Day 2: initial repeat workup probability
third_workup_percent = 0.10  # Day 3: second-stage workup probability
additional_workup_percent = 0.02  # additional repeat workups if there are multiple isolates
# second_workup_percent = 0.80  # Day 2: initial repeat workup probability
# third_workup_percent = 0.05  # Day 3: second-stage workup probability
# additional_workup_percent = 0.01 # additional repeat workups

# 5. Tech Review
min_tech_review_sub = 1.0
max_tech_review_sub = 5.0
min_reincubate_time = 1.0
max_reincubate_time = 6.0

# Shift variables:
handoff_time = 10 # minutes