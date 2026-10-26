from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

OUTPUT_PNG_DIR = PROJECT_ROOT / "output_pngs"
CACHE_DIR = PROJECT_ROOT / "cache"
LOG_DIR = PROJECT_ROOT / "sim_output_logs"
RESULTS_DIR = PROJECT_ROOT / "results_montecarlo_output"
HEADLESS_OUTPUT_DIR = PROJECT_ROOT / "headless_outputs"
INITIAL_CONDITIONS_PATH = PROJECT_ROOT / "params_config" / "initial_conditions.json"


def ensure_project_dirs() -> dict[str, Path]:
    """Create all shared runtime directories used by the simulation pipeline."""
    directories = {
        "output_png": OUTPUT_PNG_DIR,
        "cache": CACHE_DIR,
        "logs": LOG_DIR,
        "results": RESULTS_DIR,
        "headless": HEADLESS_OUTPUT_DIR,
    }
    for path in directories.values():
        path.mkdir(parents=True, exist_ok=True)
    return directories


def validate_runtime_paths() -> None:
    """Raise a clear error if essential project inputs are missing."""
    ensure_project_dirs()

    required = [
        PROJECT_ROOT,
        OUTPUT_PNG_DIR,
        CACHE_DIR,
        LOG_DIR,
        RESULTS_DIR,
        HEADLESS_OUTPUT_DIR,
    ]

    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Required project paths do not exist: {missing}")

    if not INITIAL_CONDITIONS_PATH.exists():
        print(f"[Warning] Initial conditions file not found at {INITIAL_CONDITIONS_PATH}; the run will start from fresh defaults.")
