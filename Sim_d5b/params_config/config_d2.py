# config.py
import os
import json
import numpy as np
# ==============================================================================
# Load calibrated parameters from ARUP data
# ==============================================================================
file_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(file_dir)
json_dir = os.path.join(PROJECT_ROOT, "ARUP_data", "json_clned_data")


# ---------------------------------
# JSON load
# ---------------------------------

# Map of variable name / label -> JSON filename
configs_to_load = {
    "BloodCult": "BCx_2024_calibrated_params.json",
    "BodyFluid": "BodyFluid_2024_calibrated_params.json",
    "Urine_Inv": "InvUrine_2024_calibrated_params.json",
    "Urine_NonInv": "NonInv_Urine_2024_calibrated_params.json"
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





# ---------------------------------
# Define Configuration
# ---------------------------------

SPECIMEN_TYPES = {
    "Urine_Invasive": {
        "media_req": {"ChromeAgar": 1, "Blood_Agar": 2},
        "daily_volume_mean": get_param("Urine_Inv", "daily_volume_mean"),
        # "accession_proc_time": (
        #     loaded_data["Urine_Inv"]["accession_time_config"]["mean_accession_min"],
        #     loaded_data["Urine_Inv"]["accession_time_config"]["max_accession_min"]
        # ),
        "accession_time_config": get_accession_config("Urine_Inv"),
        # "cancel_rate_percent":{loaded_data["Urine_Inv"]["cancellation_metrics"]["cancel_rate_percent"]},
        "cancel_rate_percent": loaded_data["Urine_Inv"]["cancellation_metrics"]["cancel_rate_percent"],
        "plating_time_range": (0.1, 5.0),
        "tech_review_range": (1.0, 3.0), 
        # Arrival probability weights across 24 hours (Surges at 09:00 and 15:00)
        "hourly_arrival_weights": {
            "weekday": get_param("Urine_Inv", "hourly_weights_weekday"),
            "weekend": get_param("Urine_Inv", "hourly_weights_weekend"),          
        }
    },
    "Urine_NonInvasive": {
        "media_req": {"ChromeAgar": 1, "Blood_Agar": 1},
        "daily_volume_mean": get_param("Urine_NonInv", "daily_volume_mean"),
        # "accession_proc_time": (
        #     loaded_data["Urine_NonInv"]["accession_time_config"]["mean_accession_min"],
        #     loaded_data["Urine_NonInv"]["accession_time_config"]["max_accession_min"]
        # ),
        "accession_time_config": get_accession_config("Urine_NonInv"),
        # "cancel_rate_percent":{loaded_data["Urine_NonInv"]["cancellation_metrics"]["cancel_rate_percent"]},
        "cancel_rate_percent": loaded_data["Urine_NonInv"]["cancellation_metrics"]["cancel_rate_percent"],
        "plating_time_range": (0.1, 5.0),
        "tech_review_range": (1.0, 3.0), 
        "hourly_arrival_weights": {
            "weekday": get_param("Urine_NonInv", "hourly_weights_weekday"),
            "weekend": get_param("Urine_NonInv", "hourly_weights_weekend"),          
        }
    },
    # ------------------------------------------
    # Blood Cultures ---------------------------
    "BCx": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1},
        "daily_volume_mean": get_param("BloodCult", "daily_volume_mean"),
        "ttp_config": loaded_data["BloodCult"].get("ttp_config", {}),
        # "accession_proc_time": (
        #     loaded_data["BloodCult"]["accession_time_config"]["mean_accession_min"],
        #     loaded_data["BloodCult"]["accession_time_config"]["max_accession_min"]
        # ),
        "accession_time_config": get_accession_config("BloodCult"),
        # "cancel_rate_percent":{loaded_data["BloodCult"]["cancellation_metrics"]["cancel_rate_percent"]},
        "cancel_rate_percent": loaded_data["BloodCult"]["cancellation_metrics"]["cancel_rate_percent"],
        "plating_time_range": (0.0, 0.0),
        "tech_review_range": (2.0, 4.0), 
        "hourly_arrival_weights": {
            "weekday": get_param("BloodCult", "hourly_weights_weekday"),
            "weekend": get_param("BloodCult", "hourly_weights_weekend"),          
        }
    },
    # ------------------------------------------
    # Per SOP: MICRO-PLATING-032A ---------------------------
    "BodyFluid": {
        "media_req": {"Chocolate_Agar": 1, "Blood_Agar": 1, "MacConkey": 1, "CNA_Agar": 1},
        "daily_volume_mean": get_param("BodyFluid", "daily_volume_mean"),
        "ttp_config": loaded_data["BodyFluid"].get("ttp_config", {}),
        # "accession_proc_time": (
        #     loaded_data["BodyFluid"]["accession_time_config"]["mean_accession_min"],
        #     loaded_data["BodyFluid"]["accession_time_config"]["max_accession_min"]
        # ),
        "accession_time_config": get_accession_config("BodyFluid"),
        # "cancel_rate_percent":{loaded_data["BodyFluid"]["cancellation_metrics"]["cancel_rate_percent"]},
        "cancel_rate_percent": loaded_data["BodyFluid"]["cancellation_metrics"]["cancel_rate_percent"],
        "plating_time_range": (0.0, 0.0),
        "tech_review_range": (2.0, 4.0), 
        "hourly_arrival_weights": {
            "weekday": get_param("BodyFluid", "hourly_weights_weekday"),
            "weekend": get_param("BodyFluid", "hourly_weights_weekend"),          
        }
    },
    # ------------------------------------------
    # ------------------------------------------

    # ------------------------------------------
    # Per SOP: MICRO-PLATING-058A ---------------------------
    "Stool": {
        "media_req": {"Blood_Agar": 1, "MacConkey": 1, "HE_Agar": 1, "Campy_CVA": 1, "CT-SMAC": 1, "GN_Broth": 1},
        "daily_volume_mean": 25,
        # "accession_proc_time": (1.0, 3.0),
        "accession_time_config": create_fallback_accession_config(min_min=1.0, max_min=3.0, mean_min=2.0, std_min=0.5),
        # "cancel_rate_percent":{loaded_data["Stool"]["cancellation_metrics"]["cancel_rate_percent"]},        
        "cancel_rate_percent":0.02,     
        "plating_time_range": (0.1, 5.0),   
        "tech_review_range": (0.5, 4.0), 
        # Baseline continuous rate (0.02) + spikes following routine phlebotomy rounds:
        # Morning round (05:00-07:00), Noon round (12:00-13:00), Evening round (18:00-19:00)
        "hourly_arrival_weights": [
            [0.0]*6 + [0.1]*6 + [0.05]*6 + [0.01]*6
        ]
    },
    
    # ------------------------------------------
    # ------------------------------------------

    # ------------------------------------------
    # Per SOP: MICRO-PLATING-001A ---------------------------
    "Respiratory": {
        "media_req": {"Blood_Agar": 1, "Chocolate": 1, "MacConkey": 1, "GramStain": 1},
        "daily_volume_mean": 25,
        # "accession_proc_time": (1.0, 3.0),
        "accession_time_config": create_fallback_accession_config(min_min=1.0, max_min=3.0, mean_min=2.0, std_min=0.5),
        "cancel_rate_percent":0.02,
        "plating_time_range": (0.1, 5.0),        
        "tech_review_range": (2.0, 4.0), 
        "hourly_arrival_weights": [0.04] * 24
    },
    # BACT-PLATING-048A.pptxAug122026021806.pdf
    # BCSA == Burkholderia cepacia Selective Agar
    "Resp_CystFibrosis": {
        "media_req": {"Chocolate": 1, "Blood_Agar": 1, "MacConkey": 1, "CNA_Agar": 1, "BCSA_Agar": 1},
        "daily_volume_mean": 25,
        # "accession_proc_time": (1.0, 3.0),
        "accession_time_config": create_fallback_accession_config(min_min=1.0, max_min=3.0, mean_min=2.0, std_min=0.5),
        "cancel_rate_percent":0.02,
        "plating_time_range": (0.1, 5.0),        
        "tech_review_range": (2.0, 4.0), 
        "hourly_arrival_weights": [0.04] * 24
    },
    

    # ------------------------------------------
    # ------------------------------------------

    # ------------------------------------------
    # Per SOP: MICRO-PLATING-034A---------------------------
    "Wound": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1},
        "daily_volume_mean": 18,
        # "accession_proc_time": (1.0, 3.0),
        "accession_time_config": create_fallback_accession_config(min_min=1.0, max_min=3.0, mean_min=2.0, std_min=0.5),
        "cancel_rate_percent":0.02,
        "plating_time_range": (0.1, 5.0),         
        "tech_review_range": (3.0, 5.0), 
        "hourly_arrival_weights": [0.04] * 24
    },
