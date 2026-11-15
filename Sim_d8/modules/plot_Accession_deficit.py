import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pathlib import Path

def plot_accession_deficit(df_raw: pd.DataFrame, output_path: str = "output_pngs/accession_deficit.png"):
    """
    Plots Cumulative Arrived, Instantaneous Queue, and Cumulative Processed specimens
    over the course of the simulation to highlight the capacity deficit.
    """
    if df_raw.empty:
        print("Raw event log is empty. Cannot generate deficit plot.")
        return

    # Filter arrival and accession completion events
    df_events = df_raw.copy()
    
    # Standardize column names
    time_col = "Timestamp" if "Timestamp" in df_events.columns else "Time"
    event_col = "Event" if "Event" in df_events.columns else "stage"
    
    # Convert sim minutes to days
    df_events["Sim_Day"] = df_events[time_col] / (24 * 60)
    
    # Extract arrival and accession completed events
    arrivals = df_events[df_events[event_col].str.contains("Arrived", case=False, na=False)].copy()
    accessioned = df_events[df_events[event_col].str.contains("Accessioning Completed|Accession Completed", case=False, na=False)].copy()

    # Sort by timestamp
    arrivals = arrivals.sort_values("Sim_Day")
    accessioned = accessioned.sort_values("Sim_Day")

    # Build time-series dataframe
    timeline = pd.DataFrame({
        "Sim_Day": np.sort(df_events["Sim_Day"].unique())
    })

    # Count cumulative events at each timestamp
    timeline["Cumulative_Incoming"] = timeline["Sim_Day"].apply(lambda t: (arrivals["Sim_Day"] <= t).sum())
    timeline["Cumulative_Processed"] = timeline["Sim_Day"].apply(lambda t: (accessioned["Sim_Day"] <= t).sum())
    timeline["Current_Queue"] = timeline["Cumulative_Incoming"] - timeline["Cumulative_Processed"]

    # -------------------------------------------------------------------------
    # Plotting
    # -------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(12, 6), dpi=300)

    # 1. Cumulative Incoming (Dashed Blue Line)
    ax.plot(
        timeline["Sim_Day"], 
        timeline["Cumulative_Incoming"], 
        label="Cumulative Incoming (Arrived)", 
        color="#1f77b4", 
        linestyle="--", 
        linewidth=2
    )

    # 2. Cumulative Processed (Solid Black Line)
    ax.plot(
        timeline["Sim_Day"], 
        timeline["Cumulative_Processed"], 
        label="Cumulative Processed (Accessioned)", 
        color="black", 
        linestyle="-", 
        linewidth=2.5
    )

    # 3. Instantaneous Queue Backlog (Dashed Red Line)
    ax.plot(
        timeline["Sim_Day"], 
        timeline["Current_Queue"], 
        label="Active Queue (Store Backlog)", 
        color="#d62728", 
        linestyle="--", 
        linewidth=2
    )

    ax.set_xlabel("Simulation Time (Days)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Number of Specimens", fontsize=11, fontweight="bold")
    ax.set_title("Accessioning Stage: Arrival vs. Processing Deficit Over Time", fontsize=13, fontweight="bold")
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="upper left", frameon=True, facecolor="white", edgecolor="none")

    # Format y-axis numbers with commas
    ax.yaxis.set_major_formatter("{x:,.0f}")

    plt.tight_layout()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path)
    plt.close()
    print(f"Deficit visualization saved to: {output_path}")

# =============================================================================
# Usage Example:
# =============================================================================
# from modules.simulation_d4 import run_simulation
# df_pivot, df_state, media_usage, df_ai, stochastic_stats = run_simulation(sim_days=30, seed=42)
# plot_accession_deficit(df_raw=tracker.logs, output_path="output_pngs/accession_deficit.png")