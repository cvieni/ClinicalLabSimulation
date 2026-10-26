import os
import json
import numpy as np

from params_config.specimen_config_helperfunctions import (
    get_param, get_accession_config, create_fallback_accession_config,
    extract_lognormal_config, get_shift_label_for_hour, get_shift_label_for_time,
    resolve_specimen_tuning_value, resolve_time_range_override, normalize_specimen_key,
    apply_specimen_shift_tuning, clear_specimen_shift_tuning
    )


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


# ---------------------------------
# JSON load
# ---------------------------------

# Map of variable name / label -> JSON filename
configs_to_load = {
    # Automated Reader speciments ------
    "BloodCult": "BCx_2024_calibrated_params.json",
    "BodyFluid": "BodyFluid_2024_calibrated_params.json",

    # Manual Plating specimens ------------
    "Bone": "Bone_2024_calibrated_params.json",
    "Urine_Inv": "InvUrine_2024_calibrated_params.json",
    "Urine_NonInv": "NonInv_Urine_2024_calibrated_params.json",
    "Resp_NonCF": "Respiratory_NonCF_2024_calibrated_params.json",
    "Resp_CF": "Respiratory_CF_2024_calibrated_params.json",
    "Stool": "Stool_2024_calibrated_params.json",
    "Tissue_genital": "Tiss_genital_2024_calibrated_params.json",
    "Tissue_FNA": "Tiss_FNA_2024_calibrated_params.json",
    "Tissue_other": "TissueCleaned_2024_calibrated_params.json",
    "Wound_genital": "Wound_genital_2024_calibrated_params.json",
    "Wound_other": "Wound_Cleaned_2024_calibrated_params.json",
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



# ---------------------------------
# Explicit tuning matrix for the tail-driven routes we are calibrating
# ---------------------------------
# These values are intentionally specific to specimen type + shift. They are not silent
# defaults and should be reviewed and updated in this file whenever tuning changes.
SPECIMEN_TUNING_MATRIX = {
    "Tissue": {
        "Day": {
            "avg_incubation_time_Other": 24.0,
            "std_incubation_time_Other": 8.0,
            "tech_review_range": {"min": 2.0, "max": 5.0},
            "pre_accession_hold_multiplier": 1.1,
        },
        "Evening": {
            "avg_incubation_time_Other": 20.0,
            "std_incubation_time_Other": 8.0,
            "tech_review_range": {"min": 5.0, "max": 10.0},
            "pre_accession_hold_multiplier": 1.45,
        },
        "Night": {
            "avg_incubation_time_Other": 18.0,
            "tech_review_range": {"min": 5.0, "max": 9.0},
            "pre_accession_hold_multiplier": 1.2,
        },
    },
    "Bone_Cx": {
        "Day": {
            "avg_incubation_time_Other": 28.0,
            "std_incubation_time_Other": 10.0,
            "tech_review_range": {"min": 3.0, "max": 5.0},
            "pre_accession_hold_multiplier": 1.15,
        },
        "Evening": {
            "avg_incubation_time_Other": 18.0,
            "std_incubation_time_Other": 8.0,
            "tech_review_range": {"min": 5.0, "max": 10.0},
            "pre_accession_hold_multiplier": 1.5,
        },
    },
    "BodyFluid": {
        "Day": {
            "avg_incubation_time_Other": 16.0,
            "incubation_1_time_std": 8.0,
            "tech_review_range": {"min": 3.5, "max": 7.0},
            "pre_accession_hold_multiplier": 1.0,
        },
        "Evening": {
            "avg_incubation_time_Other": 18.0,
            "tech_review_range": {"min": 4.0, "max": 8.0},
            "pre_accession_hold_multiplier": 1.25,
        },
        "Night": {
            "avg_incubation_time_Other": 17.0,
            "tech_review_range": {"min": 4.0, "max": 8.0},
            "pre_accession_hold_multiplier": 1.2,
        },
    },
    "Wound": {
        "Day": {
            "avg_incubation_time_Other": 16.0,
            "tech_review_range": {"min": 4.0, "max": 8.0},
            "pre_accession_hold_multiplier": 1.1,
        },
        "Evening": {
            "avg_incubation_time_Other": 18.0,
            "tech_review_range": {"min": 5.0, "max": 10.0},
            "pre_accession_hold_multiplier": 1.35,
        },
        "Night": {
            "avg_incubation_time_Other": 16.0,
            "tech_review_range": {"min": 4.0, "max": 8.0},
            "pre_accession_hold_multiplier": 1.15,
        },
    },
    "FNA_Tissue": {
        "Day": {
            "avg_incubation_time_Other": 16.0,
            "tech_review_range": {"min": 4.0, "max": 8.0},
            "pre_accession_hold_multiplier": 1.1,
        },
        "Evening": {
            "avg_incubation_time_Other": 18.0,
            "tech_review_range": {"min": 5.0, "max": 10.0},
            "pre_accession_hold_multiplier": 1.25,
        },
    },
}

# ---------------------------------
# Define Configuration
# ---------------------------------


SPECIMEN_TYPES = {
    # ------------------------------------------
    # Blood Cultures ---------------------------
    "BCx": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1},
        "daily_volume_mean": get_param("BloodCult", "daily_volume_mean"),

        # Bcx has 2 large spikes in the TTP which I talked to Dr. Fisher about and seem to be due to the machine/lab process rather than real. So instead nick suggested just using the log normal distribution
        # "ttp_config": loaded_data["BloodCult"].get("ttp_config", {}),
        "ttp_config": extract_lognormal_config(
                    loaded_data,
                    specimen_key="BloodCult",
                    config_key="ttp_config",
                ),


        "accession_time_config": get_accession_config("BloodCult"),
        "cancel_rate_percent": loaded_data["BloodCult"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "plating_time_range": (0.0, 0.0),
        "tech_review_range": (2.0, 4.0), 
        "hourly_arrival_weights": {
            "weekday": get_param("BloodCult", "hourly_weights_weekday"),
            "weekend": get_param("BloodCult", "hourly_weights_weekend"),          
        },
        "initial_vol": 100 
    },
    # ------------------------------------------
    # Per SOP: MICRO-PLATING-032A ---------------------------
    # Body Fluid: Test 0060108
    "BodyFluid": {
        "media_req": {"Chocolate_Agar": 1, "Blood_Agar": 1, "MacConkey": 1, "CNA_Agar": 1},
        "daily_volume_mean": get_param("BodyFluid", "daily_volume_mean"),
        "ttp_config": loaded_data["BodyFluid"].get("ttp_config", {}),
        "accession_time_config": get_accession_config("BodyFluid"),
        "cancel_rate_percent": loaded_data["BodyFluid"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "plating_time_range": (0.0, 0.0),
        "tech_review_range": (2.0, 4.0), 
        "hourly_arrival_weights": {
            "weekday": get_param("BodyFluid", "hourly_weights_weekday"),
            "weekend": get_param("BodyFluid", "hourly_weights_weekend"),          
        },
        "initial_vol": 100 
    },
    # ------------------------------------------
    # ------------------------------------------
    
    # ------------------------------------------
    # Per SOP: MICRO-PROC-045 ---------------------------
    # Test Directory: Test 0060103
    "Bone_Cx": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1, "FastidiousBroth": 1},    
        "plating_time_range": (0.1, 5.0),         
        "tech_review_range": (2.0, 4.0),  
        "initial_vol": 100,
        "daily_volume_mean": get_param("Bone", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Bone"),
        "cancel_rate_percent": loaded_data["Bone"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Bone", "hourly_weights_weekday"),
            "weekend": get_param("Bone", "hourly_weights_weekend"),          
        },
    },
    # Per SOP: MICRO-PROC-045 ---------------------------
    # ------------------------------------------

    "Urine_Invasive": {
        "media_req": {"ChromeAgar": 1, "Blood_Agar": 2},
        "daily_volume_mean": get_param("Urine_Inv", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Urine_Inv"),
        "cancel_rate_percent": loaded_data["Urine_Inv"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "plating_time_range": (0.1, 5.0),
        "tech_review_range": (1.0, 3.0), 
        # Arrival probability weights across 24 hours (Surges at 09:00 and 15:00)
        "hourly_arrival_weights": {
            "weekday": get_param("Urine_Inv", "hourly_weights_weekday"),
            "weekend": get_param("Urine_Inv", "hourly_weights_weekend"),          
        },
        "initial_vol": 100
    },
    "Urine_NonInvasive": {
        "media_req": {"ChromeAgar": 1, "Blood_Agar": 1},
        "daily_volume_mean": get_param("Urine_NonInv", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Urine_NonInv"),
        "cancel_rate_percent": loaded_data["Urine_NonInv"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "plating_time_range": (0.1, 5.0),
        "tech_review_range": (1.0, 3.0), 
        "hourly_arrival_weights": {
            "weekday": get_param("Urine_NonInv", "hourly_weights_weekday"),
            "weekend": get_param("Urine_NonInv", "hourly_weights_weekend"),          
        },
        "initial_vol": 100 
    },
    
    # ------------------------------------------
    # ------------------------------------------
    # ------------------------------------------
    # Per SOP: MICRO-PLATING-001A ---------------------------
    # Test Directory: Test 0060122
    "Respiratory": {
        "media_req": {"Blood_Agar": 1, "Chocolate": 1, "MacConkey": 1, "GramStain": 1},
        "plating_time_range": (0.1, 5.0),        
        "tech_review_range": (2.0, 4.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Resp_NonCF", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Resp_NonCF"),
        "cancel_rate_percent": loaded_data["Resp_NonCF"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Resp_NonCF", "hourly_weights_weekday"),
            "weekend": get_param("Resp_NonCF", "hourly_weights_weekend"),          
        },
    },
    # BACT-PLATING-048A.pptxAug122026021806.pdf
    # BCSA == Burkholderia cepacia Selective Agar
    # Test Directory: Test 0060130 (CF culture)
    "Resp_CystFibrosis": {
        "media_req": {"Chocolate": 1, "Blood_Agar": 1, "MacConkey": 1, "CNA_Agar": 1, "BCSA_Agar": 1},
        "plating_time_range": (0.1, 5.0),        
        "tech_review_range": (2.0, 4.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Resp_CF", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Resp_CF"),
        "cancel_rate_percent": loaded_data["Resp_CF"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Resp_CF", "hourly_weights_weekday"),
            "weekend": get_param("Resp_CF", "hourly_weights_weekend"),          
        },
    },


    # ------------------------------------------
    # ------------------------------------------
    # ------------------------------------------
    # Per SOP: MICRO-PLATING-034A---------------------------
    # Test Directory: Test 0060132
    "Wound": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1},
        "plating_time_range": (0.1, 5.0),         
        "tech_review_range": (3.0, 5.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Wound_other", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Wound_other"),
        "cancel_rate_percent": loaded_data["Wound_other"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Wound_other", "hourly_weights_weekday"),
            "weekend": get_param("Wound_other", "hourly_weights_weekend"),          
        },
    },
    "Wound_Genital": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1, "ThayerMartin": 1},
        "plating_time_range": (0.1, 5.0),               
        "tech_review_range": (3.0, 5.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Wound_genital", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Wound_genital"),
        "cancel_rate_percent": loaded_data["Wound_genital"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Wound_genital", "hourly_weights_weekday"),
            "weekend": get_param("Wound_genital", "hourly_weights_weekend"),          
        },
    },
    # Per SOP: MICRO-PLATING-034A---------------------------
    # ------------------------------------------

    # ------------------------------------------
    # Per SOP: MICRO-PLATING-092A ---------------------------
    # Test Directory: Test 0060127
    "Tissue": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1},
        "plating_time_range": (0.1, 5.0),                
        "tech_review_range": (4.0, 10.0), #
        "initial_vol": 100,
        "daily_volume_mean": get_param("Tissue_other", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Tissue_other"),
        "cancel_rate_percent": loaded_data["Tissue_other"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Tissue_other", "hourly_weights_weekday"),
            "weekend": get_param("Tissue_other", "hourly_weights_weekend"),          
        },
    },
    "Tissue_genital": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "MTM":1, "CNA_Agar": 1}, 
        "plating_time_range": (0.1, 5.0),            
        "tech_review_range": (4.0, 10.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Tissue_genital", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Tissue_genital"),
        "cancel_rate_percent": loaded_data["Tissue_genital"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Tissue_genital", "hourly_weights_weekday"),
            "weekend": get_param("Tissue_genital", "hourly_weights_weekend"),          
        },
    },
    # MICRO-PLATING-092B ---
    "Tissue_FNA": {
        "media_req": {"FastidiousBroth": 1, "Chocolate_Agar": 1, "Blood_Agar": 1},    
        "plating_time_range": (0.1, 5.0),           
        "tech_review_range": (4.0, 10.0), #
        "initial_vol": 100,
        "daily_volume_mean": get_param("Tissue_FNA", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Tissue_FNA"),
        "cancel_rate_percent": loaded_data["Tissue_FNA"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Tissue_FNA", "hourly_weights_weekday"),
            "weekend": get_param("Tissue_FNA", "hourly_weights_weekend"),          
        },
    },

    # ------------------------------------------
    # Per SOP: MICRO-PLATING-058A ---------------------------
    # Stool Culture, E. Coli, Test Directory: Test 0060134
    # Stool Culture, Campylobacter, Test Directory: Test 0060135
    # Stool Culture, Vibrio, Test Directory: Test 0060136
    # Stool Culture, Yersinia, Test Directory: Test 0060137

    "Stool": {
        "media_req": {"Blood_Agar": 1, "MacConkey": 1, "HE_Agar": 1, "Campy_CVA": 1, "CT-SMAC": 1, "GN_Broth": 1},      
        "cancel_rate_percent":0.02,     
        "plating_time_range": (0.1, 5.0),   
        "tech_review_range": (0.5, 4.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Stool", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Stool"),
        "cancel_rate_percent": loaded_data["Stool"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Stool", "hourly_weights_weekday"),
            "weekend": get_param("Stool", "hourly_weights_weekend"),          
        },

    }
}