#     "Wound": {
    #     "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1},
    #     "daily_volume_mean": 18,
    #     "accession_proc_time": (
    #         get_param("Wound", "min_accession_proc_time", 1.0),
    #         get_param("Wound", "max_accession_proc_time", 3.0)
    #     ),
    #     "tech_review_range": (3.0, 5.0), 
    #     "hourly_arrival_weights": [0.04] * 24
    # },
    "Wound_Genital": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1, "ThayerMartin": 1},
        "daily_volume_mean": 18,
        # "accession_proc_time": (1.0, 3.0),
        "accession_time_config": create_fallback_accession_config(min_min=1.0, max_min=3.0, mean_min=2.0, std_min=0.5),
        "cancel_rate_percent":0.02,        
        "tech_review_range": (3.0, 5.0), 
        "hourly_arrival_weights": [0.04] * 24
    },
    # Per SOP: MICRO-PLATING-034A---------------------------
    # ------------------------------------------

    # ------------------------------------------
    # Per SOP: MICRO-PLATING-092A ---------------------------
    "Tissue": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1},
        "daily_volume_mean": 15,
        # "accession_proc_time": (1.0, 3.0),
        "accession_time_config": create_fallback_accession_config(min_min=1.0, max_min=3.0, mean_min=2.0, std_min=0.5),
        "cancel_rate_percent":0.02,        
        "tech_review_range": (4.0, 10.0), #
        "hourly_arrival_weights": [0.04] * 24
    },
    "Tissue_genital": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "MTM":1, "CNA_Agar": 1},
        "daily_volume_mean": 15,
        # "accession_proc_time": (1.0, 3.0),
        "accession_time_config": create_fallback_accession_config(min_min=1.0, max_min=3.0, mean_min=2.0, std_min=0.5),
        "cancel_rate_percent":0.02,        
        "tech_review_range": (4.0, 10.0), #
        "hourly_arrival_weights": [0.04] * 24
    },
    # MICRO-PLATING-092B ---
    "Tissue_FNA": {
        "media_req": {"FastidiousBroth": 1, "Chocolate_Agar": 1, "Blood_Agar": 1},
        "daily_volume_mean": 15,
        # "accession_proc_time": (1.0, 3.0),
        "accession_time_config": create_fallback_accession_config(min_min=1.0, max_min=3.0, mean_min=2.0, std_min=0.5),
        "cancel_rate_percent":0.02,        
        "tech_review_range": (4.0, 10.0), #
        "hourly_arrival_weights": [0.04] * 24
    },
    # "Tissue_FNA": {
    #     "media_req": {"FastidiousBroth": 1, "Chocolate_Agar": 1, "Blood_Agar": 1},
    #     "daily_volume_mean": 15,
    #     "accession_proc_time": (
    #         get_param("Tissue_FNA", "min_accession_proc_time", 1.0),
    #         get_param("Tissue_FNA", "max_accession_proc_time", 3.0)
    #     ),
    #     "tech_review_range": (4.0, 10.0), #
    #     "hourly_arrival_weights": [0.04] * 24
    # },


    # ------------------------------------------
    # Per SOP: MICRO-PROC-045 ---------------------------
    "Bone_Cx": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1, "FastidiousBroth": 1}, 
        "daily_volume_mean": 75,
        # "accession_proc_time": (1.0, 3.0),
        "accession_time_config": create_fallback_accession_config(min_min=1.0, max_min=3.0, mean_min=2.0, std_min=0.5),
        "cancel_rate_percent":0.02,        
        "tech_review_range": (2.0, 4.0),     
        # Baseline continuous rate (0.02) + spikes following routine phlebotomy rounds:
        # Morning round (05:00-07:00), Noon round (12:00-13:00), Evening round (18:00-19:00)
        "hourly_arrival_weights": [
            0.02, 0.02, 0.02, 0.02, 0.02, 0.12, # 00:00 - 05:00 (Surge at 05:00 phlebotomy drop)
            0.15, 0.04, 0.02, 0.02, 0.02, 0.02, # 06:00 - 11:00 (Morning drop off)
            0.10, 0.12, 0.03, 0.02, 0.02, 0.02, # 12:00 - 17:00 (Midday phlebotomy drop)
            0.10, 0.08, 0.02, 0.02, 0.02, 0.02  # 18:00 - 23:00 (Evening phlebotomy drop)
        ]
    }
    # Per SOP: MICRO-PROC-045 ---------------------------
    # ------------------------------------------

}

