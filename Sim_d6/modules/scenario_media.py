"""Scenario hook for media stock policy (applied for one run only; MEDIA_CONFIG itself is never modified).

param scenario_media_json:
  {"global": 1.5,                         # multiply every media's fields below
   "per_media": {"Blood_Agar": 2.0},      # extra multiplier for named media (on top of global)
   "fields": ["reorder_point", "order_qty", "initial"],   # default; shelf_life and cost are never scaled
   "lead_time_days": 3}                   # optional supplier lead time (your baseline is 3)
"""
import copy
import json
import math

DEFAULT_FIELDS = ["reorder_point", "order_qty", "initial"]


def _cfg(s):
    if not s:
        return {}
    return json.loads(s) if isinstance(s, str) else s


def apply_media_scenario(media_cfg, media_json):
    c = _cfg(media_json)
    if not c:
        return media_cfg
    out = copy.deepcopy(media_cfg)
    per = c.get("per_media", {})
    unknown = [m for m in per if m not in out]
    if unknown:
        raise ValueError(f"scenario media {unknown} not in MEDIA_CONFIG {list(out)}")
    g = float(c.get("global", 1.0))
    for media, cfg in out.items():
        f = g * float(per.get(media, 1.0))
        for fld in c.get("fields", DEFAULT_FIELDS):
            if fld in cfg:
                cfg[fld] = int(math.ceil(cfg[fld] * f))
    return out


def media_lead_time_days(media_json, default=3):
    return float(_cfg(media_json).get("lead_time_days", default))