# Attach the explicit tuning matrix to all specimen configs so the override layer is
# always discoverable and reviewable in one place.
for specimen_name, shifts in SPECIMEN_TUNING_MATRIX.items():
    if specimen_name not in SPECIMEN_TYPES:
        continue
    SPECIMEN_TYPES[specimen_name].setdefault("tuning_overrides", {})
    for shift_name, values in shifts.items():
        SPECIMEN_TYPES[specimen_name]["tuning_overrides"].setdefault(shift_name, {}).update(values)

# Specimen priority based off of SOP: MICRO-PROC-217 pg 4
SPEC_PRIORITY_MAP = {
    "whole_blood_bone_marrow": 1,   # Whole Blood & Bone Marrow (non-blood culture)
    "stat": 2,                      # Any specimen ordered as "STAT"
    "csf": 3,                       # CSF culture and Gram stain
    "positive_blood_culture": 4,    # Positive Routine Blood Culture bottles
    "surgical_fna": 5,              # Surgical specimens (bone, tissue) & FNAs
    "invasive_respiratory": 6,      # Invasive respiratory samples (BALs, bronchoscopy)
    "short_stability_unpreserved": 7, # Short stability unpreserved (e.g. unpreserved stool)
    "sterile_body_fluids_nonsurgical": 8, # Non-surgical sterile body fluids (drains)
    "tissues_nonsurgical": 9,       # Non-surgical tissues (punch biopsies)
    "tracheal_gastric_aspirates": 10, # Tracheal and gastric aspirates
    "anaerobic_transport": 11,      # Anaerobic cultures in transport systems
    "stain_cultures": 12,           # Wounds, abscesses, sputums
    "stool_in_transport": 13,       # Stools in transport media/frozen
    "urine": 14,                    # Urines
    "genital_ureaplasma_mycoplasma": 15, # Genital specimens for Ureaplasma/Mycoplasma
    "studies": 16,                  # Research/Study specimens
}


# Attach explicit overrides to SPECIMEN_TYPES
for specimen_name, shifts in SPECIMEN_TUNING_MATRIX.items():
    if specimen_name in SPECIMEN_TYPES:
        SPECIMEN_TYPES[specimen_name].setdefault("tuning_overrides", {})
        for shift_name, values in shifts.items():
            SPECIMEN_TYPES[specimen_name]["tuning_overrides"].setdefault(shift_name, {}).update(values)