MEDIA_CONFIG = {
    "Blood_Agar": { "cost": 1.3,
                   "shelf_life": 45, "reorder_point": 200, "order_qty": 2000,
                   "initial": 200},
    "MacConkey": {"cost": 1.0,
                  "shelf_life": 60, "reorder_point": 150, "order_qty": 500,
                  "initial": 200},
    "CNA_Agar": {"cost": 1.0,
                 "shelf_life": 30, "reorder_point": 100, "order_qty": 200,
                 "initial": 200},
    "Chocolate_Agar": {"cost": 1.0,
                       "shelf_life": 30, "reorder_point": 80, "order_qty": 1000,
                       "initial": 200},
    "ThayerMartin": {"cost": 1.0,
                  "shelf_life": 30, "reorder_point": 80, "order_qty": 1000,
                  "initial": 200},
    "ChromeAgar": {"cost": 1.5,
                  "shelf_life": 30, "reorder_point": 150, "order_qty": 1000,
                  "initial": 200},
    "MTM":{"cost": 1.5,
                  "shelf_life": 30, "reorder_point": 20, "order_qty": 100,
                  "initial": 200},
    "IMA": {"cost": 1.0,
        "shelf_life": 20, "reorder_point": 75, "order_qty": 300,
        "initial": 200},
    "FastidiousBroth": {"cost": 1.0,
        "shelf_life": 20, "reorder_point": 75, "order_qty": 300,
        "initial": 200}
}


