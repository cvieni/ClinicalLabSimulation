# tracker.py
from collections import defaultdict

class SpecimenTracker:
    def __init__(self):
        self.logs = []
        self.state_logs = []
        self.media_usage = {"Blood_Agar": 0, "Chocolate_Agar": 0, "ChromeAgar": 0, "MacConkey": 0}
        self.stockout_delays = []

    def log_event(self, specimen_id, spec_type, stage, timestamp):
        self.logs.append({
            "Specimen_ID": specimen_id,
            "Type": spec_type,
            "Stage": stage,
            "Minute": timestamp,
            "Day": int(timestamp // 1440) + 1,
            "Hour": round((timestamp % 1440) / 60, 2)
        })

    def log_state(self, timestamp, active_specs, plating_q, tech_q):
        self.state_logs.append({
            "Minute": timestamp,
            "Hour": round(timestamp / 60, 1),
            "Day": round(timestamp / 1440, 2),
            "Active_Specimens_In_Lab": active_specs,
            "Plating_Queue_Length": plating_q,
            "Tech_Review_Queue_Length": tech_q
        })

    def log_stockout_delay(self, specimen_id, duration_mins):
        self.stockout_delays.append({
            "Specimen_ID": specimen_id,
            "Delay_Mins": duration_mins
        })

        # Add this inside SpecimenTracker in tracker.py

    def log_media_usage(self, media_type, qty=1):
        """Records consumption of agar plates for inventory tracking."""
        if media_type in self.media_usage:
            self.media_usage[media_type] += qty
        else:
            self.media_usage[media_type] = qty