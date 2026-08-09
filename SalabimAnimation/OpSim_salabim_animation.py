"""
Package Requirements
--------------------
Python >= 3.10,<3.14

Required Packages:
    salabim
    greenlet
    pygame
    numpy
    pandas

Install with:

    pip install salabim greenlet pygame numpy pandas matplotlib

Recommended Conda Environment:

    conda create -n micro_sim python=3.12
    conda activate micro_sim
    pip install salabim greenlet pygame numpy pandas matplotlib

Note:
    Salabim animation is currently not compatible with Python 3.14 due
    to pygame dependency limitations. Python 3.12 is recommended.
"""

import salabim as sim

import random
import numpy as np

RANDOM_SEED = 42
ORDER_LEAD_TIME = 3

weekday_volume = 90
weekend_volume = 40

from collections import defaultdict
import random

ORDER_LEAD_TIME = 3


class MediaInventory:

    def __init__(self):

        self.inventory = defaultdict(list)

        self.pending_orders = []

        self.used = defaultdict(int)

        self.expired = defaultdict(int)

        self.stockouts = defaultdict(int)

    def add_lot(self, media, qty, current_day):

        shelf_life = MEDIA_TYPES[media]["shelf_life"]

        self.inventory[media].append(
            {
                "quantity": qty,
                "expiration_day": current_day + shelf_life
            }
        )

    def total_inventory(self, media):

        return sum(
            lot["quantity"]
            for lot in self.inventory[media]
        )

    def remove_expired(self, current_day):

        for media in MEDIA_TYPES:

            remaining = []

            for lot in self.inventory:
                if lot["expiration_day"] <= current_day:

                    self.expired[media] += lot["quantity"]

                else:

                    remaining.append(lot)

            self.inventory[media] = remaining

    def use_media(self, media):

        available_lots = [
            lot
            for lot in self.inventory[media]
            if lot["quantity"] > 0
        ]

        if not available_lots:

            self.stockouts[media] += 1

            return False

        available_lots.sort(
            key=lambda x: x["expiration_day"]
        )

        if random.random() < 0.90:

            lot = available_lots[0]

        else:

            lot = available_lots[-1]

        lot["quantity"] -= 1

        self.used[media] += 1

        return True

    def place_order(self, media, current_day):

        qty = MEDIA_TYPES[media]["order_qty"]

        self.pending_orders.append(
            {
                "media": media,
                "qty": qty,
                "arrival_day": current_day + ORDER_LEAD_TIME
            }
        )

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


class MicrobiologyLab(sim.Component):

    def setup(self, inventory):
        self.inventory = inventory

    def process(self):

        while True:

            current_day = int(env.now())

            self.inventory.receive_orders(current_day)

            self.inventory.remove_expired(current_day)

            day_of_week = current_day % 7

            if day_of_week in [5, 6]:
                specimens = np.random.poisson(weekend_volume)
            else:
                specimens = np.random.poisson(weekday_volume)

            # consume media

            for _ in range(specimens):

                r = random.random()

                cumulative = 0

                for media, config in MEDIA_TYPES.items():

                    cumulative += config["usage_pct"]

                    if r <= cumulative:

                        self.inventory.use_media(media)

                        break

            # reorder review

            for media in MEDIA_TYPES:

                on_hand = self.inventory.total_inventory(media)

                pending_qty = sum(
                    o["qty"]
                    for o in self.inventory.pending_orders
                    if o["media"] == media
                )

                if (
                    on_hand + pending_qty
                    < MEDIA_TYPES[media]["reorder_point"]
                ):

                    self.inventory.place_order(
                        media,
                        current_day
                    )

            yield self.hold(1)

class InventoryDashboard:

    def __init__(self, inventory):

        self.inventory = inventory

        sim.AnimateText(
            text=lambda:
                f"Day {int(env.now())}",
            x=50,
            y=750
        )

        y = 650

        for media in MEDIA_TYPES:

            sim.AnimateText(
                text=media,
                x=50,
                y=y
            )

            sim.AnimateRectangle(
                x=250,
                y=y,
                width=lambda m=media:
                    max(
                        self.inventory.total_inventory(m) / 3,
                        5
                    ),
                height=25,
                fillcolor=lambda m=media:
                    (
                        "red"
                        if self.inventory.total_inventory(m)
                        <= MEDIA_TYPES[m]["reorder_point"]
                        else "orange"
                        if self.inventory.total_inventory(m)
                        <= (
                            MEDIA_TYPES[m]["reorder_point"] * 1.5
                        )
                        else "green"
                    )
            )

            sim.AnimateText(
                text=lambda m=media:
                    str(
                        self.inventory.total_inventory(m)
                    ),
                x=600,
                y=y
            )

            y -= 60


class KPIBoard:

    def __init__(self, inventory):

        self.inventory = inventory

        sim.AnimateText(
            text=lambda:
                f"Stockouts: "
                f"{sum(self.inventory.stockouts.values())}",
            x=900,
            y=700
        )

        sim.AnimateText(
            text=lambda:
                f"Expired: "
                f"{sum(self.inventory.expired.values())}",
            x=900,
            y=650
        )

        sim.AnimateText(
            text=lambda:
                f"Pending Orders: "
                f"{len(self.inventory.pending_orders)}",
            x=900,
            y=600
        )


class DashboardUpdater(sim.Component):

    def setup(self, dashboard, kpi):

        self.dashboard = dashboard
        self.kpi = kpi

    def process(self):

        while True:

            current_day = env.now()

            self.dashboard.update(current_day)

            self.kpi.update()

            yield self.hold(1)


class OrderMonitor:

    def __init__(self, inventory):

        self.inventory = inventory

        sim.AnimateText(
            text=self.order_text,
            x=900,
            y=500
        )

    def order_text(self):

        txt = "Pending Orders\n\n"

        for order in self.inventory.pending_orders:

            eta = (
                order["arrival_day"] - env.now()
            )

            txt += (
                f"{order['media']}  "
                f"Qty:{order['qty']}  "
                f"ETA:{eta:.0f}d\n"
            )

        return txt



random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

env = sim.Environment(trace=False)

inventory = MediaInventory()

# starting inventory

inventory.add_lot(
    "Blood Agar",
    400,
    0
)

inventory.add_lot(
    "MacConkey",
    300,
    0
)

# dashboard

InventoryDashboard(inventory)
KPIBoard(inventory)
OrderMonitor(inventory)

# simulation

MicrobiologyLab(inventory=inventory)

env.speed(30)

env.run(SIM_DAYS)