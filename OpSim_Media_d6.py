# app.py
import dash
import dash_bootstrap_components as dbc
import diskcache
from dash import DiskcacheManager
import os
from pathlib import Path
from datetime import datetime

from components.layouts_d2 import get_main_layout
from components.callbacks_d5 import register_callbacks

from OpSim_Media_d6_nodashboard import run_headless_simulation

# RUN_HEADLESS_WARMUP = True
RUN_HEADLESS_WARMUP = False

# Check version history
# python -c "import dash; print(dash.__version__)"

# Create cache directory (for progress bar)
cache = diskcache.Cache("./cache")
background_callback_manager = DiskcacheManager(cache)

# ------------------------------------------------------------------------------
# Define dynamic output path: Parent Directory / results_output
# ------------------------------------------------------------------------------
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parent  # App root folder
PARENT_DIR = PROJECT_ROOT.parent    # One directory above project root

OUTPUT_DIR = PROJECT_ROOT / "results_montecarlo_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)  # Create directory if missing

# 1. Define and create output directory
LOG_DIR = PROJECT_ROOT / "sim_output_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 2. Generate a formatted timestamp (e.g., 2026-09-04_08-57-21)
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# 3. Combine into a unique timestamped file path
OUTPUT_LOGS = LOG_DIR / f"sim_debug_{timestamp}.log"

# ------------------------------------------------------------------------------
# RUN HEADLESS WARM-UP / BURN-IN SIMULATION (TOGGLEABLE)
# ------------------------------------------------------------------------------
if RUN_HEADLESS_WARMUP:
    print("\n=== Executing Headless Burn-In Simulation for Initial Conditions ===")

    # Execute headless run (30 days warm-up)
    headless_run_dir = run_headless_simulation(
        sim_days=30,
        seed=42,
        output_root=str(PROJECT_ROOT / "headless_outputs"),
    )

    # Extract path to generated initial_conditions.json
    initial_conditions_path = headless_run_dir / "data" / "initial_conditions.json"

    if initial_conditions_path.exists():
        initial_conditions_json = str(initial_conditions_path)
        print(f" Successfully generated initial conditions JSON: {initial_conditions_json}\n")
    else:
        initial_conditions_json = None
        print("⚠️ Warning: Generated initial conditions file not found. Dash will start with a fresh state.\n")
else:
    print("\n=== Headless Burn-In Disabled: Loading params_config/initial_conditions.json ===")

    default_config_path = PROJECT_ROOT / "params_config" / "initial_conditions.json"

    if default_config_path.exists():
        initial_conditions_json = str(default_config_path)
        print(f" Loaded default initial conditions from: {initial_conditions_json}\n")
    else:
        initial_conditions_json = None
        print(f"⚠️ Warning: Default file not found at {default_config_path}. Starting with a fresh state.\n")

# ------------------------------------------------------------------------------
# Define dynamic output path: Parent Directory / results_output
# ------------------------------------------------------------------------------

# Initialize Dash application
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    background_callback_manager=background_callback_manager
    )

app.title = "Microbiology Lab Simulator"

# Set layout
app.layout = get_main_layout()

# Register callbacks
register_callbacks(app, output_directory = OUTPUT_DIR,
                   log_output = OUTPUT_LOGS, 
                   init_conditions_json = initial_conditions_json)

if __name__ == "__main__":
    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"OUTPUT_DIR:   {OUTPUT_DIR}")
    print(f"LOG DIR:   {OUTPUT_LOGS}")
    print(f"INIT JSON:    {initial_conditions_json}")
    app.run(debug=True, port=8050)

