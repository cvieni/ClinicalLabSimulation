# MEDIA_CONFIG = {
#     "Blood_Agar": { "cost": 1.3,#                    "shelf_life": 45, "reorder_point": 500, "order_qty": 2000,#                    "initial": 2000},
#     "MacConkey": {"cost": 1.0,#                   "shelf_life": 60, "reorder_point": 150, "order_qty": 500,#                   "initial": 2000},
#     "CNA_Agar": {"cost": 1.0,#                  "shelf_life": 30, "reorder_point": 100, "order_qty": 200,#                  "initial": 2000},
#     "Chocolate_Agar": {"cost": 1.0,#                        "shelf_life": 30, "reorder_point": 80, "order_qty": 1000,#                        "initial": 2000},
#     "ThayerMartin": {"cost": 1.0,#                   "shelf_life": 30, "reorder_point": 80, "order_qty": 1000,#                   "initial": 2000},
#     "ChromeAgar": {"cost": 1.5,#                   "shelf_life": 30, "reorder_point": 150, "order_qty": 1000,#                   "initial": 2000},
#     "MTM":{"cost": 1.5,#                   "shelf_life": 30, "reorder_point": 20, "order_qty": 100,#                   "initial": 2000},
#     "IMA": {"cost": 1.0,#         "shelf_life": 20, "reorder_point": 75, "order_qty": 300,#         "initial": 2000},
#     "FastidiousBroth": {"cost": 1.0,#         "shelf_life": 20, "reorder_point": 75, "order_qty": 300,#         "initial": 2000}
# }

# Claude recommended ---------------------------
# MEDIA_CONFIG = {
#     "Blood_Agar":      {"cost": 1.3, "shelf_life": 45, "reorder_point": 2000, "order_qty": 10280, "initial": 12490},
#     "Chocolate_Agar":  {"cost": 1.0, "shelf_life": 30, "reorder_point": 3960, "order_qty": 5540,  "initial": 6730},
#     "ChromeAgar":      {"cost": 1.5, "shelf_life": 30, "reorder_point": 3220, "order_qty": 4500,  "initial": 5470},
#     "MacConkey":       {"cost": 1.0, "shelf_life": 60, "reorder_point": 2910, "order_qty": 4080,  "initial": 4950},
#     "CNA_Agar":        {"cost": 1.0, "shelf_life": 30, "reorder_point": 2430, "order_qty": 3400,  "initial": 4130},
#     "HE_Agar":         {"cost": 1.0, "shelf_life": 30, "reorder_point": 2430, "order_qty": 3400,  "initial": 4130},
#     "Campy_CVA":       {"cost": 1.0, "shelf_life": 30, "reorder_point": 2430, "order_qty": 3400,  "initial": 4130},
#     "CT-SMAC":         {"cost": 1.0, "shelf_life": 30, "reorder_point": 2430, "order_qty": 3400,  "initial": 4130},
#     "BCSA_Agar":       {"cost": 1.0, "shelf_life": 30, "reorder_point": 2430, "order_qty": 3400,  "initial": 4130},
#     "GN_Broth": {"cost": 1.0, "shelf_life": 20, "reorder_point": 420,  "order_qty": 580,   "initial": 710}, # fastidious organism broth
#     "MTM":             {"cost": 1.5, "shelf_life": 30, "reorder_point": 170,  "order_qty": 240,   "initial": 290},
#     "ThayerMartin":    {"cost": 1.0, "shelf_life": 30, "reorder_point": 20,   "order_qty": 20,    "initial": 30},
#     "IMA":             {"cost": 1.0, "shelf_life": 20, "reorder_point": 10,   "order_qty": 10,    "initial": 15},
# }

# minimum order is: # of orders
# plates per order: # number of plates per single order
# order frequency: if there is a standing order, how frequent in **days**

