import simpy
import random
import numpy as np
import pandas as pd
import random

import matplotlib.pyplot as plt
import graphviz
from collections import defaultdict

from Media_dictionary import MEDIA_TYPES
from Specimen_dictionary import SPECIMEN_TYPES

# Graphing functions
from modules.GraphingFunctions import plot_workflow, plot_media_and_orders, plot_culture_volumes

# Helper Functions
from modules.helperfunctions import adjust_for_weekend_delivery, cult_vol


# =====================================================
# CONFIGURATION
# =====================================================

RANDOM_SEED = 42
SIM_DAYS = 365
ORDER_LEAD_TIME = 3  # days



# =====================================================
# ML model for predicting test volume
# =====================================================
# Example interface for feeding ML predictions into SimPy
import joblib


class DailyVolumeForecaster:

  def __init__(self, model_path):
    self.model = joblib.load(model_path)

  def predict_daily_workload(self, current_day, calendar_date):
    # Construct feature vector based on calendar date & recent lag history
    features = extract_features(calendar_date)
    # Model predicts expected volume vector across specimen types
    predicted_counts = self.model.predict([features])[0]
    return predicted_counts  # e.g. {'BCx': 45, 'UCx': 180, 'TissCx': 25}

# =====================================================
# INVENTORY MODEL
# =====================================================

class MediaInventory:

    # Create empty storage describing what is saved for each media type
    def __init__(self):
        self.inventory = defaultdict(list)
        self.pending_orders = defaultdict(int)  # On-order quantities
        self.used = defaultdict(int)
        self.expired = defaultdict(int)
        self.stockouts = defaultdict(int)
        self.order_queue = []

        # Tracking metrics for daily plotting
        self.daily_used = defaultdict(lambda: defaultdict(int))
        self.daily_expired = defaultdict(lambda: defaultdict(int))
        self.order_events = []

    # ---------------------------------
    # Add new inventory ----
    # ---------------------------------
    def add_lot(self, media, qty, current_day):
        shelf_life = MEDIA_TYPES[media]["shelf_life"]

        # Add a new shipment of media -> add quantitiy + expiration of lot
        self.inventory[media].append({
            "quantity": qty,
            "expiration_day": current_day + shelf_life
        })

    # ---------------------------------
    # Calculate Total invetory across all lots
    # ---------------------------------
    def total_inventory(self, media):
        return sum(lot["quantity"] for lot in self.inventory[media])

    def remove_expired(self, current_day):
            for media in MEDIA_TYPES:
                remaining = []
                for lot in self.inventory[media]:
                    if lot["expiration_day"] <= current_day:
                        self.expired[media] += lot["quantity"]
                    else:
                        remaining.append(lot)
                self.inventory[media] = remaining

    # ---------------------------------
    #  Function to Use Media + consume plate ----------------
    def use_media(self, media, current_day, qty=1):
        for _ in range(qty):
            available_lots = [lot for lot in self.inventory[media] if lot["quantity"] > 0]

            if not available_lots:
                self.stockouts[media] += 1
                continue

            # Sort lots by earliest expiration (FIFO)
            available_lots.sort(key=lambda x: x["expiration_day"])

            # 90% FIFO, 10% mis-pick noise
            lot = available_lots[0] if random.random() < 0.90 else available_lots[-1]

            lot["quantity"] -= 1
            self.used[media] += 1
            self.daily_used[current_day][media] += 1

    # ---------------------------------
    def place_order(self, media, current_day):
        qty = MEDIA_TYPES[media]["order_qty"]
        self.pending_orders[media] += qty

        # Calculate arrival date considering weekend delivery restrictions
        raw_arrival = current_day + ORDER_LEAD_TIME
        actual_arrival = adjust_for_weekend_delivery(raw_arrival)

        # FIXED: Use actual_arrival instead of raw calculation
        self.order_queue.append({
            "media": media,
            "qty": qty,
            "arrival_day": actual_arrival
        })
        self.order_events.append((current_day, media))

    # ---------------------------------
    def receive_orders(self, current_day):
        still_pending = []
        for order in self.order_queue:
            if order["arrival_day"] <= current_day:
                self.add_lot(order["media"], order["qty"], current_day)
                self.pending_orders[order["media"]] -= order["qty"]
            else:
                still_pending.append(order)
        self.order_queue = still_pending

