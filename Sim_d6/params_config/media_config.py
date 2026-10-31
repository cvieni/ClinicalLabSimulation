"""Media inventory configuration.

Units: every quantity below ends up in SINGLE PLATES (or tubes) inside the simulation.

Two replenishment mechanisms, both optional per medium (modules/inventory.py):
  * STANDING order : `order_frequency` days -> `standing_order_qty` plates arrive on that cycle, whatever the stock.
  * SHORTAGE order : when (on hand + on order) <= `reorder_point` plates, order `order_qty` plates, delivered after
                     `lead_time_days` (default: MediaInventory's order_lead_time_days, set from params).
A medium with `reorder_point = None` has no shortage trigger (standing only); `order_frequency = None` means no standing order.
"""

# ---- what lab's table says -------------------------------------------------------------------
# minimum_order_qnty  = number of ordering units (cases/sleeves) per order      <- CONFIRM what "Minimum Reorder" means
# plates_per_order    = plates in one unit                                      <- CONFIRM (see note in the chat: 60 x 67 = 4,020)
# order_frequency     = days between standing deliveries, None if no standing order

# Blood, MacConkey, CNA, and GN broth all still starved
# real_world_media_orders = {
#     "Blood_Agar":     {"minimum_order_qnty": 60, "plates_per_order": 67, "order_frequency": 7},
#     "MacConkey":      {"minimum_order_qnty": 30, "plates_per_order": 30, "order_frequency": 7},
#     # "MacConkey":      {"minimum_order_qnty": 12, "plates_per_order": 15, "order_frequency": 7}, # 64% media starved
#     "CNA_Agar":       {"minimum_order_qnty": 17, "plates_per_order": 18, "order_frequency": 30},
#     # "CNA_Agar":         {"minimum_order_qnty": 22, "plates_per_order" = 18, "order_frequency" = 30}, # unclear to me in chad's table he wrote standing order 22 deliveryed once a month, but the column says 17
#     "Chocolate_Agar": {"minimum_order_qnty": 32, "plates_per_order": 35, "order_frequency": 30},
#     # "Chocolate_Agar":   {"minimum_order_qnty": 48, "plates_per_order" = 35, "order_frequency" = 30}, # unclear to me in chad's table he wrote standing order 48 deliveryed once 
#     "ThayerMartin":   {"minimum_order_qnty": 6,  "plates_per_order": 8,  "order_frequency": None},
#     "ChromeAgar":     {"minimum_order_qnty": 30,  "plates_per_order": 30,  "order_frequency": None},
#     # "ChromeAgar":     {"minimum_order_qnty": 7,  "plates_per_order": 8,  "order_frequency": None}, # 78 % would be starved
#     "GN_Broth":       {"minimum_order_qnty": 13, "plates_per_order": 15, "order_frequency": None},
#     "CT-SMAC":        {"minimum_order_qnty": 74, "plates_per_order": 80, "order_frequency": None},
#     "TCBS":           {"minimum_order_qnty": 4,  "plates_per_order": 7,  "order_frequency": None},
# }

real_world_media_orders = {
    "Blood_Agar":     {"minimum_order_qnty": 80, "plates_per_order": 67, "order_frequency": 7},
    "MacConkey":      {"minimum_order_qnty": 50, "plates_per_order": 30, "order_frequency": 7},
    "CNA_Agar":       {"minimum_order_qnty": 50, "plates_per_order": 18, "order_frequency": 30},
    "Chocolate_Agar": {"minimum_order_qnty": 32, "plates_per_order": 35, "order_frequency": 30},
    "ThayerMartin":   {"minimum_order_qnty": 6,  "plates_per_order": 8,  "order_frequency": None},
    "ChromeAgar":     {"minimum_order_qnty": 30,  "plates_per_order": 30,  "order_frequency": None},
    "GN_Broth":       {"minimum_order_qnty": 20, "plates_per_order": 15, "order_frequency": None},
    "CT-SMAC":        {"minimum_order_qnty": 74, "plates_per_order": 80, "order_frequency": None},
    "TCBS":           {"minimum_order_qnty": 4,  "plates_per_order": 7,  "order_frequency": None},
}

base_media_config = {
    "Blood_Agar":      {"cost": 1.0, "shelf_life": 90, "reorder_point": 8000, "order_qty": 11000, "initial": 13735},
    "MacConkey":       {"cost": 1.0, "shelf_life": 60, "reorder_point": 3000, "order_qty": 5000,  "initial": 6000},
    "CNA_Agar":        {"cost": 1.0, "shelf_life": 60, "reorder_point": 3000, "order_qty": 5000,  "initial": 6000},
    "Chocolate_Agar":  {"cost": 1.0, "shelf_life": 60, "reorder_point": 3500, "order_qty": 5000,  "initial": 6000},
    "ThayerMartin":    {"cost": 1.0, "shelf_life": 60, "reorder_point": 20,   "order_qty": 48,    "initial": 30},
    "ChromeAgar":      {"cost": 2.0, "shelf_life": 60, "reorder_point": 3220, "order_qty": 56,  "initial": 5470},
    "GN_Broth":        {"cost": 1.0, "shelf_life": 150, "reorder_point": 1500,  "order_qty": 1000,   "initial": 2500}, # fastidious organism broth
    "CT-SMAC":         {"cost": 1.0, "shelf_life": 30, "reorder_point": 1000, "order_qty": 1000,  "initial": 1200},
    # "FastidiousBroth": {"cost": 1.0, "shelf_life": 150, "reorder_point": 420,  "order_qty": 195,  "initial": 710},
    "TCBS":            {"cost": 1.0, "shelf_life": 90, "reorder_point": 500, "order_qty": 500,  "initial": 1000},

    "HE_Agar":         {"cost": 1.0, "shelf_life": 30, "reorder_point": 2000, "order_qty": 1100,  "initial": 4000},
    "Campy_CVA":       {"cost": 1.0, "shelf_life": 30, "reorder_point": 1000, "order_qty": 1100,  "initial": 4000},
    "BCSA_Agar":       {"cost": 1.0, "shelf_life": 30, "reorder_point": 800, "order_qty": 500,  "initial": 800},
    "MTM":             {"cost": 1.0, "shelf_life": 30, "reorder_point": 250,  "order_qty": 250,   "initial": 500},
    # "IMA":             {"cost": 1.0, "shelf_life": 20, "reorder_point": 10,   "order_qty": 10,    "initial": 15},
}

_NO_ORDER_INFO = {"minimum_order_qnty": None, "plates_per_order": None, "order_frequency": None}


def _build_media_config() -> dict:
    cfg = {}
    for media, details in base_media_config.items():
        info = {**_NO_ORDER_INFO, **real_world_media_orders.get(media, {})}
        units = info.get("standing_units") or info["minimum_order_qnty"]
        plates_per_unit = info["plates_per_order"]
        order_qty = units * plates_per_unit if units is not None and plates_per_unit is not None else details["order_qty"]
        freq = info["order_frequency"]
        cfg[media] = {
            **details,
            "order_qty": order_qty,
            # BOTH mechanisms stay active: the shortage trigger is no longer switched off by a standing order.
            "reorder_point": details.get("reorder_point"),
            "order_frequency": freq,
            "standing_order_qty": order_qty if freq else None,
            "standing_order_interval_days": freq,
        }
    return cfg


MEDIA_CONFIG = _build_media_config()