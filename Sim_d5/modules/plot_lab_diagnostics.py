"""
Plot time-series store buffers, technician utilization, and queue lengths
from diagnostic monitor runs.
"""

from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
CSV_PATH = PROJECT_ROOT / "results_experiments" / "diagnostics_timeseries.csv"
OUTPUT_PNG = PROJECT_ROOT / "output_pngs" / "bottleneck_timeseries_summary.png"


def plot_diagnostics(csv_path: Path, output_path: Path):
    df = pd.read_csv(csv_path)
    time_hrs = df["sim_time_min"] / 60.0

    # Categorize columns
    store_cols = [c for c in df.columns if c.startswith("store_")]
    tech_util_cols = [c for c in df.columns if c.startswith("res_util_pct_tech_")]
    tech_queue_cols = [c for c in df.columns if c.startswith("res_queue_tech_")]
    equip_util_cols = [c for c in df.columns if c.startswith("res_util_pct_") and not c.startswith("res_util_pct_tech_")]

    fig, axes = plt.subplots(4, 1, figsize=(14, 14), sharex=True)

    # Panel 1: Stores & Holding Buffers
    for col in store_cols:
        label = col.replace("store_", "")
        axes[0].plot(time_hrs, df[col], label=label, linewidth=1.5)
    axes[0].set_ylabel("Items Waiting")
    axes[0].set_title("Stores & Holding Buffers Over Time (Backlog Detection)", fontweight="bold")
    axes[0].grid(True, linestyle=":", alpha=0.5)
    axes[0].legend(loc="upper left", frameon=False, fontsize=8)

    # Panel 2: Technician Utilization (%)
    for col in tech_util_cols:
        label = col.replace("res_util_pct_", "")
        axes[1].plot(time_hrs, df[col], label=label, linewidth=1.5)
    axes[1].set_ylabel("Utilization (%)")
    axes[1].set_ylim(-5, 105)
    axes[1].axhline(100, color="red", linestyle="--", alpha=0.5, label="100% Saturation")
    axes[1].set_title("Technician Resource Utilization (%)", fontweight="bold")
    axes[1].grid(True, linestyle=":", alpha=0.5)
    axes[1].legend(loc="lower left", frameon=False, fontsize=8, ncol=2)

    # Panel 3: Technician Queues
    for col in tech_queue_cols:
        label = col.replace("res_queue_", "")
        axes[2].plot(time_hrs, df[col], label=label, linewidth=1.5)
    axes[2].set_ylabel("Queued Requests")
    axes[2].set_title("Technician Queue Lengths Over Time", fontweight="bold")
    axes[2].grid(True, linestyle=":", alpha=0.5)
    axes[2].legend(loc="upper left", frameon=False, fontsize=8, ncol=2)

    # Panel 4: Equipment Utilization (%)
    for col in equip_util_cols:
        label = col.replace("res_util_pct_", "")
        axes[3].plot(time_hrs, df[col], label=label, linewidth=1.5)
    axes[3].set_ylabel("Utilization (%)")
    axes[3].set_ylim(-5, 105)
    axes[3].set_xlabel("Simulation Time (Hours)")
    axes[3].set_title("Equipment Resource Utilization (%)", fontweight="bold")
    axes[3].grid(True, linestyle=":", alpha=0.5)
    axes[3].legend(loc="upper left", frameon=False, fontsize=8, ncol=2)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=300)
    print(f"Saved diagnostic plots to: {output_path}")


if __name__ == "__main__":
    plot_diagnostics(CSV_PATH, OUTPUT_PNG)