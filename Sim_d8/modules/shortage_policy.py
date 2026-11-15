"""Supply-disruption injection and shortage-response levers for one simulation run.

Configured by params `scenario_shortage_json` (empty = nothing changes, results identical to before):

{
 "disruptions": [{"media": "Blood_Agar", "start_day": 20, "duration_days": 10, "severity": 0.8}],
 "response": {
    "expedite":  {"trigger_cover_days": 3, "lead_days": 1.0, "qty_days": 5, "cooldown_days": 3, "premium": 1.5},
    "reserve":   {"trigger_cover_days": 4, "reserve_days": 2, "types": ["BCx", "Urine_Invasive"]},
    "spare":     {"trigger_cover_days": 3, "drop": {"CNA_Agar": ["Wound", "Respiratory"]}}
 }
}

Disruption: any delivery (standing order or reorder) that would land inside [start, start+duration) has `severity`
of its quantity held back and released as a late lot when the window ends (back-order). Initial stock is untouched.
Expedite : when days of cover (on hand / smoothed daily use) falls below trigger, place an emergency order that
           arrives after lead_days and is NOT held by the disruption (costs `premium` x the unit cost; stat emergency_cost is the extra over the normal price).
Reserve  : while cover < trigger, specimens whose type is NOT listed can only draw stock above reserve_days of use.
Spare    : while cover < trigger, the listed specimen types skip the listed (optional) media.
Run statistics are left in LAST_STATS for the caller (same process as run_simulation).
"""
import json

LAST_STATS = {}
_STATE = {"inv": None, "cfg": None}


def _cover_days(inv, media):
    use = inv._use_ewma.get(media, 0.0)
    on_hand = inv.total_inventory(media)
    return float("inf") if use <= 1e-9 else on_hand / use


def install_shortage(env, inventory, media_cfg, cfg_json):
    """Called once after MediaInventory is built. No-op when cfg_json is empty."""
    global LAST_STATS
    LAST_STATS = {}
    _STATE["inv"], _STATE["cfg"] = None, None
    if not cfg_json:
        return
    cfg = json.loads(cfg_json) if isinstance(cfg_json, str) else cfg_json
    if not cfg:
        return
    inv = inventory
    resp = cfg.get("response") or {}
    inv._use_day = {}
    inv._use_ewma = {}
    inv._stats = {"n_spared": 0, "n_reserve_blocked": 0, "emergency_units": 0.0, "emergency_cost": 0.0, "n_emergency_orders": 0,
                  "held_units": 0.0, "min_cover_days": {}}
    inv._emergency_ids = 0
    LAST_STATS = inv._stats
    wins = [dict(media=d["media"], t0=float(d["start_day"]) * 1440, t1=(float(d["start_day"]) + float(d["duration_days"])) * 1440,
                 sev=float(d.get("severity", 1.0))) for d in (cfg.get("disruptions") or [])]
    for w in wins:
        if w["media"] not in media_cfg:
            raise ValueError(f"shortage disruption media {w['media']} not in MEDIA_CONFIG")

    _orig_add, _orig_consume = inv.add_lot, inv.try_consume_media

    def add_lot(media, qty):
        now = env.now
        if now > 0 and not getattr(inv, "_bypass", False):
            for w in wins:
                if w["media"] == media and w["t0"] <= now < w["t1"] and w["sev"] > 0:
                    held = qty * w["sev"]
                    inv._stats["held_units"] += held
                    env.process(_release(media, held, w["t1"] - now))
                    qty = qty - held
                    break
        _orig_add(media, qty)

    def _release(media, qty, delay):
        yield env.timeout(delay)
        _orig_add(media, qty)

    def try_consume(media, qty=1):
        ok = _orig_consume(media, qty)
        if ok:
            inv._use_day[media] = inv._use_day.get(media, 0.0) + qty
        return ok

    inv.add_lot, inv.try_consume_media = add_lot, try_consume
    # the standing-order and reorder processes call self.add_lot -> instance attribute wins (looked up at call time)

    ex = resp.get("expedite")

    def monitor():
        last_emerg = {}
        while True:
            yield env.timeout(1440)
            for m in media_cfg:
                u = inv._use_day.pop(m, 0.0)
                prev = inv._use_ewma.get(m)
                inv._use_ewma[m] = u if prev is None else 0.8 * prev + 0.2 * u
                c = _cover_days(inv, m)
                if c != float("inf"):
                    mc = inv._stats["min_cover_days"]
                    mc[m] = min(mc.get(m, 1e9), c)
                if ex and c < float(ex["trigger_cover_days"]) and env.now - last_emerg.get(m, -1e12) >= float(ex.get("cooldown_days", 3)) * 1440:
                    units = float(ex["qty_days"]) * max(inv._use_ewma.get(m, 0.0), 1.0)
                    last_emerg[m] = env.now
                    inv._stats["n_emergency_orders"] += 1
                    inv._stats["emergency_units"] += units
                    inv._stats["emergency_cost"] += units * float(media_cfg[m].get("cost", 1.0)) * (float(ex.get("premium", 1.5)) - 1.0)   # premium over normal price
                    env.process(_emergency(m, units, float(ex.get("lead_days", 1.0)) * 1440))

    def _emergency(media, units, delay):
        yield env.timeout(delay)
        inv._bypass = True
        try:
            _orig_add(media, units)
        finally:
            inv._bypass = False

    env.process(monitor())
    _STATE["inv"], _STATE["cfg"] = inv, resp


def usable(inventory, spec_type, media):
    """Stock this specimen may draw (reserve rule). Equals total_inventory when no reserve policy is active."""
    tot = inventory.total_inventory(media)
    resp = _STATE["cfg"]
    if not resp or _STATE["inv"] is not inventory or not resp.get("reserve"):
        return tot
    r = resp["reserve"]
    if spec_type in r.get("types", []):
        return tot
    if _cover_days(inventory, media) >= float(r["trigger_cover_days"]):
        return tot
    held = float(r["reserve_days"]) * inventory._use_ewma.get(media, 0.0)
    left = max(0.0, tot - held)
    if left < tot:
        inventory._stats["n_reserve_blocked"] += 1 if left <= 0 else 0
    return left


def adjust_request(inventory, spec_type, media_req):
    """Drop optional media for sparing. Returns the (possibly smaller) request dict."""
    resp = _STATE["cfg"]
    if not resp or _STATE["inv"] is not inventory or not resp.get("spare"):
        return media_req
    s = resp["spare"]
    out = dict(media_req)
    for media, types in (s.get("drop") or {}).items():
        if media in out and spec_type in types and _cover_days(inventory, media) < float(s["trigger_cover_days"]) and len(out) > 1:
            del out[media]
            inventory._stats["n_spared"] += 1
    return out