# =====================================================
# DAILY OPERATIONS
# =====================================================

def microbiology_lab(env, inventory, metrics_log):
    all_media_list = list(MEDIA_TYPES.keys())

    while True:
        current_day = env.now

        # 1. Morning Inventory Ops
        inventory.receive_orders(current_day)
        inventory.remove_expired(current_day)

        # 2. Workload Generation
        day_of_week = int(current_day) % 7
        is_weekend = day_of_week in [5, 6]
        daily_counts = cult_vol(is_weekend)

        # Daily metric tracking
        day_metrics = {"Day": current_day}

        # -----------------------------------------------------
        # 3. SPECIAL CASE: Blood Cultures (Flag-Triggered Workflow)
        # -----------------------------------------------------
        bcx_count = daily_counts.get("BCx", 0)
        bcx_cfg = SPECIMEN_TYPES.get("BCx", {})
        pos_rate = bcx_cfg.get("positivity_rate", 0.10)
        pos_bcx = np.random.binomial(n=bcx_count, p=pos_rate)

        day_metrics["BCx_Vol"] = bcx_count
        day_metrics["BCx_Pos_Pct"] = (pos_bcx / bcx_count * 100) if bcx_count > 0 else 0

        for _ in range(pos_bcx):
            for media, qty in bcx_cfg.get("media_req", {}).items():
                inventory.use_media(media, current_day, qty)

        # -----------------------------------------------------
        # 4. DYNAMIC LOOP: All Direct-Plated Specimens
        # -----------------------------------------------------
        for spec_code, spec_cfg in SPECIMEN_TYPES.items():
            if spec_code == "BCx":
                continue  # Handled above

            count = daily_counts.get(spec_code, 0)
            sub_count = 0

            for _ in range(count):
                # Inoculate primary set
                for media, qty in spec_cfg.get("media_req", {}).items():
                    inventory.use_media(media, current_day, qty)

                # Inoculate subcultures if organism grows
                if random.random() < spec_cfg.get("subculture_prob", 0):
                    sub_count += 1
                    sub_media = random.choice(all_media_list)
                    inventory.use_media(sub_media, current_day, 1)

            day_metrics[f"{spec_code}_Vol"] = count
            day_metrics[f"{spec_code}_Pos_Pct"] = (sub_count / count * 100) if count > 0 else 0

        metrics_log.append(day_metrics)
    
        # -----------------------------------------------------
        # 5. Periodic Inventory Review (Checked once per day)
        # -----------------------------------------------------
        for media in MEDIA_TYPES:
            on_hand = inventory.total_inventory(media)
            on_order = inventory.pending_orders[media]

            if (on_hand + on_order) < MEDIA_TYPES[media]["reorder_point"]:
                inventory.place_order(media, current_day)

        # Advance simulation time by 1 day
        yield env.timeout(1)


# =====================================================
# REPORTING
# =====================================================

def print_results(inv):

    rows = []
    for media in MEDIA_TYPES:
        ending_inventory = inv.total_inventory(media)
        total_received = inv.used[media] + inv.expired[media] + ending_inventory

        waste_pct = (
            100 * inv.expired[media] / total_received
            if total_received > 0
            else 0
        )

        rows.append({
            "Media": media,
            "Plates Used": inv.used[media],
            "Expired": inv.expired[media],
            "Stockouts": inv.stockouts[media],
            "Ending Inventory": ending_inventory,
            "Waste %": round(waste_pct, 2)
        })

    df = pd.DataFrame(rows)

    print("\nMICROBIOLOGY MEDIA INVENTORY REPORT (365 Days)\n")
    print(df.to_string(index=False))


# =====================================================
# MAIN
# =====================================================

def main():

    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    env = simpy.Environment()
    inventory = MediaInventory()
    metrics_log = []

    # FIXED: Automatically initialize baseline stock for ALL media types in MEDIA_TYPES
    for media, cfg in MEDIA_TYPES.items():
        inventory.add_lot(media, cfg["order_qty"], 0)

    env.process(microbiology_lab(env, inventory, metrics_log))
    env.run(until=SIM_DAYS)

    print_results(inventory)

    # Visualization
    plot_workflow(output_dir="output_pngs")
    plot_media_and_orders(inventory, SIM_DAYS, output_dir="output_pngs")
    plot_culture_volumes(metrics_log, output_dir="output_pngs")


if __name__ == "__main__":
    main()