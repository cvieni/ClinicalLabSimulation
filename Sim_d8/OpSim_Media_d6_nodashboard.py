import json
import os
import sys
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from project_config import (
    HEADLESS_OUTPUT_DIR, INITIAL_CONDITIONS_PATH, LOG_DIR, OUTPUT_PNG_DIR, PROJECT_ROOT,
    ensure_project_dirs, validate_runtime_paths,
)

# Import simulation engine and default configuration structures
from modules.simulation_d4 import run_simulation
from params_config.config_d2 import Instrument_resources
from params_config.staffing_config import SHIFT_STAFFING_PROFILE

from modules.export_final_conditions_json import export_initial_conditions_from_run

ENABLE_MONTE_CARLO = True  # Toggle Switch: Set to False to disable the Monte Carlo tab


def ensure_dir(path: Path) -> Path:
    """Creates directory if it does not exist."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_dashboard_visualizations(df_pivot: pd.DataFrame, df_state: pd.DataFrame, output_dir: Path | str = OUTPUT_PNG_DIR):
    """Export the dashboard visualizations to the shared output_pngs folder used by the app."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_path = out_dir / "1_tat_distribution.png"
    queue_path = out_dir / "2_queue_trajectories.png"

    if not df_pivot.empty and "Total_TAT_Hours" in df_pivot.columns:
        generate_kpi_summary_png(df_pivot, summary_path)
    else:
        generate_kpi_summary_png(pd.DataFrame(), summary_path)

    if not df_state.empty and "Minute" in df_state.columns:
        generate_utilization_png(df_state, queue_path)
    else:
        generate_utilization_png(pd.DataFrame(), queue_path)

    return {
        "tat_distribution": summary_path,
        "queue_trajectories": queue_path,
    }


def generate_kpi_summary_png(df_pivot: pd.DataFrame, output_path: Path):
    """Plots and exports Turnaround Time (TAT) distribution by Specimen Type."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(10, 6), dpi=300)

    if not df_pivot.empty and "Total_TAT_Hours" in df_pivot.columns:
        completed_df = df_pivot.dropna(subset=["Total_TAT_Hours"])

        if not completed_df.empty:
            types = completed_df["Type"].unique()
            tat_by_type = [
                completed_df[completed_df["Type"] == t][
                    "Total_TAT_Hours"
                ].values
                for t in types
            ]

            plt.boxplot(tat_by_type, tick_labels=types, patch_artist=True)
            plt.title(
                "Specimen Turnaround Time (TAT) Distribution",
                fontsize=14,
                fontweight="bold",
            )
            plt.ylabel("Total TAT (Hours)", fontsize=12)
            plt.xlabel("Specimen Type", fontsize=12)
            plt.grid(axis="y", linestyle="--", alpha=0.7)
        else:
            plt.text(
                0.5,
                0.5,
                "No completed specimens found in simulation output.",
                ha="center",
                va="center",
            )
    else:
        plt.text(
            0.5,
            0.5,
            "No TAT data available.",
            ha="center",
            va="center",
        )

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()


def generate_utilization_png(df_state: pd.DataFrame, output_path: Path):
    """Plots and exports active resource queues over simulation time."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(12, 6), dpi=300)

    if not df_state.empty and "Minute" in df_state.columns:
        time_hours = df_state["Minute"] / 60.0

        # Identify queue columns
        queue_cols = [
            c
            for c in df_state.columns
            if "queue" in c.lower() or "waiting" in c.lower()
        ]

        if queue_cols:
            for col in queue_cols[:5]:  # Plot top 5 tracked queues
                plt.plot(
                    time_hours,
                    df_state[col],
                    label=col.replace("_", " ").title(),
                    linewidth=1.5,
                )
            plt.title(
                "Workload Queue Trajectories Over Time",
                fontsize=14,
                fontweight="bold",
            )
            plt.xlabel("Simulation Time (Hours)", fontsize=12)
            plt.ylabel("Specimens Waiting", fontsize=12)
            plt.legend(loc="upper right")
            plt.grid(True, linestyle="--", alpha=0.5)
        else:
            plt.text(
                0.5,
                0.5,
                "No resource queue metrics recorded in df_state.",
                ha="center",
                va="center",
            )
    else:
        plt.text(
            0.5, 0.5, "No state log data available.", ha="center", va="center"
        )

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()

