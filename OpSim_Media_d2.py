import simpy
import random
import numpy as np
import pandas as pd

from collections import defaultdict

# =====================================================
# CONFIGURATION
# =====================================================

RANDOM_SEED = 42
SIM_DAYS = 365

# Average specimens per day
DAILY_SPECIMENS = 72
weekday_volume = 90
weekend_volume = 40

from Media_dictionary import MEDIA_TYPES
from Specimen_dictionary import SPECIMEN_TYPES

ORDER_LEAD_TIME = 3  # days
# if day in range(300, 365):
#     demand_multiplier = 1.30

# =====================================================
# INVENTORY MODEL
# =====================================================

class MediaInventory:

    # Create empty storage describing what is saved for each media type
    def __init__(self):
        self.inventory = defaultdict(list)
        self.pending_orders = []
        self.used = defaultdict(int)
        self.expired = defaultdict(int)
        self.stockouts = defaultdict(int)

    # ---------------------------------
    # Add new inventory ----
    # ---------------------------------
    def add_lot(self, media, qty, current_day):
        shelf_life = MEDIA_TYPES[media]["shelf_life"]

        # Add a new shipment of media -> add quantitiy + expiration of lot
        self.inventory[media].append(
            {
                "quantity": qty,
                "expiration_day": current_day + shelf_life
            }
        )

    # ---------------------------------
    # Calculate Total invetory across all lots
    # ---------------------------------
    def total_inventory(self, media):
        return sum(
            lot["quantity"]
            for lot in self.inventory[media]
        )

    # ---------------------------------
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
    # ---------------------------------
    def use_media(self, media):

        # Only consider lots that still have inventory
        available_lots = [
            lot for lot in self.inventory[media]
            if lot["quantity"] > 0
        ]

        if not available_lots:
            self.stockouts[media] += 1
            return False

        available_lots.sort(
            key=lambda x: x["expiration_day"]
        )
        # 90% of the time do First in first out (using older lot)
        # 10% random selection
        if random.random() < 0.90:
            lot = available_lots[0]      # oldest
        else:
            lot = available_lots[-1]     # newest

        lot["quantity"] -= 1
        self.used[media] += 1

        return True


        self.stockouts[media] += 1
        return False

    # ---------------------------------
    def place_order(self, media, current_day):

        qty = MEDIA_TYPES[media]["order_qty"]

        self.pending_orders.append(
            {
                "media": media,
                "qty": qty,
                "arrival_day": current_day + ORDER_LEAD_TIME
            }
        )

    # ---------------------------------

    def receive_orders(self, current_day):

        still_pending = []

        for order in self.pending_orders:

            if order["arrival_day"] <= current_day:

                self.add_lot(
                    order["media"],
                    order["qty"],
                    current_day
                )

            else:

                still_pending.append(order)

        self.pending_orders = still_pending


# =====================================================
# DAILY OPERATIONS
# =====================================================

def microbiology_lab(env, inventory):

    while True:

        current_day = env.now

        inventory.receive_orders(current_day)

        inventory.remove_expired(current_day)

        # Daily demand variability        
        day_of_week = int(current_day) % 7

        if day_of_week in [5, 6]:
            specimens = np.random.poisson(weekend_volume)
        else:
            specimens = np.random.poisson(weekday_volume)


        # Media utilization
        for _ in range(specimens):

            r = random.random()

            cumulative = 0

            for media, config in MEDIA_TYPES.items():

                cumulative += config["usage_pct"]

                if r <= cumulative:

                    inventory.use_media(media)
                    break

        # Reorder review
        for media in MEDIA_TYPES:

            on_hand = inventory.total_inventory(media)

            pending_qty = sum(
                o["qty"]
                for o in inventory.pending_orders
                if o["media"] == media
            )

            if (
                on_hand + pending_qty
                < MEDIA_TYPES[media]["reorder_point"]
            ):

                inventory.place_order(
                    media,
                    current_day
                )

        yield env.timeout(1)


# =====================================================
# REPORTING
# =====================================================

def print_results(inv):

    rows = []

    for media in MEDIA_TYPES:

        ending_inventory = inv.total_inventory(media)

        total_received = (
            inv.used[media]
            + inv.expired[media]
            + ending_inventory
        )

        waste_pct = (
            100 * inv.expired[media] / total_received
            if total_received > 0
            else 0
        )

        rows.append({
            "Media": media,
            "Used": inv.used[media],
            "Expired": inv.expired[media],
            "Stockouts": inv.stockouts[media],
            "Ending Inventory": ending_inventory,
            "Waste %": round(waste_pct, 2)
        })

    df = pd.DataFrame(rows)

    print("\nMICROBIOLOGY MEDIA INVENTORY REPORT\n")
    print(df.to_string(index=False))

# =====================================================
# MAIN
# =====================================================

def main():

    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    env = simpy.Environment()

    inventory = MediaInventory()

    # Starting inventory

    inventory.add_lot(
        "Blood Agar",
        400, 0
    )

    inventory.add_lot(
        "MacConkey",
        300, 0
    )

    env.process(
        microbiology_lab(
            env,
            inventory
        )
    )

    env.run(until=SIM_DAYS)

    print_results(inventory)


if __name__ == "__main__":
    main()