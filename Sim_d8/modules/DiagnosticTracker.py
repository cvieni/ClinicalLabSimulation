import pandas as pd
from pathlib import Path

class SimulationDiagnosticTracker:
    def __init__(self, env, resources, stores, check_interval=15.0):
        self.env = env
        self.resources = resources
        self.stores = stores
        self.check_interval = check_interval
        self.records = []  # Added for time-series storing
        self.action = env.process(self.run_diagnostics())

    def run_diagnostics(self):
        while True:
            yield self.env.timeout(self.check_interval)
            
            # Record numeric snapshot for plotting
            row = {"sim_time_min": self.env.now}
            
            print(f"\n============================================================")
            print(f"--- DETAILED BOTTLENECK DIAGNOSTIC [Sim Time: {self.env.now:.1f} min] ---")
            print(f"============================================================")
            
            # 1. Store/Buffer Queues
            print("--- STORES & HOLDING BUFFERS ---")
            for name, store in self.stores.items():
                pending_count = len(store.items)
                status = "🚨 BOTTLENECK" if pending_count > 100 else "OK"
                print(f"  Store: {name:<25} | Items Waiting: {pending_count:<6} [{status}]")
                row[f"store_{name}"] = pending_count
            
            # 2. Tech & Hardware Resources
            print("\n--- RESOURCE UTILIZATION & QUEUES ---")
            for name, res in self.resources.items():
                in_use = res.count
                cap = res.capacity
                in_queue = len(res.queue)
                
                over_allocated = "⚠️ OVER-CAPACITY" if in_use > cap else ""
                queue_alert = "🔥 QUEUE SURGE" if in_queue > 50 else ""
                alerts = f"{over_allocated} {queue_alert}".strip()
                
                utilization = (in_use / cap * 100) if cap > 0 else 0.0
                print(f"  Resource: {name:<22} | In Use: {in_use:>2}/{cap:<2} ({utilization:>5.1f}%) | Queue: {in_queue:<5} {alerts}")
                
                # Append numeric fields for plotting
                row[f"res_in_use_{name}"] = in_use
                row[f"res_capacity_{name}"] = cap
                row[f"res_util_pct_{name}"] = utilization
                row[f"res_queue_{name}"] = in_queue

            print(f"============================================================\n")
            self.records.append(row)

    def export_csv(self, output_path: str | Path):
        """Export collected data to CSV for plot_lab_diagnostics.py."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(self.records)
        df.to_csv(output_path, index=False)
        return df