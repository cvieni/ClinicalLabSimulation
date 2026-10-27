# app.py
import dash
import dash_bootstrap_components as dbc
import diskcache
from dash import DiskcacheManager
from datetime import datetime
from pathlib import Path

from components.layouts_d2 import get_main_layout
from components.callbacks_d5 import register_callbacks
from OpSim_Media_d6_nodashboard import run_headless_simulation

RUN_HEADLESS_WARMUP = False

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "results_montecarlo_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = PROJECT_ROOT / "sim_output_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
OUTPUT_LOGS = LOG_DIR / f"sim_debug_{timestamp}.log"

cache = diskcache.Cache(str(PROJECT_ROOT / "cache"))
background_callback_manager = DiskcacheManager(cache)

if RUN_HEADLESS_WARMUP:
    print("\n=== Executing Headless Burn-In Simulation for Initial Conditions ===")
    headless_run_dir = run_headless_simulation(
        sim_days=30,
        seed=42,
        output_root=str(PROJECT_ROOT / "headless_outputs"),
    )
    initial_conditions_path = headless_run_dir / "data" / "initial_conditions.json"
    initial_conditions_json = str(initial_conditions_path) if initial_conditions_path.exists() else None
else:
    default_config_path = PROJECT_ROOT / "params_config" / "initial_conditions.json"
    initial_conditions_json = str(default_config_path) if default_config_path.exists() else None

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    background_callback_manager=background_callback_manager,
)

app.title = "Microbiology Lab Simulator"
app.layout = get_main_layout()
register_callbacks(
    app,
    output_directory=OUTPUT_DIR,
    log_output=OUTPUT_LOGS,
    init_conditions_json=initial_conditions_json,
)

if __name__ == "__main__":
    app.run(debug=True, port=8050)
