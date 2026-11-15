"""Run a Monte Carlo study from the dashboard's Monte Carlo tab settings (no Dash imports: unit-testable)."""
import json
import re
from datetime import datetime
from pathlib import Path

import params_config.params_d3 as p
from params_config.config_d2 import Instrument_resources
from params_config.staffing_config import SHIFT_STAFFING_PROFILE
from components.scenario_overrides import assemble_profile, build_overrides, scenario_fields

MC_DAY_MAP = {"mc_wd": "Weekday", "mc_we": "Weekend"}
SHIFT_MAP = {"shift1": ("Shift_1_Day", (7, 15)), "shift2": ("Shift_2_Evening", (15, 23)), "shift3": ("Shift_3_Night", (23, 7))}
MC_FIELDS = scenario_fields("mcs")
MC_KEYS = [k for _, k in MC_FIELDS]
_BASE_PLATING = tuple(getattr(p, n, None) for n in ("min_plating_time", "avg_plating_time", "max_plating_time"))
_BASE_PLATING = _BASE_PLATING if all(v is not None for v in _BASE_PLATING) else None


def min_days_required():
    """sim_days must cover warm-up + cool-down + at least one measured day (params_d3.warmup_days / cooldown_days)."""
    return float(getattr(p, "warmup_days", 5)) + float(getattr(p, "cooldown_days", 7))


def timestamped_path(out_dir, label=""):
    lab = re.sub(r"[^A-Za-z0-9_-]+", "_", (label or "").strip()).strip("_")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(out_dir) / (f"sim_{stamp}_{lab}.csv" if lab else f"sim_{stamp}.csv")


def run_from_ui(iterations, sim_days, seed_base, workers, label, bc_cap, inc_cap, phx_cap, maldi_cap,
                staff_values, staff_ids, media_values, media_ids, sc_vals, out_dir, set_progress=None):
    """Returns dict(df, mc, csv_path, overrides, warnings, settings). Raises ValueError for settings that cannot work."""
    from modules.MonteCarlo.monte_carlo_d3 import run_monte_carlo_simulation
    iterations, sim_days = int(iterations or 10), float(sim_days or 60)
    need = min_days_required()
    if sim_days <= need:
        raise ValueError(f"Simulation days ({sim_days:g}) must exceed warm-up + cool-down ({need:g}); otherwise no day is measured. Use 60 for the validated setup.")
    instruments = {
        "incubator": inc_cap if inc_cap is not None else Instrument_resources.get("incubator"),
        "bc_instrument": bc_cap if bc_cap is not None else Instrument_resources.get("bc_instrument"),
        "phoenix_instrument": phx_cap if phx_cap is not None else Instrument_resources.get("phoenix_instrument"),
        "maldi_instrument": maldi_cap if maldi_cap is not None else Instrument_resources.get("maldi_instrument"),
    }
    profile = assemble_profile(SHIFT_STAFFING_PROFILE, staff_values, staff_ids, MC_DAY_MAP, SHIFT_MAP)
    overrides, warnings = build_overrides(**dict(zip(MC_KEYS, sc_vals)), base_plating=_BASE_PLATING)
    policy = {i["index"]: (v if v is not None else 0) for i, v in zip(media_ids or [], media_values or [])}
    csv_path = timestamped_path(out_dir, label)
    mc = run_monte_carlo_simulation(
        proposed_policy=policy, instrument_resources=instruments, shift_staffing_profile=profile, iterations=iterations,
        sim_days=sim_days, seed_base=int(seed_base if seed_base is not None else 42), set_progress=set_progress,
        max_workers=int(workers) if workers else None, csv_output_path=str(csv_path), initial_conditions_json=None,
        parameter_overrides=overrides or None)
    settings = {"timestamp": datetime.now().isoformat(timespec="seconds"), "label": label or "", "iterations": iterations, "sim_days": sim_days,
                "seed_base": int(seed_base if seed_base is not None else 42), "instrument_resources": instruments,
                "staffing_profile": profile, "parameter_overrides": overrides, "media_policy": policy, "warnings": warnings}
    csv_path.with_suffix(".json").write_text(json.dumps(settings, indent=1, default=str))
    return {"df": mc["export_dataframe"], "mc": mc, "csv_path": csv_path, "overrides": overrides, "warnings": warnings, "settings": settings}