def run_headless_simulation(
    sim_days,
    seed,
    output_root: str | Path = HEADLESS_OUTPUT_DIR,
    custom_staffing: dict = None,
    custom_instruments: dict = None,
):
    """Executes simulation, saves outputs, parameters, and exports static PNG charts."""
    validate_runtime_paths()

    # 1. Setup timestamped directory structure
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = ensure_dir(Path(output_root) / f"run_{timestamp}")
    logs_dir = ensure_dir(run_dir / "logs")
    plots_dir = ensure_dir(run_dir / "plots")
    data_dir = ensure_dir(run_dir / "data")

    log_file = logs_dir / f"sim_execution_{timestamp}.log"

    # Use defaults if custom configs are omitted
    staffing = (
        custom_staffing if custom_staffing is not None else SHIFT_STAFFING_PROFILE
    )
    instruments = (
        custom_instruments
        if custom_instruments is not None
        else Instrument_resources
    )

    print(f"=== Starting Headless Simulation Run ===")
    print(f"Duration: {sim_days} days | Seed: {seed}")
    print(f"Output Directory: {run_dir.resolve()}")

    # 2. Save configuration parameters for experiment reproducibility
    config_snapshot = {
        "sim_days": sim_days,
        "seed": seed,
        "timestamp": timestamp,
        "instrument_resources": instruments,
        "shift_staffing_profile": staffing,
    }
    with open(run_dir / "config_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(config_snapshot, f, indent=4)

    # 3. Execute core simulation engine
    df_pivot, df_state, media_usage, df_ai_features, stochastic_stats = (
        run_simulation(
            sim_days=sim_days,
            seed=seed,
            instrument_resources=instruments,
            shift_staffing_profile=staffing,
            save_plots=False,
            log_filename=str(log_file),
        )
    )

    # 4. Save tabular outputs
    if not df_pivot.empty:
        df_pivot.to_csv(data_dir / "specimens_pivot.csv", index=False)
    if not df_state.empty:
        df_state.to_csv(data_dir / "system_state.csv", index=False)
    if not df_ai_features.empty:
        df_ai_features.to_csv(data_dir / "ai_features.csv", index=False)

    # Save summary metrics
    with open(data_dir / "stochastic_stats.json", "w", encoding="utf-8") as f:
        json.dump(stochastic_stats, f, indent=4)

    # =========================================================
    # EXPORT INITIAL CONDITIONS FOR FUTURE RUNS
    # =========================================================
    total_sim_minutes = sim_days * 24 * 60
    export_initial_conditions_from_run(
        df_pivot=df_pivot,
        total_sim_minutes=total_sim_minutes,
        output_path=data_dir / "initial_conditions.json",
    )

    # 5. Generate and export static PNG figures to both the run folder and the shared output_pngs folder
    print("Generating static PNG reports...")
    run_graph_paths = export_dashboard_visualizations(df_pivot, df_state, output_dir=plots_dir)
    shared_graph_paths = export_dashboard_visualizations(df_pivot, df_state, output_dir=OUTPUT_PNG_DIR)

    print(f"Run-specific charts: {run_graph_paths}")
    print(f"Shared charts: {shared_graph_paths}")

    print(f"=== Run Complete! All artifacts saved to: {run_dir.resolve()} ===")
    return run_dir


if __name__ == "__main__":
    # Example execution: Run a 30-day simulation headless
    ensure_project_dirs()
    validate_runtime_paths()
    run_headless_simulation(sim_days=30, seed=42, output_root=HEADLESS_OUTPUT_DIR)