# params.py
import os
import json
import numpy as np
import scipy.stats as stats

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

json_dir = os.path.join(PARENT_DIR, "ARUP_data", "json_clned_data")
# print("json_dir = ", json_dir)



params_to_load = {
    "BloodCult": "BCx_2024_calibrated_params.json",
    "BodyFluid": "BodyFluid_2024_calibrated_params.json",
}

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

# Specimen configurations to load
configs_to_load = {
    "BloodCult": "BCx_2024_calibrated_params.json",
    "BodyFluid": "BodyFluid_2024_calibrated_params.json",
}

loaded_data = {}

# ---------------------------------
# JSON load
# ---------------------------------
for specimen_key, filename in configs_to_load.items():
    json_path = os.path.join(json_dir, filename)
    
    if os.path.exists(json_path):
        with open(json_path, "r") as f:
            data = json.load(f)
            loaded_data[specimen_key] = data
            
            # Extract TTP parameters if defined in JSON, else keep fallback
            ttp_section = data.get("ttp_config", {})
            if ttp_section:
                TTP_CONFIGS[specimen_key] = {
                    "params": ttp_section.get("params", DEFAULT_TTP_PARAMS),
                    "min_ttp_hrs": ttp_section.get("min_ttp_hrs", DEFAULT_MIN_TTP),
                    "max_ttp_hrs": ttp_section.get("max_ttp_hrs", DEFAULT_MAX_TTP)
                }
    else:
        print(f"Config: WARNING - Required JSON for '{specimen_key}' not found at {json_path}")
        print(f"--> Using default fallback TTP params for {specimen_key}")
        loaded_data[specimen_key] = {}


    
def sample_time_to_positive(specimen_type="BloodCult"):
    """
    Generates a Time-to-Positivity duration (in hours) sampled directly from 
    the fitted Log-Normal distribution for the given specimen type.
    
    Supports: "BloodCult", "BodyFluid" (falls back to default if key missing).
    """
    config = TTP_CONFIGS.get(specimen_type, TTP_CONFIGS["BloodCult"])
    params = config["params"]
    
    ttp_hours = stats.lognorm.rvs(
        s=params.get("shape", 0.55),
        loc=params.get("loc", 2.0),
        scale=params.get("scale", 20.0)
    )
    
    # Clip extreme statistical outliers to match observed bounds
    return float(np.clip(ttp_hours, a_min=config["min_ttp_hrs"], a_max=config["max_ttp_hrs"]))

# ==============================================================================
# All other SIMULATION RUNTIME & CONTROL PARAMS
# ==============================================================================

# -------------------------
# Overall Simulation Parameters
# -------------------------
sim_max_time = 31
seed_input = 42

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
# Biofire Setup & Gram Stain time

# Incubation times
incubation_1_time_std = 6.0 # Hours 
incubation_1_time_avg = 18 # Hours 
incubation_2_time_std = 6.0 # Hours
incubation_2_time_avg = 18

min_subcult_incbtion_time_Bcx = 18.0 # in hours
# 3B. Routine Urine, Wound, Tissu
avg_incubation_time_Other = 16.0 
std_incubation_time_Other = 6.0

# ==============================================================================
# Tech/Runtime Parameters
# ==============================================================================
# if more colonies then require 35% more time for workup
colony_workup_time_factor = 1.25

# 2. Tech touch time during accessioning
touch_time_min = 1.0
touch_time_max = 4.0
# touch_time_max = 3.0
bld_touch_time_min = 0.5
bld_touch_time_max = 2.0
accession_batch_max_wait_minutes = 10.0

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
min_subculture_time = 0.0
max_subculture_time = 3.0



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
workup_required_rate = 0.30        # Z: proportion of positive / multi-organism samples that need repeat workup

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