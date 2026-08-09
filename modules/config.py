# config.py

SPECIMEN_TYPES = {
    "Urine": {
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
        "media_req": {"Blood_Agar": 2, "Chocolate_Agar": 1},
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
        "Wound": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1},
        "daily_volume_mean": 18,
        "tech_review_range": (3.0, 5.0), 
        "hourly_arrival_weights": [0.04] * 24
    },
    "Tissue": {
        "media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1, "MacConkey": 1, "CNA_Agar": 1},
        "daily_volume_mean": 15,
        "tech_review_range": (4.0, 10.0), #
        "hourly_arrival_weights": [0.04] * 24
    }
}

MEDIA_CONFIG = {
    "Blood_Agar": {"usage_pct": 1.0, "cost": 1.3,
                   "shelf_life": 45, "reorder_point": 200, "order_qty": 2000,
                   "initial": 200},
    "MacConkey": {"usage_pct": 0.8, "cost": 1.0,
                  "shelf_life": 60, "reorder_point": 150, "order_qty": 500,
                  "initial": 200},
    "CNA_Agar": {"usage_pct": 0.8, "cost": 1.0,
                 "shelf_life": 30, "reorder_point": 100, "order_qty": 200,
                 "initial": 200},
    "Chocolate_Agar": {"usage_pct": 1.0, "cost": 1.0,
                       "shelf_life": 30, "reorder_point": 80, "order_qty": 1000,
                       "initial": 200},
    "ChromeAgar": {"usage_pct": 1.0, "cost": 1.5,
                  "shelf_life": 30, "reorder_point": 150, "order_qty": 1000,
                  "initial": 200},
    "IMA": {"usage_pct": 0.20, "cost": 1.0,
        "shelf_life": 20, "reorder_point": 75, "order_qty": 300,
        "initial": 200}
}


# Shift staffing profiles (Tech availability multiplier throughout the day)
# Separate Weekday vs. Weekend staffing profiles
SHIFT_STAFFING_PROFILE = {
    "Weekday": {
        "Shift_1_Day":     {"hours": (7, 15),  "tech_capacity": 5, "plating_capacity": 4},
        "Shift_2_Evening": {"hours": (15, 23), "tech_capacity": 3, "plating_capacity": 2},
        "Shift_3_Night":   {"hours": (23, 7),  "tech_capacity": 1, "plating_capacity": 1}
    },
    "Weekend": {
        "Shift_1_Day":     {"hours": (7, 15),  "tech_capacity": 2, "plating_capacity": 2},
        "Shift_2_Evening": {"hours": (15, 23), "tech_capacity": 2, "plating_capacity": 1},
        "Shift_3_Night":   {"hours": (23, 7),  "tech_capacity": 1, "plating_capacity": 1}
    }
}