"""Scenario staffing changes, applied to a COPY of SHIFT_STAFFING_PROFILE for one run.

The change list arrives as a JSON string in params `scenario_staffing_json` (so it travels through
--overrides like any scalar parameter). Each op is a dict:

    {"bench": "tech_routine", "add": 1, "shift_contains": "Evening", "day_types": ["Weekday", "Weekend"]}
    {"bench": "tech_float_accession", "set": 0}

  bench           key inside a shift dict of the profile (tech_routine, tech_float_newroutine, ...)
  add / set       add n to the current staffing, or set it to n (floored at 0)
  shift_contains  optional, case-insensitive substring of the shift key (e.g. "Evening"); default = all shifts
  day_types       optional list, default = every day type in the profile
"""
import copy
import json


def apply_staffing_changes(profile, changes_json):
    if not changes_json:
        return profile
    ops = json.loads(changes_json) if isinstance(changes_json, str) else changes_json
    if not ops:
        return profile
    prof = copy.deepcopy(profile)
    for op in ops:
        bench = op["bench"]
        touched = 0
        for day_type, shifts in prof.items():
            if op.get("day_types") and day_type not in op["day_types"]:
                continue
            for shift_key, cfg in shifts.items():
                if op.get("shift_contains") and op["shift_contains"].lower() not in shift_key.lower():
                    continue
                if bench not in cfg:
                    continue
                cur = int(cfg[bench])
                cfg[bench] = max(0, int(op["set"]) if "set" in op else cur + int(op["add"]))
                touched += 1
        if touched == 0:
            raise ValueError(f"scenario staffing op matched nothing (bench key or shift name wrong?): {op}")
    return prof
