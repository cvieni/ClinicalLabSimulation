# config.py

SPECIMEN_TYPES = {
    "Urine_Invasive": {
        "media_req": {"ChromeAgar": 1, "Blood_Agar": 2},
        "daily_volume_mean": 120,
        "tech_review_range": (1.0, 3.0), 
        # Arrival probability weights across 24 hours (Surges at 09:00 and 15:00)
        "hourly_arrival_weights": [
            0.01, 0.01, 0.01, 0.01, 0.02, 0.03, # 00:00 - 05:00 (Night)
            0.05, 0.08, 0.12, 0.10, 0.08, 0.06, # 06:00 - 11:00 (Morning surge)
            0.05, 0.05, 0.07, 0.11, 0.08, 0.04, # 12:00 - 17:00 (Afternoon surge)
            0.02, 0.01, 0.01, 0.01, 0.01, 0.01  # 18:00 - 23:00 (Evening drop)
        ]
    },
    "Urine_NonInvasive": {
        "media_req": {"ChromeAgar": 1, "Blood_Agar": 1},
        "daily_volume_mean": 120,
        "tech_review_range": (1.0, 3.0), 
        # Arrival probability weights across 24 hours (Surges at 09:00 and 15:00)
        "hourly_arrival_weights": [
            0.01, 0.01, 0.01, 0.01, 0.02, 0.03, # 00:00 - 05:00 (Night)
            0.05, 0.08, 0.12, 0.10, 0.08, 0.06, # 06:00 - 11:00 (Morning surge)
            0.05, 0.05, 0.07, 0.11, 0.08, 0.04, # 12:00 - 17:00 (Afternoon surge)
            0.02, 0.01, 0.01, 0.01, 0.01, 0.01  # 18:00 - 23:00 (Evening drop)
        ]
    },
    "BCx": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1},
        "daily_volume_mean": 75,
        "tech_review_range": (2.0, 4.0), 
        # Baseline continuous rate (0.02) + spikes following routine phlebotomy rounds:
        # Morning round (05:00-07:00), Noon round (12:00-13:00), Evening round (18:00-19:00)
        "hourly_arrival_weights": [
            0.02, 0.02, 0.02, 0.02, 0.02, 0.12, # 00:00 - 05:00 (Surge at 05:00 phlebotomy drop)
            0.15, 0.04, 0.02, 0.02, 0.02, 0.02, # 06:00 - 11:00 (Morning drop off)
            0.10, 0.12, 0.03, 0.02, 0.02, 0.02, # 12:00 - 17:00 (Midday phlebotomy drop)
            0.10, 0.08, 0.02, 0.02, 0.02, 0.02  # 18:00 - 23:00 (Evening phlebotomy drop)
        ]
    },
    # ------------------------------------------
    # Per SOP: MICRO-PLATING-032A ---------------------------
    "BodyFluid": {
        "media_req": {"Chocolate_Agar": 1, "Blood_Agar": 1, "MacConkey": 1, "CNA_Agar": 1},
        "daily_volume_mean": 75,
        "tech_review_range": (2.0, 4.0), 
        # Baseline continuous rate (0.02) + spikes following routine phlebotomy rounds:
        # Morning round (05:00-07:00), Noon round (12:00-13:00), Evening round (18:00-19:00)
        "hourly_arrival_weights": [
            0.02, 0.02, 0.02, 0.02, 0.02, 0.12, # 00:00 - 05:00 (Surge at 05:00 phlebotomy drop)
            0.15, 0.04, 0.02, 0.02, 0.02, 0.02, # 06:00 - 11:00 (Morning drop off)
            0.10, 0.12, 0.03, 0.02, 0.02, 0.02, # 12:00 - 17:00 (Midday phlebotomy drop)
            0.10, 0.08, 0.02, 0.02, 0.02, 0.02  # 18:00 - 23:00 (Evening phlebotomy drop)
        ]
    },
    # ------------------------------------------
    # ------------------------------------------

    # ------------------------------------------
    # Per SOP: MICRO-PLATING-058A ---------------------------
    "Stool": {
        "media_req": {"Blood_Agar": 1, "MacConkey": 1, "HE_Agar": 1, "Campy_CVA": 1, "CT-SMAC": 1, "GN_Broth": 1},
        "daily_volume_mean": 25,
        "tech_review_range": (2.0, 4.0), 
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
        "tech_review_range": (2.0, 4.0), 
        "hourly_arrival_weights": [0.04] * 24
    },
    # BACT-PLATING-048A.pptxAug122026021806.pdf
    # BCSA == Burkholderia cepacia Selective Agar
    "Resp_CystFibrosis": {
        "media_req": {"Chocolate": 1, "Blood_Agar": 1, "MacConkey": 1, "CNA_Agar": 1, "BCSA_Agar": 1},
        "daily_volume_mean": 25,
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
        "tech_review_range": (3.0, 5.0), 
        "hourly_arrival_weights": [0.04] * 24
    },
    "Wound_Genital": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1, "ThayerMartin": 1},
        "daily_volume_mean": 18,
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
        "tech_review_range": (4.0, 10.0), #
        "hourly_arrival_weights": [0.04] * 24
    },
    "Tissue_genital": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "MTM":1, "CNA_Agar": 1},
        "daily_volume_mean": 15,
        "tech_review_range": (4.0, 10.0), #
        "hourly_arrival_weights": [0.04] * 24
    },
    # MICRO-PLATING-092B ---
    "Tissue_FNA": {
        "media_req": {"FastidiousBroth": 1, "Chocolate_Agar": 1, "Blood_Agar": 1},
        "daily_volume_mean": 15,
        "tech_review_range": (4.0, 10.0), #
        "hourly_arrival_weights": [0.04] * 24
    },


    # ------------------------------------------
    # Per SOP: MICRO-PROC-045 ---------------------------
    "Bone_Cx": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1, "FastidiousBroth": 1}, 
        "daily_volume_mean": 75,
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
                            "tech_general": 4, "tech_blood": 2, "tech_routine": 4, "tech_urine": 2, "tech_new": 2,
                            "plating_capacity": 4},
        "Shift_2_Evening": {"hours": (15, 23),
                            "tech_general": 4, "tech_blood": 1, "tech_routine": 2, "tech_urine": 1, "tech_new": 2,
                            "plating_capacity": 3},
        "Shift_3_Night":   {"hours": (23, 7),
                            "tech_general": 2, "tech_blood": 1, "tech_routine": 1, "tech_urine": 1, "tech_new": 2,
                            "plating_capacity": 2}
    },
    "Weekend": {
        "Shift_1_Day":     {"hours": (7, 15), 
                            "tech_general": 3, "tech_blood": 1, "tech_routine": 2, "tech_urine": 1, "tech_new": 2,
                            "plating_capacity": 2},
        "Shift_2_Evening": {"hours": (15, 23),
                            "tech_general": 2, "tech_blood": 1, "tech_routine": 2, "tech_urine": 1,  "tech_new": 2,
                            "plating_capacity": 1},
        "Shift_3_Night":   {"hours": (23, 7), 
                            "tech_general": 2, "tech_blood": 1, "tech_routine": 2, "tech_urine": 1, "tech_new": 2,
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