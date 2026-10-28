import os
import json
import numpy as np


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


# ---------------------------------
# JSON load
# ---------------------------------

# Map of variable name / label -> JSON filename
configs_to_load = {
    # Automated Reader speciments ------
    "BloodCult": f"BCx_{json_year}_calibrated_params.json",
    "BodyFluid": f"BodyFluid_{json_year}_calibrated_params.json",

    # Manual Plating specimens ------------
    "Bone": f"Bone_{json_year}_calibrated_params.json",
    "Urine_Inv": f"InvUrine_{json_year}_calibrated_params.json",
    "Urine_NonInv": f"NonInv_Urine_{json_year}_calibrated_params.json",
    "Resp_NonCF": f"Respiratory_NonCF_{json_year}_calibrated_params.json",
    "Resp_CF": f"Respiratory_CF_{json_year}_calibrated_params.json",
    "Stool": f"Stool_{json_year}_calibrated_params.json",
    "Tissue_genital": f"Tiss_genital_{json_year}_calibrated_params.json",
    "Tissue_FNA": f"Tiss_FNA_{json_year}_calibrated_params.json",
    "Tissue_other": f"TissueCleaned_{json_year}_calibrated_params.json",
    "Wound_genital": f"Wound_genital_{json_year}_calibrated_params.json",
    "Wound_other": f"Wound_Cleaned_{json_year}_calibrated_params.json",
}

loaded_data = {}

for specimen_key, filename in configs_to_load.items():
    json_path = os.path.join(json_dir, filename)
    
    if os.path.exists(json_path):
        with open(json_path, "r") as f:
            loaded_data[specimen_key] = json.load(f)
    else:
        print(f"Config.py: ERROR - Required JSON for {specimen_key} not found at {json_path}")
        loaded_data[specimen_key] = {}

# Helper function to eliminate repetitive dict lookups safely
def get_param(key, param_name):
    return loaded_data[key][param_name]

# In params_config/specimen_config_helperfunctions.py

# def get_param(key, param_name, default=None):
#     """Retrieve a parameter from loaded_data, checking both root level 
#     and common nested dictionary wrappers (e.g. 'params', 'specimen_metrics').
#     """
#     if key not in loaded_data:
#         if default is not None:
#             return default
#         raise KeyError(f"Specimen key '{key}' not found in loaded_data.")

#     data = loaded_data[key]

#     # 1. Check top-level root
#     if param_name in data:
#         return data[param_name]

#     # 2. Check common nested keys
#     nested_keys = ["params", "ttp_config", "specimen_metrics", "volume_metrics", "config"]
#     for nested in nested_keys:
#         if nested in data and isinstance(data[nested], dict) and param_name in data[nested]:
#             return data[nested][param_name]

#     # 3. Fallback or raise clear informative error
#     if default is not None:
#         return default

#     raise KeyError(
#         f"Parameter '{param_name}' for '{key}' not found at root or within nested blocks "
#         f"({nested_keys}) in JSON. Found top-level keys: {list(data.keys())}"
#     )

def get_accession_config(specimen_key):
    return loaded_data[specimen_key].get("accession_time_config", {})


# ------------------ TEMP -------------------------------
# Helper function to generate a valid empirical bin structure for missing/uncalibrated specimens
def create_fallback_accession_config(min_min=1.0, max_min=5.0, mean_min=3.0, std_min=1.0):
    edges = np.linspace(min_min, max_min, 11)
    probs = np.full(10, 0.1)  # Uniform probability across 10 bins
    return {
        "units": "minutes",
        "min_accession_min": float(min_min),
        "max_accession_min": float(max_min),
        "mean_accession_min": float(mean_min),
        "std_accession_min": float(std_min),
        "lognormal_sigma": 0.5,
        "lognormal_mu": float(np.log(mean_min)),
        "bin_probabilities": probs.tolist(),
        "bin_edges": edges.round(3).tolist()
    }

# Add these entries to your SPECIMEN_TYPES dictionary in config.py:

# ------------------ TEMP -------------------------------
# ------------------ TEMP -------------------------------

# Specifically to extract log normal curves from json files
def extract_lognormal_config(
    loaded_data: dict,
    specimen_key: str,
    config_key: str = "ttp_config",
) -> dict:
    """Extracts Scipy lognormal parameters and bounds strictly from loaded JSON data.
    Fails immediately with KeyError if structural paths do not exist.
    """
    sub_config = loaded_data[specimen_key][config_key]
    params = sub_config["params"]

    shape = float(params["shape"])
    scale = float(params["scale"])
    loc = float(params["loc"])

    if scale <= 0:
        raise ValueError(
            f"Invalid scale parameter ({scale}) for specimen '{specimen_key}' in '{config_key}'"
        )

    return {
        "distribution": "lognormal",
        "lognormal_mu": float(np.log(scale)),
        "lognormal_sigma": shape,
        "loc": loc,
        "min_hours": float(sub_config["min_ttp_hrs"]),
        "max_hours": float(sub_config["max_ttp_hrs"]),
    }


