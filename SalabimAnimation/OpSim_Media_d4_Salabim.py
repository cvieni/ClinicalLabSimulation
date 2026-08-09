import random
import numpy as np
import pandas as pd
import salabim as sim
from collections import defaultdict

# Tell Salabim to use traditional generator 'yield' syntax
sim.yieldless(False)

# =====================================================
# CONFIGURATION & DATA DICTIONARIES
# =====================================================
RANDOM_SEED = 42
MINUTES_PER_DAY = 1440
SIM_DAYS = 3
SIM_TIME = SIM_DAYS * MINUTES_PER_DAY
ORDER_LEAD_TIME = 3  # days

MEDIA_TYPES = {
    "Blood_Agar": {"shelf_life": 14, "order_qty": 100, "reorder_point": 50},
    "MacConkey": {"shelf_life": 21, "order_qty": 100, "reorder_point": 40},
    "Chocolate_Agar": {"shelf_life": 10, "order_qty": 80, "reorder_point": 30},
}

SPECIMEN_TYPES = {
    "Urine": {"media_req": {"MacConkey": 1, "Blood_Agar": 1}, "subculture_prob": 0.15},
    "Wound": {"media_req": {"Blood_Agar": 1, "Chocolate_Agar": 1}, "subculture_prob": 0.25},
    "BCx": {"media_req": {"Blood_Agar": 2, "Chocolate_Agar": 1}, "positivity_rate": 0.10},
}

# =====================================================
# INVENTORY MODEL
# =====================================================
class MediaInventory:
    def __init__(self):
        self.inventory = defaultdict(list)
        self.pending_orders = defaultdict(int)
        self.used = defaultdict(int)
        self.expired = defaultdict(int)
        self.stockouts = defaultdict(int)
        self.order_queue = []

    def add_lot(self, media, qty, current_day):
        shelf_life = MEDIA_TYPES[media]["shelf_life"]
        self.inventory[media].append({
            "quantity": qty,
            "expiration_day": current_day + shelf_life
        })

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

    def use_media(self, media, current_day, qty=1):
        for _ in range(qty):
            available_lots = [l for l in self.inventory[media] if l["quantity"] > 0]
            if not available_lots:
                self.stockouts[media] += 1
                continue
            available_lots.sort(key=lambda x: x["expiration_day"])
            lot = available_lots[0] if random.random() < 0.90 else available_lots[-1]
            lot["quantity"] -= 1
            self.used[media] += 1

    def place_order(self, media, current_day):
        qty = MEDIA_TYPES[media]["order_qty"]
        self.pending_orders[media] += qty
        arrival_day = current_day + ORDER_LEAD_TIME
        self.order_queue.append({"media": media, "qty": qty, "arrival_day": arrival_day})

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
# SALABIM COMPONENT: SPECIMEN ENTITY WITH ANIMATION
# =====================================================
class Specimen(sim.Component):
    def setup(self, spec_code, lab_resources, inventory):
        self.spec_code = spec_code
        self.lab_resources = lab_resources
        self.inventory = inventory
        
        # Start specimen at arrival coordinates (Far Left)
        self.pos_x = 50
        self.pos_y = 300
        
        colors = {"Urine": "skyblue", "Wound": "orange", "BCx": "crimson"}
        self.color = colors.get(spec_code, "green")
        
        # Attach circle graphic to this component
        sim.AnimateCircle(
            radius=12,
            fillcolor=self.color,
            text=self.spec_code[:2],
            textcolor="white",
            parent=self
        )

    # Dynamic coordinate methods that Salabim queries every frame
    def x(self):
        return self.pos_x

    def y(self):
        return self.pos_y

    def process(self):
        current_day = int(self.env.now() // MINUTES_PER_DAY)
        spec_cfg = SPECIMEN_TYPES.get(self.spec_code, {})

        # --- STAGE 1: Plating Station Queue & Workstation ---
        yield self.request(self.lab_resources["plating_bench"])
        
        # Move visual dot to Plating Bench
        self.pos_x = 250
        self.pos_y = 300
        
        for media, qty in spec_cfg.get("media_req", {}).items():
            self.inventory.use_media(media, current_day, qty)
            
        yield self.hold(random.uniform(10, 20))
        yield self.release(self.lab_resources["plating_bench"])

        # --- STAGE 2: Incubator Queue & Station ---
        yield self.request(self.lab_resources["incubator"])
        
        # Move visual dot to Incubator Bench
        self.pos_x = 650
        self.pos_y = 300
        
        yield self.hold(random.uniform(60, 120))
        yield self.release(self.lab_resources["incubator"])

        # Completion: move off screen before termination
        self.pos_x = 950

# =====================================================
# WORKLOAD GENERATOR
# =====================================================
class LabGenerator(sim.Component):
    def setup(self, lab_resources, inventory):
        self.lab_resources = lab_resources
        self.inventory = inventory

    def process(self):
        while True:
            current_day = int(self.env.now() // MINUTES_PER_DAY)
            
            self.inventory.receive_orders(current_day)
            self.inventory.remove_expired(current_day)

            # Generate specimens with reasonable arrival spacing
            for _ in range(random.randint(15, 30)):
                spec_code = random.choice(list(SPECIMEN_TYPES.keys()))
                Specimen(
                    spec_code=spec_code,
                    lab_resources=self.lab_resources,
                    inventory=self.inventory
                )
                yield self.hold(random.uniform(10, 30))

            # Wait until next shift / next day
            next_day_time = (current_day + 1) * MINUTES_PER_DAY
            yield self.hold(next_day_time - self.env.now())

# =====================================================
# MAIN RUNNER WITH CANVAS & LAYOUT SETUP
# =====================================================
def run_salabim_simulation():
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    env = sim.Environment(trace=False)
    env.animate(True)
    
    env.modelname("Microbiology Lab Discrete Event Simulation")
    env.speed(10)  # Lower speed multiplier so movement is easy to observe
    env.width(1024)
    env.height(600)

    lab_resources = {
        "plating_bench": sim.Resource("Plating Bench", capacity=2),
        "incubator": sim.Resource("Incubator", capacity=8),
    }

    inventory = MediaInventory()
    for media, cfg in MEDIA_TYPES.items():
        inventory.add_lot(media, cfg["order_qty"], 0)

    # Visual Station Boxes
    sim.AnimateRectangle(
        spec=(-60, -40, 60, 40),
        x=250, y=300,
        fillcolor="lightgrey",
        linecolor="black",
        text="Plating Bench\n(Cap: 2)",
    )
    sim.AnimateQueue(
        queue=lab_resources["plating_bench"].requesters(),
        x=150, y=300,
        direction="W",
        title="Plating Queue"
    )

    sim.AnimateRectangle(
        spec=(-70, -50, 70, 50),
        x=650, y=300,
        fillcolor="whitesmoke",
        linecolor="darkblue",
        text="Incubator\n(Cap: 8)",
    )
    sim.AnimateQueue(
        queue=lab_resources["incubator"].requesters(),
        x=530, y=300,
        direction="W",
        title="Incubator Queue"
    )

    # FIX: Single dynamic AnimateText using a lambda (avoids memory/rendering leak)
    sim.AnimateText(
        text=lambda: "LIVE MEDIA INVENTORY:\n" + "\n".join(
            [f"• {m}: {inventory.total_inventory(m)} plates" for m in MEDIA_TYPES]
        ),
        x=50, y=520, font="Calibri", fontsize=14
    )

    # Start workload generator
    LabGenerator(lab_resources=lab_resources, inventory=inventory)

    env.run(till=SIM_TIME)

if __name__ == "__main__":
    run_salabim_simulation()