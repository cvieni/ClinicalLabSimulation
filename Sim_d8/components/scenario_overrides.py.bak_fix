"""Pure helpers (no Dash): turn the dashboard's scenario controls into run_simulation(parameter_overrides=...) and
build the staffing profile from the grid. Unit-testable without a browser."""
import copy
import json

from modules.ml_pipeline import NO_RESPONSE, to_overrides

# order of the scenario controls as passed to the callbacks (id suffix, build_overrides keyword)
_SUFFIX_KEYS = [
    ("volume_x", "volume_x"), ("media_x", "media_x"), ("lead_days", "lead_days"),
    ("biochem", "biochem"), ("lit_gram", "lit_gram"), ("plating_x", "plating_x"),
    ("shortage_on", "shortage_on"), ("sh_media", "sh_media"), ("sh_start", "sh_start"),
    ("sh_duration", "sh_duration"), ("sh_severity", "sh_severity"),
    ("exp_on", "exp_on"), ("exp_lead", "exp_lead"), ("exp_trigger", "exp_trigger"), ("exp_qty", "exp_qty"),
    ("res_days", "res_days"), ("res_trigger", "res_trigger"),
    ("spare_on", "spare_on"), ("spare_trigger", "spare_trigger"),
    ("advanced", "advanced"),
]


def scenario_fields(prefix="sc"):
    return [(f"{prefix}_{suf}", key) for suf, key in _SUFFIX_KEYS]


SCENARIO_FIELDS = scenario_fields("sc")
SCENARIO_KEYS = [k for _, k in SCENARIO_FIELDS]


def _num(v, default):
    try:
        return default if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return default


def build_overrides(volume_x=1.0, media_x=1.0, lead_days=None, biochem=True, lit_gram=False, plating_x=1.0,
                    shortage_on=False, sh_media=None, sh_start=20, sh_duration=10, sh_severity=0.8,
                    exp_on=False, exp_lead=1.0, exp_trigger=3.0, exp_qty=5.0, res_days=0.0, res_trigger=4.0,
                    spare_on=False, spare_trigger=3.0, advanced="", base_plating=None):
    """Returns (overrides dict, list of warning strings). Only non-default settings are included, so an untouched
    dashboard runs exactly the baseline model. base_plating = (min, avg, max) minutes from params."""
    ov, warn = {}, []
    vx = _num(volume_x, 1.0)
    if abs(vx - 1.0) > 1e-9:
        ov["scenario_volume_json"] = json.dumps({"global": vx})
    mx, ld = _num(media_x, 1.0), (None if lead_days in (None, "") else _num(lead_days, None))
    if abs(mx - 1.0) > 1e-9 or ld is not None:
        m = {"global": mx}
        if ld is not None:
            m["lead_time_days"] = ld
        ov["scenario_media_json"] = json.dumps(m)
    if biochem is not None and not bool(biochem):
        ov["biochem_tests_enabled"] = 0
    if lit_gram:
        ov["use_literature_task_times"] = 1
    px = _num(plating_x, 1.0)
    if abs(px - 1.0) > 1e-9 and base_plating:
        mn, av, mxx = base_plating
        ov.update(min_plating_time=mn * px, avg_plating_time=av * px, max_plating_time=mxx * px)
    if shortage_on:
        if not sh_media:
            warn.append("Supply disruption is on but no medium is selected: ignored.")
        else:
            pt = {"media": sh_media, "start_day": _num(sh_start, 20), "duration_days": _num(sh_duration, 10),
                  "severity": _num(sh_severity, 0.8), "volume": 1.0, **NO_RESPONSE,
                  "exp_on": 1 if exp_on else 0, "exp_lead_days": _num(exp_lead, 1.0), "exp_trigger_days": _num(exp_trigger, 3.0),
                  "exp_qty_days": _num(exp_qty, 5.0), "res_days": _num(res_days, 0.0), "res_trigger_days": _num(res_trigger, 4.0),
                  "spare_on": 1 if spare_on else 0, "spare_trigger_days": _num(spare_trigger, 3.0)}
            ov.update(to_overrides(pt))
    elif exp_on or res_days or spare_on:
        warn.append("Response levers (expedite / reserve / spare) only act during a supply disruption: switch the disruption on.")
    if advanced and str(advanced).strip():
        try:
            extra = json.loads(advanced)
            if not isinstance(extra, dict):
                raise ValueError("must be a JSON object, e.g. {\"batch_size\": 8}")
            ov.update(extra)
        except Exception as e:
            warn.append(f"Advanced overrides ignored ({e}).")
    return ov, warn


def assemble_profile(default_profile, staff_values, staff_ids, day_map, shift_map):
    """Copy of the configured SHIFT_STAFFING_PROFILE with the dashboard grid values laid over it, so keys that are not on
    the grid (and 'hours') keep their configured values instead of being dropped."""
    prof = copy.deepcopy(default_profile)
    for val, meta in zip(staff_values, staff_ids):
        day_type, shift_raw, field = meta.get("day_type"), meta.get("shift"), meta.get("field")
        if day_type not in day_map or shift_raw not in shift_map:
            continue
        shift_key = shift_map[shift_raw][0]
        try:
            clean = int(val) if val is not None else 0
        except (TypeError, ValueError):
            clean = 0
        prof.setdefault(day_map[day_type], {}).setdefault(shift_key, {"hours": list(shift_map[shift_raw][1])})[field] = clean
    return prof
