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

    # def log_state(self, timestamp, active_specimens, plating_queue, tech_queue, busy_techs, active_techs):
    def log_state(self, timestamp, active_specimens, plating_queue, tech_queue, busy_techs, active_techs, **kwargs):
        """
        Logs simulation snapshots. Accepts explicit core metrics plus optional
        dynamic queues passed via **kwargs.
        """
        entry = {
            "Minute": timestamp,
            "Hour": round(timestamp / 60, 1),
            "Day": round(timestamp / 1440, 2),
            "Active_Specimens_In_Lab": active_specimens,
            "Plating_Queue_Length": plating_queue,
            "Total_Tech_Queue_Length": tech_queue, 
            "Busy_Techs": busy_techs,
            "Active_Techs": active_techs
        }

        # Dynamically append individual tech queues passed from state_monitor_process
        for key, val in kwargs.items():
            # Converts keys like 'tech_accession_queue' -> 'Tech_Accession_Queue_Length'
            clean_key = key.replace("tech_", "").replace("_queue_length", "").replace("_queue", "")
            formatted_key = f"Tech_{clean_key.capitalize()}_Queue_Length"
            entry[formatted_key] = val

        self.state_logs.append(entry)

    def log_stockout_delay(self, specimen_id, duration_mins):
        self.stockout_delays.append({
            "Specimen_ID": specimen_id,
            "Delay_Mins": duration_mins
        })

    def log_media_usage(self, media_type, qty=1):
        """Records consumption of agar plates for inventory tracking."""
        if media_type in self.media_usage:
            self.media_usage[media_type] += qty
        else:
            self.media_usage[media_type] = qty