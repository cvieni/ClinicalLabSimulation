# ==============================================================================
# DEFAULT SIMULATION RUNTIME & CONTROL PARAMS
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
max_wait=15


# -------------------------
# specimen_process module
# -------------------------
# 1. preprocessing -----
rejection_percent = 0.02      # 2% of samples are rejected before processing
# 2. Check and consume inventory
inventory_stockout_recheck = 480 # recheck delivery

# 3. Blood Culture / body fluid positivity 
BCx_positivity = 0.10
BdyFlid_positivity = 0.10
avg_time2posBcx = 18.0
std_time2posBcx = 6.0
avg_time2posBdyFld = 20
std_time2posBdyFld = 10.0
# Biofire Setup & Gram Stain time
min_biochem_screen_time = 5.0 # minutes
max_biochem_screen_time = 10.0 # minutes

incubation_1_time_std = 6.0 # Hours 
incubation_1_time_avg = 24 # Hours 
incubation_2_time_std = 6.0 # Hours
incubation_2_time_avg = 24
min_subcult_incbtion_time_Bcx = 18.0 # in hours

# 3B. Routine Urine, Wound, Tissu
avg_incubation_time_Other = 24.0
std_incubation_time_Other = 6.0

avg_plating_time = 3.0
plating_std_time = 1.0
min_plating_time = 0.5
max_plating_time = 3.0

min_allowed_incubation = 300 # in minutes

# 6. Subcultring:
min_subcultEval_time = 0.5
max_subcultEval_time = 1.5
min_subculture_time = 0.0
max_subculture_time = 3.0
# if more colonies then require 75% more time for workup
colony_workup_time_factor = 1.75


# Need for multiple colony workup
second_colony_blood_percent = 0.1
third_colony_blood_percent = 0.01
four_colony_blood_percent = 0.001

second_colony_percent = 0.4
third_colony_percent = 0.2
four_colony_percent = 0.05

# -------- Need to subculture
# number of times bloods can be subcultured
max_subculture_limit_blood = 2
max_subculture_limit_other = 3
# chance of setting up a 2nd or third subculture (after first culture from primary specimen)
second_workup_percent = 0.80  # Day 2
third_workup_percent = 0.05 # Day 3
additional_workup_percent = 0.01

# 5. Tech Review
min_tech_review_sub = 2.0
max_tech_review_sub = 5.0
min_reincubate_time = 1.0
max_reincubate_time = 6.0

# Phenix & MALDI workup
maldi_testing_percent = 0.6
Phoenix_test_percent = 0.5
min_MALDI_prep_time = 15.0
max_MALDI_prep_time = 60.0
MALDI_runtime = 20.0  # in minutes

min_PHENIXprep_time = 5.0
max_PHENIXprep_time = 15.0
phoenix_run_time_hours = 6.0 # in hours

# Shift variables:
handoff_time = 15 # minutes


# non-variable params / initialization
subculture_count = 0
phoenix_max_wait = 240 # minutes