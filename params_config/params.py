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
second_workup_percent = 0.80  
third_workup_percent = 0.05
additional_workup_percent = 0.01

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
inventory_stockout_recheck = 300 # recheck delivery every 6 hours
# 3. Blood Culture / body fluid positivity 
BCx_positivity = 0.10
BdyFlid_positivity = 0.10
avg_time2posBcx = 18.0
std_time2posBcx = 6.0
avg_time2posBdyFld = 20
std_time2posBdyFld = 10.0


incubation_1_time_min = 20 # Hours 
incubation_1_time_avg = 26 # Hours 

min_subcult_incbtion_time_Bcx = 18.0 # in hours


# 3B. Routine Urine, Wound, Tissu
min_incubation_time_Other = 6.0


avg_plating_time = 3.0
plating_std_time = 1.0
min_plating_time = 0.5
max_plating_time = 8.0

min_allowed_incubation = 300 # in minutes

# 6. Subcultring:
min_subcultEval_time = 0.5
max_subcultEval_time = 1.5
min_subculture_time = 1.0
max_subculture_time = 3.0

# 5. Tech Review
min_tech_review_sub = 2.0
max_tech_review_sub = 5.0
min_reincubate_time = 4.0
max_reincubate_time = 12.0

# Phenix & MALDI workup
maldi_testing_percent = 0.6
Phoenix_test_percent = 0.9
min_MALDIprep_time = 15.0
max_MALDIprep_time = 60.0
MALDI_runtime = 10.0  # in minutes
min_PHENIXprep_time = 5.0
max_PHENIXprep_time = 15.0
phoenix_run_time_hours = 6.0 # in hours

# Shift variables:
handoff_time = 15 # minutes