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
            self.add_lot(media, cfg["initial"])

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
        qty = self.media_cfg[media]["order_qty"]
        self.pending_orders[media] += qty
        self.env.process(self._delivery_process(media, qty, self.lead_time_mins))

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
            reorder_point = cfg["reorder_point"]
            
            if (on_hand + on_order) <= reorder_point:
                inventory.place_order(media)
                
        yield env.timeout(review_interval_mins)