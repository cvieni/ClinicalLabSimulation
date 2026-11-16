# inventory.py  (instrumented: same behaviour as before, plus a per-day log used by manuscript FigS6)
from collections import defaultdict
import numpy as np
import pandas as pd

LAST_DAILY = None   # DataFrame of the replication that just finished; written to media_###.csv.gz by run_montecarlo_and_plot.py


def _day_table():
    return defaultdict(lambda: defaultdict(float))


class MediaInventory:
    def __init__(self, env, media_cfg, order_lead_time_days=3):
        global LAST_DAILY
        LAST_DAILY = None                      # never carry the previous replication's log into this one
        self.env = env
        self.media_cfg = media_cfg
        self.lead_time_mins = order_lead_time_days * 1440
        self.lots = defaultdict(list)
        self.pending_orders = defaultdict(int)
        self.waste_log = defaultdict(int)
        # ---- per-day log (day = int(minute // 1440)); does not influence the simulation ----
        self.daily_used = _day_table()         # plates actually taken from stock (includes batch_waste_factor)
        self.daily_expired = _day_table()      # plates that passed their expiry date unused
        self.daily_ordered = _day_table()      # plates ordered that day
        self.daily_delivered = _day_table()    # plates delivered that day
        self.daily_on_hand = _day_table()      # unexpired plates on hand at the daily review (start of day)

        for media, cfg in media_cfg.items():
            self.add_lot(media, cfg["initial"])

    def _day(self):
        return int(self.env.now // 1440)

    def add_lot(self, media, qty):
        shelf_life_mins = self.media_cfg[media]["shelf_life"] * 1440
        exp_minute = self.env.now + shelf_life_mins
        self.lots[media].append({"qty": qty, "exp_minute": exp_minute})

    def total_inventory(self, media):
        return sum(lot["qty"] for lot in self.lots[media] if lot["exp_minute"] > self.env.now)

    def purge_expired(self):
        for media in list(self.lots.keys()):
            valid_lots = []
            for lot in self.lots[media]:
                if lot["exp_minute"] <= self.env.now:
                    self.waste_log[media] += lot["qty"]
                    if lot["qty"]:
                        self.daily_expired[self._day()][media] += lot["qty"]
                else:
                    valid_lots.append(lot)
            self.lots[media] = valid_lots

    def try_consume_media(self, media, qty=1):
        self.purge_expired()
        available_lots = [l for l in self.lots[media] if l["qty"] > 0]

        if sum(l["qty"] for l in available_lots) < qty:
            return False

        available_lots.sort(key=lambda x: x["exp_minute"])

        # Realistic operational waste (e.g., QC plate per sleeve / drying out)
        waste_multiplier = 1.0 + self.media_cfg[media].get("batch_waste_factor", 0.0)
        actual_qty_needed = int(np.ceil(qty * waste_multiplier))

        remaining_to_consume = actual_qty_needed

        for lot in available_lots:
            take = min(lot["qty"], remaining_to_consume)
            lot["qty"] -= take
            remaining_to_consume -= take
            if remaining_to_consume == 0:
                break

        self.daily_used[self._day()][media] += actual_qty_needed - remaining_to_consume
        return True

    def place_order(self, media):
        qty = self.media_cfg[media]["order_qty"]
        self.pending_orders[media] += qty
        self.daily_ordered[self._day()][media] += qty
        self.env.process(self._delivery_process(media, qty, self.lead_time_mins))

    def _delivery_process(self, media, qty, delay_mins):
        yield self.env.timeout(delay_mins)
        self.add_lot(media, qty)
        self.pending_orders[media] -= qty
        self.daily_delivered[self._day()][media] += qty

    def snapshot(self):
        """Daily review: record unexpired plates on hand per media."""
        for media in self.media_cfg:
            self.daily_on_hand[self._day()][media] = self.total_inventory(media)

    def finalize(self, sim_minutes=None):
        """Build the long table (rep added by the runner): Day, Media, Used, Expired, Ordered, Delivered, On_Hand."""
        global LAST_DAILY
        n_days = int(np.ceil(sim_minutes / 1440.0)) if sim_minutes else 1 + max(
            [0] + [d for t in (self.daily_used, self.daily_expired, self.daily_ordered, self.daily_delivered, self.daily_on_hand) for d in t])
        rows = []
        for d in range(n_days):
            for m in self.media_cfg:
                rows.append((d, m, self.daily_used[d][m] if d in self.daily_used else 0.0,
                             self.daily_expired[d][m] if d in self.daily_expired else 0.0,
                             self.daily_ordered[d][m] if d in self.daily_ordered else 0.0,
                             self.daily_delivered[d][m] if d in self.daily_delivered else 0.0,
                             self.daily_on_hand[d][m] if d in self.daily_on_hand else np.nan))
        LAST_DAILY = pd.DataFrame(rows, columns=["Day", "Media", "Used", "Expired", "Ordered", "Delivered", "On_Hand"])
        return LAST_DAILY


def inventory_manager_process(env, inventory, media_cfg, review_interval_mins=1440):
    while True:
        inventory.purge_expired()
        inventory.snapshot()
        for media, cfg in media_cfg.items():
            on_hand = inventory.total_inventory(media)
            on_order = inventory.pending_orders[media]
            reorder_point = cfg["reorder_point"]

            if (on_hand + on_order) <= reorder_point:
                inventory.place_order(media)

        yield env.timeout(review_interval_mins)
