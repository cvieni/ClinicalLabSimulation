# Shift staffing profiles (Tech availability multiplier throughout the day)
# Separate Weekday vs. Weekend staffing profiles
# tech_general == tech that does general accessioning and plating from specimen

#  ------------- Actual values from the Lab ---------------------
SHIFT_STAFFING_PROFILE = {
    "Weekday": {
        "Shift_1_Day":     {"hours": (7, 15),
                            "tech_accession": 12, "tech_plating": 8, "tech_blood": 2, "tech_routine": 3, "tech_stool": 1,  "tech_urine": 2, "tech_new": 2, "tech_float": 2,
                            "plating_capacity": 4},
        "Shift_2_Evening": {"hours": (15, 23),
                            "tech_accession": 11, "tech_plating": 6, "tech_blood": 1, "tech_routine": 2, "tech_stool": 0, "tech_urine": 1, "tech_new": 2, "tech_float": 1,
                            "plating_capacity": 3},
        "Shift_3_Night":   {"hours": (23, 7),
                            "tech_accession": 6, "tech_plating": 4, "tech_blood": 1, "tech_routine": 1, "tech_stool": 0, "tech_urine": 1, "tech_new": 2, "tech_float": 1,
                            "plating_capacity": 2}
    },
    "Weekend": {
        "Shift_1_Day":     {"hours": (7, 15), 
                            "tech_accession": 12, "tech_plating": 8, "tech_blood": 1, "tech_routine": 2, "tech_stool": 1, "tech_urine": 1, "tech_new": 2, "tech_float": 2,
                            "plating_capacity": 2},
        "Shift_2_Evening": {"hours": (15, 23),
                            "tech_accession": 10, "tech_plating": 6, "tech_blood": 1, "tech_routine": 2, "tech_stool": 0, "tech_urine": 1,  "tech_new": 2, "tech_float": 1,
                            "plating_capacity": 1},
        "Shift_3_Night":   {"hours": (23, 7), 
                            "tech_accession": 5, "tech_plating": 4, "tech_blood": 1, "tech_routine": 2, "tech_stool": 0, "tech_urine": 1, "tech_new": 2, "tech_float": 1,
                            "plating_capacity": 1}
    }
}


# ----- Tuned values for troubleshooting ------------------------
# SHIFT_STAFFING_PROFILE = {
#     "Weekday": {
#         "Shift_1_Day":     {"hours": (7, 15),
#                             "tech_accession": 24, "tech_plating": 8, "tech_blood": 2, "tech_routine": 3, "tech_stool": 1,  "tech_urine": 2, "tech_new": 2, "tech_float": 2,
#                             "plating_capacity": 4},
#         "Shift_2_Evening": {"hours": (15, 23),
#                             "tech_accession": 22, "tech_plating": 6, "tech_blood": 1, "tech_routine": 2, "tech_stool": 0, "tech_urine": 1, "tech_new": 2, "tech_float": 1,
#                             "plating_capacity": 3},
#         "Shift_3_Night":   {"hours": (23, 7),
#                             "tech_accession": 12, "tech_plating": 4, "tech_blood": 1, "tech_routine": 1, "tech_stool": 0, "tech_urine": 1, "tech_new": 2, "tech_float": 1,
#                             "plating_capacity": 2}
#     },
#     "Weekend": {
#         "Shift_1_Day":     {"hours": (7, 15), 
#                             "tech_accession": 22, "tech_plating": 8, "tech_blood": 1, "tech_routine": 2, "tech_stool": 1, "tech_urine": 1, "tech_new": 2, "tech_float": 2,
#                             "plating_capacity": 2},
#         "Shift_2_Evening": {"hours": (15, 23),
#                             "tech_accession": 20, "tech_plating": 6, "tech_blood": 1, "tech_routine": 2, "tech_stool": 0, "tech_urine": 1,  "tech_new": 2, "tech_float": 1,
#                             "plating_capacity": 1},
#         "Shift_3_Night":   {"hours": (23, 7), 
#                             "tech_accession": 10, "tech_plating": 4, "tech_blood": 1, "tech_routine": 2, "tech_stool": 0, "tech_urine": 1, "tech_new": 2, "tech_float": 1,
#                             "plating_capacity": 1}
#     }
# }
