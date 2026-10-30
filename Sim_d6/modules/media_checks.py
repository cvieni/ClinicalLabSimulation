"""Media (plates/broths) sanity checks, config only, no simulation needed.

Two problems found in the 10-day funnel (5,624 stockout delays, 3,243 specimens dropped for media):

1. UNKNOWN MEDIA NAMES. `media_req` in specimen_config_d2 names media that do not exist in MEDIA_CONFIG
   ('Chocolate', 'GramStain', 'BCSA_Agar', 'HE_Agar', 'Campy_CVA', 'CT-SMAC', 'GN_Broth').
   MediaInventory.lots is a defaultdict, so an unknown name silently has 0 stock forever. consume_media_inventory
   then polls 5 times (p.inventory_stockout_recheck, 480 min) and aborts the specimen: those specimen types can
   NEVER be plated. validate_media_requirements() fails fast at start-up instead.

2. REPLENISHMENT CAN NOT KEEP UP. inventory_manager_process orders `order_qty` when (on_hand + on_order) <= reorder_point,
   and a delivery takes 3 days. If reorder_point < demand x lead time, stock hits zero while the order is in transit, and
   because consumption stops at zero, the position stays above the reorder point until delivery. The cycle is then
   lead + order_qty/demand days, so the supply rate is order_qty / (lead + order_qty/demand), far below demand.
   media_supply_report() computes that per medium and prints a demand-based suggestion.
"""
from __future__ import annotations

import math
import os

import pandas as pd


def media_demand_per_day(spec_types: dict, media_cfg: dict | None = None, rejection_frac: float = 0.0,
                         workup_factor: float = 1.0) -> dict:
    """Plates/day per medium = sum over types of daily_volume_mean x qty x (1-rejection) x workup_factor x (1+waste).
    workup_factor > 1 approximates the extra plates used by repeat workups (not modelled here)."""
    dem: dict = {}
    for t, cfg in spec_types.items():
        vol = float(cfg.get("daily_volume_mean") or 0.0)
        for m, q in (cfg.get("media_req") or {}).items():
            waste = float((media_cfg or {}).get(m, {}).get("batch_waste_factor", 0.0))
            dem[m] = dem.get(m, 0.0) + vol * float(q) * (1.0 - rejection_frac) * workup_factor * (1.0 + waste)
    return dem


def find_unknown_media(spec_types: dict, media_cfg: dict) -> dict:
    """{media_name: [(spec_type, daily_volume), ...]} for every media_req key missing from media_cfg."""
    out: dict = {}
    for t, cfg in spec_types.items():
        for m in (cfg.get("media_req") or {}):
            if m not in media_cfg:
                out.setdefault(m, []).append((t, float(cfg.get("daily_volume_mean") or 0.0)))
    return out


def validate_media_requirements(spec_types: dict, media_cfg: dict, strict: bool = True) -> dict:
    """Raise (or warn when LABSIM_ALLOW_UNKNOWN_MEDIA=1 / strict=False) if any media_req name is not in media_cfg."""
    unknown = find_unknown_media(spec_types, media_cfg)
    if not unknown:
        return unknown
    lost = {}
    for m, lst in unknown.items():
        for t, v in lst:
            lost[t] = v
    lines = [f"  {m!r:20} used by " + ", ".join(f"{t} ({v:.0f}/day)" for t, v in lst) for m, lst in unknown.items()]
    msg = ("media_req names that are not in MEDIA_CONFIG (those specimens can never get media and will be aborted "
           f"after p.inventory_stockout_recheck x 5 minutes; {sum(lost.values()):.0f} specimens/day affected):\n"
           + "\n".join(lines) + "\nFix the spelling in specimen_config_d2.py or add the medium to media_config.py "
           "(set LABSIM_ALLOW_UNKNOWN_MEDIA=1 to run anyway).")
    if strict and os.environ.get("LABSIM_ALLOW_UNKNOWN_MEDIA") != "1":
        raise ValueError(msg)
    import warnings
    warnings.warn(msg)
    return unknown


def media_supply_report(spec_types: dict, media_cfg: dict, lead_time_days: float = 3.0, review_days: float = 1.0,
                        recheck_minutes: float = 480.0, max_attempts: int = 5, rejection_frac: float = 0.0,
                        workup_factor: float = 1.15, safety: float = 1.25, order_days: float = 7.0) -> pd.DataFrame:
    """Per-medium demand vs the (initial, reorder_point, order_qty, lead time) policy."""
    dem = media_demand_per_day(spec_types, media_cfg, rejection_frac, workup_factor)
    rows = []
    for m, d in sorted(dem.items(), key=lambda kv: -kv[1]):
        c = media_cfg.get(m)
        if c is None:
            rows.append(dict(medium=m, demand_per_day=round(d), status="NOT IN MEDIA_CONFIG"))
            continue
        rop, q, init = float(c["reorder_point"]), float(c["order_qty"]), float(c["initial"])
        need_rop = d * (lead_time_days + review_days)
        if rop >= need_rop:
            sup_pct = 100.0
        else:
            cycle = lead_time_days + review_days / 2.0 + q / d       # days per replenishment cycle
            sup_pct = min(100.0, 100.0 * (q / cycle) / d)
        rows.append(dict(medium=m, demand_per_day=round(d), initial_days_cover=round(init / d, 2),
                         reorder_point=rop, rop_needed=math.ceil(need_rop), order_qty_days=round(q / d, 1),
                         supply_pct_of_demand=round(sup_pct), status="OK" if sup_pct >= 99 else "STARVED"))
    df = pd.DataFrame(rows)
    print(f"\n=== Media: demand vs replenishment policy (lead {lead_time_days:g} d, review every {review_days:g} d) ===")
    print(df.to_string(index=False))
    print(f"\nA specimen waits at most {max_attempts} x {recheck_minutes:g} min = {max_attempts * recheck_minutes / 60:g} h for "
          f"media, then is aborted. A lead time of {lead_time_days * 24:g} h is longer than that.")
    unk = find_unknown_media(spec_types, media_cfg)
    if unk:
        print("\nUNKNOWN MEDIA (never obtainable):")
        for m, lst in unk.items():
            print(f"  {m!r}: " + ", ".join(f"{t} ({v:.0f}/day)" for t, v in lst))
    print(f"\nSuggested starting point (demand x {safety:g} safety, {order_days:g}-day orders; REPLACE with your real par levels):")
    for m, d in sorted(dem.items(), key=lambda kv: -kv[1]):
        rop = math.ceil(d * (lead_time_days + review_days) * safety / 10) * 10
        q = math.ceil(d * order_days / 10) * 10
        print(f'    "{m}": reorder_point={rop}, order_qty={q}, initial={rop + q // 2}')
    return df
