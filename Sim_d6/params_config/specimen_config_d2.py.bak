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

# most speciemsn I set to 0.1 to 5.0 mins originally. lowering to 4min
typical_max_plating_time = 4.0

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
        "accession_touch_time_min": 0.25,  # 15 seconds
        "accession_touch_time_max": 1.0,  # 45 seconds
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
        "accession_touch_time_min": 0.25,
        "accession_touch_time_max": 2.0,
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
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1, "GN_Broth": 1},    
        "plating_time_range": (0.1, typical_max_plating_time),         
        "tech_review_range": (2.0, 4.0),  
        "initial_vol": 100,
        "daily_volume_mean": get_param("Bone", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Bone"),
        "accession_touch_time_min": 1.0,
        "accession_touch_time_max": 5.0,
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
        "accession_touch_time_min": 0.5,
        "accession_touch_time_max": 2.5,
        "cancel_rate_percent": loaded_data["Urine_Inv"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "plating_time_range": (0.1, typical_max_plating_time),
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
        "plating_time_range": (0.1, typical_max_plating_time),
        "tech_review_range": (1.0, 3.0), 
        "daily_volume_mean": get_param("Urine_NonInv", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Urine_NonInv"),
        "accession_touch_time_min": 0.5,
        "accession_touch_time_max": 2.5,
        "cancel_rate_percent": loaded_data["Urine_NonInv"]["cancellation_metrics"]["lab_cancel_rate_pct"],
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
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1},
        "plating_time_range": (0.1, typical_max_plating_time),        
        "tech_review_range": (2.0, 4.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Resp_NonCF", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Resp_NonCF"),
        "accession_touch_time_min": 0.5,
        "accession_touch_time_max": 3.0,
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
        "media_req": {"Chocolate_Agar": 1, "Blood_Agar": 1, "MacConkey": 1, "CNA_Agar": 1, "BCSA_Agar": 1},
        "plating_time_range": (0.1, typical_max_plating_time),        
        "tech_review_range": (2.0, 4.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Resp_CF", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Resp_CF"),
        "accession_touch_time_min": 0.5,
        "accession_touch_time_max": 3.0,
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
        "plating_time_range": (0.1, typical_max_plating_time),         
        "tech_review_range": (2.0, 5.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Wound_other", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Wound_other"),
        "accession_touch_time_min": 1.5,
        "accession_touch_time_max": 6.0,
        "cancel_rate_percent": loaded_data["Wound_other"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Wound_other", "hourly_weights_weekday"),
            "weekend": get_param("Wound_other", "hourly_weights_weekend"),          
        },
    },
    "Wound_Genital": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1, "ThayerMartin": 1},
        "plating_time_range": (0.1, typical_max_plating_time),               
        "tech_review_range": (2.0, 5.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Wound_genital", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Wound_genital"),
        "accession_touch_time_min": 1.0,
        "accession_touch_time_max": 6.0,
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
        "plating_time_range": (0.1, typical_max_plating_time),                
        "tech_review_range": (4.0, 10.0), #
        "initial_vol": 100,
        "daily_volume_mean": get_param("Tissue_other", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Tissue_other"),
        "accession_touch_time_min": 1.5,
        "accession_touch_time_max": 6.0,
        "cancel_rate_percent": loaded_data["Tissue_other"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Tissue_other", "hourly_weights_weekday"),
            "weekend": get_param("Tissue_other", "hourly_weights_weekend"),          
        },
    },
    "Tissue_genital": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "MTM":1, "CNA_Agar": 1}, 
        "plating_time_range": (0.1, typical_max_plating_time),            
        "tech_review_range": (4.0, 10.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Tissue_genital", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Tissue_genital"),
        "accession_touch_time_min": 1.0,
        "accession_touch_time_max": 6.0,
        "cancel_rate_percent": loaded_data["Tissue_genital"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Tissue_genital", "hourly_weights_weekday"),
            "weekend": get_param("Tissue_genital", "hourly_weights_weekend"),          
        },
    },
    # MICRO-PLATING-092B ---
    "Tissue_FNA": {
        "media_req": {"GN_Broth": 1, "Chocolate_Agar": 1, "Blood_Agar": 1},    
        "plating_time_range": (0.1, typical_max_plating_time),           
        "tech_review_range": (4.0, 10.0), #
        "initial_vol": 100,
        "daily_volume_mean": get_param("Tissue_FNA", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Tissue_FNA"),
        "accession_touch_time_min": 1.0,
        "accession_touch_time_max": 4.0,
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

    # "Stool": {
    #     "media_req": {"Blood_Agar": 1, "MacConkey": 1, "HE_Agar": 1, "Campy_CVA": 1, "CT-SMAC": 1, "GN_Broth": 1},      
    #     "cancel_rate_percent":0.02,     
    #     "plating_time_range": (0.1, typical_max_plating_time),   
    #     "tech_review_range": (0.5, 4.0), 
    #     "initial_vol": 100,
    #     "daily_volume_mean": get_param("Stool", "daily_volume_mean"),
    #     "accession_time_config": get_accession_config("Stool"),
    #     "accession_touch_time_min": 0.5,
    #     "accession_touch_time_max": 3.0,
    #     "cancel_rate_percent": loaded_data["Stool"]["cancellation_metrics"]["lab_cancel_rate_pct"],
    #     "hourly_arrival_weights": {
    #         "weekday": get_param("Stool", "hourly_weights_weekday"),
    #         "weekend": get_param("Stool", "hourly_weights_weekend"),          
    #     },


    "Stool_EcoliRoutine": {
        "media_req": {"Blood_Agar": 1, "MacConkey": 1, "HE_Agar": 1, "Campy_CVA": 1, "CT-SMAC": 1, "GN_Broth": 1},      
        "cancel_rate_percent":0.02,     
        "plating_time_range": (0.1, typical_max_plating_time),   
        "tech_review_range": (0.5, 4.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Stool_Ecoli", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Stool_Ecoli"),
        "accession_touch_time_min": 0.5,
        "accession_touch_time_max": 3.0,
        "cancel_rate_percent": loaded_data["Stool_Ecoli"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Stool_Ecoli", "hourly_weights_weekday"),
            "weekend": get_param("Stool_Ecoli", "hourly_weights_weekend"),          
        },
    },

    "Stool_Campy": {
        # "media_req": {"Blood_Agar": 1, "MacConkey": 1, "HE_Agar": 1, "Campy_CVA": 1, "CT-SMAC": 1, "GN_Broth": 1},      
        "media_req": {"Campy_CVA": 1},      
        "cancel_rate_percent":0.02,     
        "plating_time_range": (0.1, typical_max_plating_time),   
        "tech_review_range": (0.5, 4.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Stool_Campy", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Stool_Campy"),
        "accession_touch_time_min": 0.5,
        "accession_touch_time_max": 3.0,
        "cancel_rate_percent": loaded_data["Stool_Campy"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Stool_Campy", "hourly_weights_weekday"),
            "weekend": get_param("Stool_Campy", "hourly_weights_weekend"),          
        },
    },

    "Stool_Vibrio": {
        "media_req": {"Blood_Agar": 1, "MacConkey": 1, "TCBS": 1,},      
        "cancel_rate_percent":0.02,     
        "plating_time_range": (0.1, typical_max_plating_time),   
        "tech_review_range": (0.5, 4.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Stool_Vibrio", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Stool_Vibrio"),
        "accession_touch_time_min": 0.5,
        "accession_touch_time_max": 3.0,
        "cancel_rate_percent": loaded_data["Stool_Vibrio"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Stool_Vibrio", "hourly_weights_weekday"),
            "weekend": get_param("Stool_Vibrio", "hourly_weights_weekend"),          
        },
    },

    "Stool_Yersinia": {
        "media_req": {"MacConkey": 1},      
        "cancel_rate_percent":0.02,     
        "plating_time_range": (0.1, typical_max_plating_time),   
        "tech_review_range": (0.5, 4.0), 
        "initial_vol": 100,
        "daily_volume_mean": get_param("Stool_Yersinia", "daily_volume_mean"),
        "accession_time_config": get_accession_config("Stool"),
        "accession_touch_time_min": 0.5,
        "accession_touch_time_max": 3.0,
        "cancel_rate_percent": loaded_data["Stool_Yersinia"]["cancellation_metrics"]["lab_cancel_rate_pct"],
        "hourly_arrival_weights": {
            "weekday": get_param("Stool_Yersinia", "hourly_weights_weekday"),
            "weekend": get_param("Stool_Yersinia", "hourly_weights_weekend"),          
        },
    },


# Update the STOOL config -----
# Path 1: Stool
# Path 2: Stool + Campy -> requires 72 hours before reading the campy plate
# --	Stools (0060134; 0060135; 0060136; 0060137) -------------
# 0060137 = Stool Culture Yersinia
# 0060134 = E. coli shiga toxin
# 0060135 = Campylobacter
# 0060136 = Vibrio

# For E. coli -> after MALDI -> perform E. coli latex agglutination biochemical
# Plate from GN Broth gets at least 2 days even if no growth
# All plates discarded at 2 days if no growth except for CVA

# Vibrio culture requires TCBS agar - incubate 18 hours at 35C - swwep oxidase -> -> if positive TSI, if negative discard -> after TSI if K/A then phoenix and or Maldi
# Yersinia culture -> incubate at room temperature (no incubator slot) -> examine MAC plate at 48 hours -> no biochemicals until after 48 hours -> if colonies present innoculate TSI and incubate at 37 + innoculate two MIO tubes
# -> if rule out Y. pestis then do Oxidase, catalse, indole, and urease -> then perform Phoenix ID / AST -> confirm with MALDI or 16S sequencing

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

stat_priority_cutoff = 4
accession_aging_minutes_per_rank = 15.0  # routine specimens gain 1 rank per this many minutes of waiting

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



# ---- paste at the END of params_config/specimen_config_d2.py (after SPEC_PRIORITY_MAP) ----
# priority_category: a key of SPEC_PRIORITY_MAP. These are MY GUESSES from the SOP list: review each line.
#  * Categories with rank <= stat_priority_cutoff (1-4) are treated as the STAT tier (no pre-accession hold), so none
#    of the type-level defaults below use them; STAT comes from stat_fraction instead.
#  
# This code maps the specimen type that I define from the LIS (i.e. BCx, bodyfluid, etc. in column 1)
# mapped to the SOP STAT priority list (column 2, i.e. surgical fna, stool_in_transport, etc.), 
# Specimen priority based off of SOP: MICRO-PROC-217 pg 4

PRIORITY_CATEGORY_BY_TYPE = {
    "BCx":               {"whole_blood_bone_marrow": 0.50, "positive_blood_culture": 0.50},
    "BodyFluid":         {"csf": 0.10, "sterile_body_fluids_nonsurgical": 0.90},
    "Bone_Cx":           {"whole_blood_bone_marrow": 1.0}, 
    "Tissue_FNA":        {"surgical_fna": 1.0},
    "Tissue":            {"tissues_nonsurgical": 0.6, "tracheal_gastric_aspirates": 0.1, "anaerobic_transport": 0.1, "invasive_respiratory": 0.2},
    "Tissue_genital":    {"tissues_nonsurgical": 0.6, "genital_ureaplasma_mycoplasma": 0.4},
    "Respiratory":       {"tracheal_gastric_aspirates": 0.4, "invasive_respiratory": 0.4, "stain_cultures": 0.2},                    
    "Resp_CystFibrosis": {"tracheal_gastric_aspirates": 0.4, "invasive_respiratory": 0.4,  "stain_cultures": 0.2}, 
    "Wound":             {"stain_cultures": 1.0},                    
    "Wound_Genital":     {"tissues_nonsurgical": 0.6, "genital_ureaplasma_mycoplasma": 0.4},
    "Stool":             {"stool_in_transport": 0.8, "short_stability_unpreserved": 0.2},
    "Urine_Invasive":    {"urine": 1.0},
    "Urine_NonInvasive": {"urine": 1.0},
}


# Fraction of each type ordered STAT (0-1), from the LIS STAT flag. 0.0 = none until you estimate it.
STAT_FRACTION_BY_TYPE = {t: 0.0 for t in PRIORITY_CATEGORY_BY_TYPE}

# The accession-time histogram was measured on the REAL mix of priorities, so it already includes the fast ones.
# If high-priority specimens also skip the hold, the sim is faster than the LIS. Recommended: False.
stat_skip_hold = False

for _name, _cfg in SPECIMEN_TYPES.items():
    _cat = PRIORITY_CATEGORY_BY_TYPE.get(_name)
    if isinstance(_cat, dict):
        _unknown = [k for k in _cat if k not in SPEC_PRIORITY_MAP]
        assert not _unknown, f"{_name}: unknown SPEC_PRIORITY_MAP categories {_unknown}"
        _cfg["priority_mix"] = dict(_cat)
    elif _cat is not None:
        assert _cat in SPEC_PRIORITY_MAP, f"{_name}: unknown category {_cat!r}"
        _cfg.setdefault("priority_category", _cat)
    _cfg.setdefault("stat_fraction", STAT_FRACTION_BY_TYPE.get(_name, 0.0))


# ===== paste at the END of specimen_config_d2.py (after PRIORITY/STAT snippet) =====================================
# Final-report timing per type, hours AFTER ARRIVAL.  STARTING VALUES taken from the LIS quantiles you posted
# (2024: hold = about P5..P25 of the non-extended part, extended_fraction = share of TATs above ~250-300 h).
# Re-derive them from the raw file:   python calibrate_final_read.py --raw data/observed_2024_lis_clean.csv
# extended_fraction is an UPPER BOUND for "final waits for an AFB/fungal culture": the LIS cannot separate that from
# other long finals (anaerobes, slow growers, positives with long workups).  Set it lower if you know the lab's rate.
FINAL_READ_BY_TYPE = {
    # BCx finals are the Bactec 120 h protocol and match the LIS: no entry.
    "BodyFluid":         {"hold_hours": (75, 127),     "extended_fraction": 0.12, "extended_hours": (318, 356)},
    "Bone_Cx":           {"hold_hours": (94, 175), "extended_fraction": 0.361, "extended_hours": (328, 357), "positive_delay_hours": (8, 12)},
    "Tissue":            {"hold_hours": (75, 137), "extended_fraction": 0.391, "extended_hours": (327, 350), "positive_delay_hours": (8, 12)},
    "Tissue_FNA":        {"hold_hours": (98, 127), "extended_fraction": 0.122, "extended_hours": (268, 358)},
    "Tissue_genital":    {"hold_hours": (68, 142), "extended_fraction": 0.123, "extended_hours": (330, 412)},
    "Wound":             {"hold_hours": (62, 125), "extended_fraction": 0.08, "extended_hours": (327, 351), "positive_delay_hours": (8, 12)},
    "Wound_Genital":     {"hold_hours": (63, 119), "extended_fraction": 0.022, "extended_hours": (260, 356), "positive_delay_hours": (6, 8)},
    "Respiratory":       {"hold_hours": (42, 56),   "extended_fraction": 0.0,  "extended_hours": (0, 0)},
    "Resp_CystFibrosis": {"hold_hours": (42, 56),   "extended_fraction": 0.0,  "extended_hours": (0, 0)},
    "Stool":             {"hold_hours": (72, 91), "extended_fraction": 0.0, "extended_hours": (0, 0), "positive_delay_hours": (5, 10)},
    "Urine_Invasive":    {"hold_hours": (22, 68), "extended_fraction": 0.0, "extended_hours": (0, 0)},
    "Urine_NonInvasive": {"hold_hours": (22, 68),   "extended_fraction": 0.0,  "extended_hours": (0, 0)},
}

               
for _t, _fr in FINAL_READ_BY_TYPE.items():
    if _t in SPECIMEN_TYPES:
        SPECIMEN_TYPES[_t]["final_read"] = _fr
    else:
        print(f"WARNING FINAL_READ_BY_TYPE: '{_t}' is not in SPECIMEN_TYPES (typo?)")

