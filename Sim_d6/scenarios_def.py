"""Edit this file to define scenarios. run_scenarios.py runs everything in SCENARIOS.

Building blocks (combine any of them with combine(...)):
  volume_x(type, f)            multiply one specimen type's daily volume       volume_x("BCx", 2)
  volume_add(type, n)          add n specimens/day of that type                volume_add("BCx", 2000)
  volume_all(f)                multiply EVERY type (e.g. 1.5x testing volume)  volume_all(1.5)
  staff_add(bench, n, shift=None, days=None)   add n techs (shift = substring of the shift key, e.g. "Evening")
  staff_set(bench, n, shift=None, days=None)   set staffing to n               staff_set("tech_float_accession", 0)
  media_x(f, media=None, lead_time_days=None)  scale media stock policy (all media, or a name/list); optional supplier lead time
  instrument(name, capacity)   incubator / bc_instrument / phoenix_instrument / maldi_instrument
  param(name=value, ...)       any scalar parameter in params_d3.py            param(stool_biochem_time_multiplier=2.0)
Sweeps:  sweep_volume("BCx", [1.25, 1.5, 2.0])  -> one scenario per factor
Type names: BCx, BodyFluid, Bone_Cx, Tissue, Tissue_FNA, Tissue_genital, Wound, Wound_Genital, Stool,
            Respiratory (non-CF), Resp_CystFibrosis, Urine_Invasive, Urine_NonInvasive
"""
import copy


def _blank():
    return {"overrides": {}, "staffing": [], "volume": {"global": 1.0, "multipliers": {}, "add_per_day": {}},
            "instruments": {}, "media": {"global": 1.0, "per_media": {}}}


def volume_x(t, f):
    c = _blank(); c["volume"]["multipliers"][t] = float(f); return c


def volume_add(t, n):
    c = _blank(); c["volume"]["add_per_day"][t] = float(n); return c


def volume_all(f):
    c = _blank(); c["volume"]["global"] = float(f); return c


def staff_add(bench, n, shift=None, days=None):
    c = _blank(); c["staffing"].append({"bench": bench, "add": int(n), **({"shift_contains": shift} if shift else {}),
                                        **({"day_types": days} if days else {})}); return c


def staff_set(bench, n, shift=None, days=None):
    c = _blank(); c["staffing"].append({"bench": bench, "set": int(n), **({"shift_contains": shift} if shift else {}),
                                        **({"day_types": days} if days else {})}); return c


def instrument(name, capacity):
    c = _blank(); c["instruments"][name] = int(capacity); return c


def media_x(f, media=None, lead_time_days=None):
    """Scale media stock policy (reorder point, order qty, initial stock). media=None -> all media, else one name or list."""
    c = _blank()
    if media is None:
        c["media"]["global"] = float(f)
    else:
        for m in ([media] if isinstance(media, str) else media):
            c["media"]["per_media"][m] = float(f)
    if lead_time_days is not None:
        c["media"]["lead_time_days"] = float(lead_time_days)
    return c


def param(**kw):
    c = _blank(); c["overrides"].update(kw); return c


def combine(*parts):
    out = _blank()
    for c in parts:
        out["overrides"].update(c["overrides"])
        out["staffing"] += copy.deepcopy(c["staffing"])
        out["volume"]["global"] *= c["volume"]["global"]
        for k, v in c["volume"]["multipliers"].items():
            out["volume"]["multipliers"][k] = out["volume"]["multipliers"].get(k, 1.0) * v
        for k, v in c["volume"]["add_per_day"].items():
            out["volume"]["add_per_day"][k] = out["volume"]["add_per_day"].get(k, 0.0) + v
        out["instruments"].update(c["instruments"])
        out["media"]["global"] *= c["media"]["global"]
        for k, v in c["media"]["per_media"].items():
            out["media"]["per_media"][k] = out["media"]["per_media"].get(k, 1.0) * v
        if "lead_time_days" in c["media"]:
            out["media"]["lead_time_days"] = c["media"]["lead_time_days"]
    return out


def sweep_volume(t, factors, media=False):
    """One scenario per factor, named <type>_x<factor>. media=True also scales the media stock policy by the same factor."""
    return {f"{t}_x{f:g}": combine(volume_x(t, f), media_x(f) if media else _blank()) for f in factors}


def sweep_volume_add(t, adds, media_per_unit=None):
    """One scenario per added specimens/day, named <type>_p<n>."""
    return {f"{t}_p{n:g}": volume_add(t, n) for n in adds}


def sweep_volume_all(factors, media=True):
    """Everything scaled (new client / 1.5x testing volume), named all_x<factor>. Media policy scaled too by default."""
    return {f"all_x{f:g}": combine(volume_all(f), media_x(f) if media else _blank()) for f in factors}


SCENARIOS = {
    "baseline": _blank(),
    "no_float": combine(staff_set("tech_float_accession", 0), staff_set("tech_float_newroutine", 0)),
    "evening_routine_plus1": staff_add("tech_routine", 1, shift="Evening"),
    "stool_biochem_x2": param(stool_biochem_time_multiplier=2.0),
    # ---- examples (uncomment / edit) ----
    # "new_client_bcx_plus2000": combine(volume_add("BCx", 2000), instrument("bc_instrument", 864)),
    # "volume_x1.5_all": combine(volume_all(1.5), media_x(1.5)),
    # **sweep_volume_all([1.25, 1.5, 2.0, 2.5]),        # -> all_x1.25 ... used by the breaking-point figure
    # **sweep_volume_add("BCx", [500, 1000, 2000]),
    # **sweep_volume("BCx", [1.25, 1.5, 2.0]),
}
