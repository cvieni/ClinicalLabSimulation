"""Everything you are expected to edit for the policy optimizer lives here.

PLACEHOLDER COST NUMBERS BELOW ARE NOT YOUR LAB'S. Replace them before trusting a recommendation.
"""

# ---------------------------------------------------------------------------------------------
# 1. LEVERS the optimizer may change
#    staff       add/remove techs on one bench in one shift (applied to Weekday AND Weekend; floors at 0)
#    media       scale media stock policy (all media): fields listed are multiplied by the lever value
#    instrument  multiplier on the baseline capacity (Instrument_resources key)
#    param       a scalar parameter in params_d3.py (baseline read from the module)
#    context     NOT a decision: an uncertain future condition the policy must survive (volume multiplier)
#    Fewer levers = a better surrogate. Delete lines you do not want changed.
# ---------------------------------------------------------------------------------------------
LEVERS = [
    # --- staffing: bench, shift, lowest / highest change in head-count -----------------------
    {"kind": "staff", "bench": "tech_accession",         "shift": "Day",     "lo": -2, "hi": 2},
    {"kind": "staff", "bench": "tech_accession",         "shift": "Evening", "lo": -2, "hi": 2},
    {"kind": "staff", "bench": "tech_accession",         "shift": "Night",   "lo": -1, "hi": 2},
    {"kind": "staff", "bench": "tech_plating",           "shift": "Day",     "lo": -2, "hi": 2},
    {"kind": "staff", "bench": "tech_plating",           "shift": "Evening", "lo": -2, "hi": 2},
    {"kind": "staff", "bench": "tech_blood",             "shift": "Day",     "lo": -1, "hi": 1},
    {"kind": "staff", "bench": "tech_blood",             "shift": "Evening", "lo": -1, "hi": 1},
    {"kind": "staff", "bench": "tech_blood",             "shift": "Night",   "lo": -1, "hi": 1},
    {"kind": "staff", "bench": "tech_urine",             "shift": "Day",     "lo": -1, "hi": 1},
    {"kind": "staff", "bench": "tech_urine",             "shift": "Evening", "lo": -1, "hi": 1},
    {"kind": "staff", "bench": "tech_new",               "shift": "Day",     "lo": -1, "hi": 2},
    {"kind": "staff", "bench": "tech_new",               "shift": "Evening", "lo": -1, "hi": 2},
    {"kind": "staff", "bench": "tech_routine",           "shift": "Day",     "lo": -2, "hi": 2},
    {"kind": "staff", "bench": "tech_routine",           "shift": "Evening", "lo": -2, "hi": 2},
    {"kind": "staff", "bench": "tech_routine",           "shift": "Night",   "lo": 0,  "hi": 2},
    {"kind": "staff", "bench": "tech_stool",             "shift": "Day",     "lo": -1, "hi": 1},
    {"kind": "staff", "bench": "tech_float_accession",   "shift": "Day",     "lo": -2, "hi": 2},
    {"kind": "staff", "bench": "tech_float_accession",   "shift": "Evening", "lo": -1, "hi": 2},
    {"kind": "staff", "bench": "tech_float_accession",   "shift": "Night",   "lo": -2, "hi": 2},
    {"kind": "staff", "bench": "tech_float_newroutine",  "shift": "Day",     "lo": -1, "hi": 2},
    {"kind": "staff", "bench": "tech_float_newroutine",  "shift": "Evening", "lo": -1, "hi": 2},
    {"kind": "staff", "bench": "tech_float_newroutine",  "shift": "Night",   "lo": -2, "hi": 2},
    {"kind": "staff", "bench": "tech_supervisor",        "shift": "Day",     "lo": -1, "hi": 1},
    # --- media stock policy -------------------------------------------------------------------
    {"kind": "media", "name": "media_reorder_scale",   "fields": ["reorder_point", "initial"], "lo": 0.5, "hi": 3.0, "step": 0.1},
    {"kind": "media", "name": "media_order_qty_scale", "fields": ["order_qty"],                "lo": 0.5, "hi": 3.0, "step": 0.1},
    # --- instrument capacity (multiplier on today's capacity) ---------------------------------
    {"kind": "instrument", "name": "bc_instrument",      "lo": 0.9, "hi": 2.0, "step": 0.05},
    # --- process rules (scalar parameters in params_d3.py) ------------------------------------
    {"kind": "param", "name": "batch_size",                     "lo": 2, "hi": 12, "integer": True},
    {"kind": "param", "name": "float_accession_surge_backlog",  "lo": 3, "hi": 20, "integer": True},
    # --- uncertainty the policy must survive (NOT decided by the optimizer) -------------------
    {"kind": "context", "name": "volume_global", "lo": 1.0, "hi": 1.3},
]
# constraints are enforced at each of these context values (e.g. today's volume and +15 %)
CONTEXTS = [{"volume_global": 1.0}, {"volume_global": 1.15}]

# ---------------------------------------------------------------------------------------------
# 2. COST MODEL (per day) - PLACEHOLDERS
# ---------------------------------------------------------------------------------------------
TECH_COST_PER_HOUR = {"default": 45.0, "tech_supervisor": 60.0}
SHIFT_DIFFERENTIAL = {"Day": 1.0, "Evening": 1.10, "Night": 1.20}
DAYTYPE_WEIGHT = {"Weekday": 5 / 7, "Weekend": 2 / 7}      # share of days; makes cost a per-average-day number
MEDIA_HOLDING_RATE_PER_DAY = 0.002       # fraction of stocked media value carried per day (storage, waste, capital)
INSTRUMENT_COST_PER_UNIT_DAY = {"bc_instrument": 0.25, "default": 0.0}   # $ per unit of capacity per day

# ---------------------------------------------------------------------------------------------
# 3. CONSTRAINTS
# ---------------------------------------------------------------------------------------------
TARGET_TOLERANCE = 0.0      # P95 may be at most baseline x (1 + tol); 0 = "no worse than today"
TAT_TARGETS_HOURS = {}      # explicit P95 targets (hours) per sim type override the tolerance, e.g. {"BCx": 130, "Urine_Invasive": 72}
# low-volume types have noisy P95s; leaving them out of the constraints keeps the optimizer from chasing noise
EXCLUDE_TYPES = ["Wound_Genital", "Tissue_FNA", "Tissue_genital"]
UNFINISHED_ABS_MARGIN = 0.5  # unfinished % may exceed the baseline's by this many percentage points (also >= 1 %)
MIN_N_FOR_P95 = 10