real_world_media_orders = {
    "Blood_Agar":     {"minimum_order_qnty": 60, "plates_per_order": 67, "order_frequency": 7},
    "MacConkey":      {"minimum_order_qnty": 12, "plates_per_order": 15, "order_frequency": 7},
    "CNA_Agar":       {"minimum_order_qnty": 17, "plates_per_order": 18, "order_frequency": 30},
    # "CNA_Agar":         {"minimum_order_qnty": 22, "plates_per_order" = 18, "order_frequency" = 30}, # unclear to me in chad's table he wrote standing order 22 deliveryed once a month, but the column says 17
    "Chocolate_Agar": {"minimum_order_qnty": 32, "plates_per_order": 35, "order_frequency": 30},
    # "Chocolate_Agar":   {"minimum_order_qnty": 48, "plates_per_order" = 35, "order_frequency" = 30}, # unclear to me in chad's table he wrote standing order 48 deliveryed once 
    "ThayerMartin":   {"minimum_order_qnty": 6,  "plates_per_order": 8,  "order_frequency": None},
    "ChromeAgar":     {"minimum_order_qnty": 7,  "plates_per_order": 8,  "order_frequency": None},
    "GN_Broth":       {"minimum_order_qnty": 13, "plates_per_order": 15, "order_frequency": None},
    "CT-SMAC":        {"minimum_order_qnty": 74, "plates_per_order": 80, "order_frequency": None},
    "TCBS":           {"minimum_order_qnty": 4,  "plates_per_order": 7,  "order_frequency": None},
}

base_media_config = {
    "Blood_Agar":      {"cost": 1.0, "shelf_life": 90, "reorder_point": 2000, "order_qty": 4020, "initial": 10000},
    "MacConkey":       {"cost": 1.0, "shelf_life": 60, "reorder_point": 2910, "order_qty": 180,  "initial": 4950},
    "CNA_Agar":        {"cost": 1.0, "shelf_life": 60, "reorder_point": 2430, "order_qty": 306,  "initial": 4130},
    "Chocolate_Agar":  {"cost": 1.0, "shelf_life": 60, "reorder_point": 3960, "order_qty": 1120,  "initial": 6730},
    "ThayerMartin":    {"cost": 1.0, "shelf_life": 60, "reorder_point": 20,   "order_qty": 48,    "initial": 30},
    "ChromeAgar":      {"cost": 1.0, "shelf_life": 60, "reorder_point": 3220, "order_qty": 56,  "initial": 5470},
    "GN_Broth":        {"cost": 1.0, "shelf_life": 150, "reorder_point": 420,  "order_qty": 195,   "initial": 710}, # fastidious organism broth
    "CT-SMAC":         {"cost": 1.0, "shelf_life": 30, "reorder_point": 2430, "order_qty": 5920,  "initial": 4130},
    
    "TCBS":            {"cost": 1.0, "shelf_life": 90, "reorder_point": 500, "order_qty": 28,  "initial": 1000},

    "HE_Agar":         {"cost": 1.0, "shelf_life": 30, "reorder_point": 2000, "order_qty": 1100,  "initial": 4000},
    "Campy_CVA":       {"cost": 1.0, "shelf_life": 30, "reorder_point": 1000, "order_qty": 1100,  "initial": 4000},
    "BCSA_Agar":       {"cost": 1.0, "shelf_life": 30, "reorder_point": 1000, "order_qty": 500,  "initial": 2000},
    "MTM":             {"cost": 1.0, "shelf_life": 30, "reorder_point": 500,  "order_qty": 250,   "initial": 1000},
    # "IMA":             {"cost": 1.0, "shelf_life": 20, "reorder_point": 10,   "order_qty": 10,    "initial": 15},
}

# Fallback values if media entry is missing from real_world_media_orders
fallback_order_info = {
    "minimum_order_qnty": None,
    "plates_per_order": None,
    "order_frequency": None,
}

# Construct MEDIA_CONFIG dynamically
MEDIA_CONFIG = {}

for media, details in base_media_config.items():
    order_info = real_world_media_orders.get(media, fallback_order_info)
    
    # 1. Calculate order_qty (min_qty * plates_per_order), fallback to base config
    min_qty = order_info.get("minimum_order_qnty")
    plates = order_info.get("plates_per_order")
    
    if min_qty is not None and plates is not None:
        calculated_order_qty = min_qty * plates
    else:
        calculated_order_qty = details.get("order_qty", 500)
        
    # 2. Determine reorder strategy based on order_frequency
    freq = order_info.get("order_frequency")
    
    if freq is not None:
        # Standing order strategy: reorder_point is ignored (set to None)
        reorder_point = None
    else:
        # Plate-threshold strategy: fall back to numerical reorder_point
        reorder_point = details.get("reorder_point")
        
    MEDIA_CONFIG[media] = {
        **details,
        "order_qty": calculated_order_qty,
        "reorder_point": reorder_point,
        **order_info,
    }