# Shift staffing profiles (Tech availability multiplier throughout the day)
# Separate Weekday vs. Weekend staffing profiles
# tech_general == tech that does general accessioning and plating from specimen
SHIFT_STAFFING_PROFILE = {
    "Weekday": {
        "Shift_1_Day":     {"hours": (7, 15),
                            "tech_accession": 12, "tech_plating": 4, "tech_blood": 2, "tech_routine": 4, "tech_urine": 2, "tech_new": 2,
                            "plating_capacity": 4},
        "Shift_2_Evening": {"hours": (15, 23),
                            "tech_accession": 6, "tech_plating": 4, "tech_blood": 1, "tech_routine": 2, "tech_urine": 1, "tech_new": 2,
                            "plating_capacity": 3},
        "Shift_3_Night":   {"hours": (23, 7),
                            "tech_accession": 6, "tech_plating": 4, "tech_blood": 1, "tech_routine": 1, "tech_urine": 1, "tech_new": 2,
                            "plating_capacity": 2}
    },
    "Weekend": {
        "Shift_1_Day":     {"hours": (7, 15), 
                            "tech_accession": 12, "tech_plating": 4, "tech_blood": 1, "tech_routine": 2, "tech_urine": 1, "tech_new": 2,
                            "plating_capacity": 2},
        "Shift_2_Evening": {"hours": (15, 23),
                            "tech_accession": 6, "tech_plating": 4, "tech_blood": 1, "tech_routine": 2, "tech_urine": 1,  "tech_new": 2,
                            "plating_capacity": 1},
        "Shift_3_Night":   {"hours": (23, 7), 
                            "tech_accession": 6, "tech_plating": 4, "tech_blood": 1, "tech_routine": 2, "tech_urine": 1, "tech_new": 2,
                            "plating_capacity": 1}
    }
}


# Setup resources dictionary
bc_instrument_capacity = 432 # 16 racks w/ 27 bottles each -> 432 per instrument # per SOP BACT-PROC-224
num_BACTEC_virtuo = 3
incubator_capacity = 10000
temp_slots_phenix = 1 # termpature slot on the phenix
phoenix_capacity_permach = 50 - temp_slots_phenix
numphenix = 3
maldi_cap = 2 # number of maldi instruments

Instrument_resources = {
    "incubator": incubator_capacity,
    "bc_instrument": int(num_BACTEC_virtuo * bc_instrument_capacity),
    "phoenix_instrument": int(numphenix*phoenix_capacity_permach),
    "maldi_instrument": maldi_cap
}


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


# # Print accession times to terminal
print("\n--- ACCESSION PROCESSING TIMES ---")
for spec_name, spec_cfg in SPECIMEN_TYPES.items():
    acc_cfg = spec_cfg.get("accession_time_config")
    
    if isinstance(acc_cfg, dict) and "mean_accession_min" in acc_cfg:
        mean_val = acc_cfg["mean_accession_min"]
        max_val = acc_cfg["max_accession_min"]
        print(f"{spec_name:<20}: Mean ~{mean_val} min (Max ~{max_val} min)")
    elif isinstance(acc_cfg, dict) and "bin_edges" in acc_cfg:
        min_val = acc_cfg["bin_edges"][0]
        max_val = acc_cfg["bin_edges"][-1]
        print(f"{spec_name:<20}: Range ({min_val}, {max_val}) minutes")
    else:
        print(f"{spec_name:<20}: Default (2.0, 5.0) minutes")