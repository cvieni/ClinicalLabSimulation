"""Scenario hooks for arrival volume and instrument capacity (applied for one run only).

params (JSON strings, set through --overrides by run_scenarios.py):
  scenario_volume_json      {"global": 1.5, "multipliers": {"BCx": 2.0}, "add_per_day": {"BCx": 2000}}
                            new daily volume = base * global * multipliers.get(type, 1) + add_per_day.get(type, 0)
  scenario_instrument_json  {"bc_instrument": 864, "incubator": 2000}   (replaces those capacities)
"""
import copy
import json


def _load(s):
    if not s:
        return {}
    return json.loads(s) if isinstance(s, str) else s


def apply_volume_scenario(spec_type, base_daily_volume, volume_json):
    cfg = _load(volume_json)
    if not cfg:
        return base_daily_volume
    v = base_daily_volume * float(cfg.get("global", 1.0)) * float(cfg.get("multipliers", {}).get(spec_type, 1.0))
    return max(0.0, v + float(cfg.get("add_per_day", {}).get(spec_type, 0.0)))


def apply_instrument_changes(instrument_resources, instrument_json):
    cfg = _load(instrument_json)
    if not cfg:
        return instrument_resources
    out = copy.deepcopy(instrument_resources)
    for k, v in cfg.items():
        if k not in out:
            raise ValueError(f"scenario instrument '{k}' not in Instrument_resources {list(out)}")
        out[k] = int(v)
    return out