def get_shift_label_for_hour(hour: int | float | None) -> str:
    """Map a clock hour to the lab's operational shift label."""
    if hour is None:
        return "Day"
    hour_int = int(hour)
    if 7 <= hour_int < 15:
        return "Day"
    if 15 <= hour_int < 23:
        return "Evening"
    return "Night"


def get_shift_label_for_time(sim_minutes=None, hour=None) -> str:
    """Return 'Day', 'Evening', or 'Night' from either a sim-minute clock or an hour value."""
    if sim_minutes is not None:
        hour = int((sim_minutes % (24 * 60)) // 60)
    return get_shift_label_for_hour(hour)


def resolve_specimen_tuning_value(spec_cfg, tuning_key, sim_minutes=None, hour=None):
    """Read a specimen-specific, time-of-day override if one is explicitly configured.

    This intentionally avoids silent fallback values. If the override is not defined in the
    specimen configuration for the active shift, the caller must explicitly decide whether to
    use the global default or keep the value unset.
    """
    if not isinstance(spec_cfg, dict):
        return None

    tuning_overrides = spec_cfg.get("tuning_overrides") or {}
    if not isinstance(tuning_overrides, dict) or not tuning_overrides:
        return None

    shift_label = get_shift_label_for_time(sim_minutes=sim_minutes, hour=hour)
    shift_cfg = tuning_overrides.get(shift_label, {})
    if tuning_key in shift_cfg:
        return shift_cfg[tuning_key]
    return None


def resolve_time_range_override(spec_cfg, tuning_key, sim_minutes=None, default_range=None, hour=None):
    """Resolve a min/max duration override for a specific specimen and shift.

    If the override is not configured, callers must explicitly provide a default range.
    There is no hidden fallback to a hard-coded default.
    """
    override = resolve_specimen_tuning_value(spec_cfg, tuning_key, sim_minutes=sim_minutes, hour=hour)
    if override is None:
        if default_range is None:
            return None
        return tuple(default_range)

    if isinstance(override, dict):
        if "min" in override and "max" in override:
            return (float(override["min"]), float(override["max"]))
        if "low" in override and "high" in override:
            return (float(override["low"]), float(override["high"]))

    if isinstance(override, (list, tuple)) and len(override) == 2:
        return (float(override[0]), float(override[1]))

    if isinstance(override, (int, float)):
        if default_range is None:
            return None
        lo, hi = default_range
        factor = float(override)
        if factor <= 0:
            return tuple(default_range)
        return (float(lo) * factor, float(hi) * factor)

    return tuple(default_range) if default_range is not None else None


SPECIMEN_KEY_ALIASES = {
    "Bone": "Bone_Cx",
}


def normalize_specimen_key(specimen_type):
    """Resolve user-friendly specimen aliases to the actual registry keys used in the model."""
    if specimen_type is None:
        return None
    return SPECIMEN_KEY_ALIASES.get(str(specimen_type), str(specimen_type))


def apply_specimen_shift_tuning(specimen_type, shift_label, tuning_key, value):
    """Persist a specimen-type and shift-specific override for later simulation processing."""
    from params_config.specimen_config_d2 import SPECIMEN_TYPES

    specimen_type = normalize_specimen_key(specimen_type)
    if specimen_type not in SPECIMEN_TYPES:
        raise KeyError(f"Unknown specimen type '{specimen_type}' for tuning override.")
    spec_cfg = SPECIMEN_TYPES[specimen_type]
    override_bucket = spec_cfg.setdefault("tuning_overrides", {})
    override_bucket.setdefault(shift_label, {})[tuning_key] = value
    return spec_cfg

def clear_specimen_shift_tuning(specimen_type, shift_label=None, tuning_key=None):
    """Remove one or more specimen-type and shift-specific overrides."""
    specimen_type = normalize_specimen_key(specimen_type)
    if specimen_type not in SPECIMEN_TYPES:
        return
    spec_cfg = SPECIMEN_TYPES[specimen_type]
    tuning_overrides = spec_cfg.get("tuning_overrides") or {}
    if not tuning_overrides:
        return
    if shift_label is None:
        tuning_overrides.clear()
        return
    if tuning_key is None:
        tuning_overrides.pop(shift_label, None)
        return
    shift_cfg = tuning_overrides.get(shift_label, {})
    shift_cfg.pop(tuning_key, None)
    if not shift_cfg:
        tuning_overrides.pop(shift_label, None)