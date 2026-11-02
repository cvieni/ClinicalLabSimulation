"""What is in initial_conditions.json, and do the sim's daily volumes match the LIS?   (run from the project folder)

    python inspect_initial_conditions.py [--json params_config/initial_conditions.json] [--raw data/observed_2025_lis_clean.csv]
"""
import argparse, json, re
from collections import Counter, defaultdict
ap = argparse.ArgumentParser()
ap.add_argument("--json", default="params_config/initial_conditions.json")
ap.add_argument("--raw", default=None, help="raw LIS file (specimen_type, arrival_datetime) to compare daily volumes")
a = ap.parse_args()

cfg = json.load(open(a.json, encoding="utf-8"))
print(f"{a.json}: top-level keys {list(cfg)[:12]}")
for grp, items in cfg.items():
    if not isinstance(items, list):
        continue
    by = defaultdict(list)
    for it in items:
        t = it.get("spec_type") or it.get("type") or "?"
        off = it.get("arrival_time", it.get("remaining_incubation_time", it.get("remaining_time", 0))) or 0
        by[t].append(float(off))
    print(f"\n{grp}: {len(items):,} items   (offset = arrival_time / remaining time, MINUTES -> days)")
    for t, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print(f"   {t:20s} n={len(v):6,}   offset days: min {min(v)/1440:6.2f}  median {sorted(v)[len(v)//2]/1440:6.2f}  max {max(v)/1440:6.2f}")

try:
    from params_config.specimen_config_d2 import SPECIMEN_TYPES
    print("\nSim daily_volume_mean per type (what the generator uses):")
    lis = {}
    if a.raw:
        import pandas as pd
        d = pd.read_csv(a.raw, usecols=["specimen_type", "arrival_datetime"], low_memory=False)
        d["arrival_datetime"] = pd.to_datetime(d["arrival_datetime"], errors="coerce")
        ndays = d["arrival_datetime"].dt.date.nunique()
        lis = (d.groupby("specimen_type").size() / ndays).round(1).to_dict()
        print(f"LIS per-day (raw file, {ndays} distinct days): {lis}")
    for t, c in SPECIMEN_TYPES.items():
        print(f"   {t:20s} daily_volume_mean = {c.get('daily_volume_mean')}")
except Exception as e:
    print("\n(could not import SPECIMEN_TYPES:", e, ")")
