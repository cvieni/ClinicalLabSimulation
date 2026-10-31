# inventory.py
from collections import defaultdict
import numpy as np

class MediaInventory:
    def __init__(self, env, media_cfg, order_lead_time_days=3):
        self.env = env
        self.media_cfg = media_cfg
        self.lead_time_mins = order_lead_time_days * 1440
        self.lots = defaultdict(list)
        self.pending_orders = defaultdict(int)
        self.waste_log = defaultdict(int)

        for media, cfg in media_cfg.items():
            self.add_lot(media, cfg["initial"] * self.unit(media))
            # Standing order: a fixed quantity delivered on a fixed cycle, independent of stock level
            # ("standing order 75 delivered once a week").
            if self.standing_interval_days(media) and self.standing_qty(media):
                self.env.process(self._standing_order(media))

    def unit(self, media):
        """Plates (or tubes) per ordering unit. reorder_point / order_qty / initial / standing_order_qty in
        MEDIA_CONFIG are in these units; all stock inside the inventory is counted in single plates.
        Default 1, so an existing config in plates behaves exactly as before."""
        return int(self.media_cfg[media].get("plates_per_unit", 1))

    def standing_interval_days(self, media):
        c = self.media_cfg[media]
        return c.get("standing_order_interval_days") or c.get("order_frequency")

    def standing_qty(self, media):
        """Units per standing delivery: standing_order_qty if given, else order_qty when order_frequency is set."""
        c = self.media_cfg[media]
        if c.get("standing_order_qty"):
            return c["standing_order_qty"]
        return c["order_qty"] if c.get("order_frequency") else None

    def lead_minutes(self, media):
        d = self.media_cfg[media].get("lead_time_days")
        return self.lead_time_mins if d is None else float(d) * 1440

    def _standing_order(self, media):
        cfg = self.media_cfg[media]
        days = float(self.standing_interval_days(media))
        yield self.env.timeout(float(cfg.get("standing_order_first_day", days)) * 1440)
        while True:
            self.add_lot(media, self.standing_qty(media) * self.unit(media))
            yield self.env.timeout(days * 1440)

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
                
        return True

    def place_order(self, media):
        qty = self.media_cfg[media]["order_qty"] * self.unit(media)
        self.pending_orders[media] += qty
        self.env.process(self._delivery_process(media, qty, self.lead_minutes(media)))

    def _delivery_process(self, media, qty, delay_mins):
        yield self.env.timeout(delay_mins)
        self.add_lot(media, qty)
        self.pending_orders[media] -= qty


def inventory_manager_process(env, inventory, media_cfg, review_interval_mins=1440):
    while True:
        inventory.purge_expired()
        for media, cfg in media_cfg.items():
            on_hand = inventory.total_inventory(media)
            on_order = inventory.pending_orders[media]
            if cfg.get("reorder_point") is None:      # standing-order-only medium: no shortage trigger
                continue
            reorder_point = cfg["reorder_point"] * inventory.unit(media)
            
            if (on_hand + on_order) <= reorder_point:
                inventory.place_order(media)
                
        yield env.timeout(review_interval_mins)