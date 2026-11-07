"""Derive FINAL_READ_BY_TYPE starting values from the raw LIS file (observed_<year>_lis_clean.csv from make_observed_csv_d1.py).

    python calibrate_final_read.py --raw data/observed_2025_lis_clean.csv [--tail Respiratory=96,Resp_CystFibrosis=100] [--offset-h 8]

Per sim type: tail = TAT above that type's threshold -> extended_fraction, extended_hours = (P10, P90 of the tail);
the rest ("bulk") -> hold_hours = (bulk quantile lo-q, bulk quantile hi-q).
The sim adds roughly 7-10 h on top of a hold (scheduled read slots, positives' workup), so every hold/extended value is lowered by --offset-h
(default 8; use 0 to see the raw LIS quantiles).  Always check the result with a short run (table2_validation.csv) and adjust.

v2: * respiratory CF / non-CF handled (labels 'Respiratory (CF)' / 'Respiratory (Non-CF)'),
    * invasive and non-invasive urine are separate (their LIS TATs differ a lot: median ~74 h vs ~47 h),
    * stool is split by LIS test code when the file has an order_num column: 60134 Stool_Ecoli, 60135 Stool_Campy, 60136 Stool_Vibrio, 60137 Stool_Yersinia,
    * --tail sets the tail threshold per sim type (default 250 h; use ~100 h for respiratory and urine, whose tails start much earlier).
"""
import argparse
import re

import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--raw", required=True)
ap.add_argument("--tail-h", type=float, default=250.0, help="default tail threshold (h)")
ap.add_argument("--tail", default="Respiratory=100,Resp_CystFibrosis=120,Urine_Invasive=100,Urine_NonInvasive=72",
                help="per sim type tail threshold, e.g. Respiratory=96,Urine_NonInvasive=72")
ap.add_argument("--lo-q", type=float, default=0.05)
ap.add_argument("--hi-q", type=float, default=0.25)
ap.add_argument("--offset-h", type=float, default=8.0)
ap.add_argument("--tat-col", default="TAT_Hours")
a = ap.parse_args()
TAIL = {k: float(v) for k, v in (x.split("=") for x in a.tail.split(",") if x)}

norm = lambda s: re.sub(r"[^a-z]", "", str(s).lower())
MAP = {"invasiveurine": ["Urine_Invasive"], "noninvasiveurine": ["Urine_NonInvasive"], "urineinvasive": ["Urine_Invasive"],
       "urine": ["Urine_Invasive", "Urine_NonInvasive"],
       "wound": ["Wound"], "genitalwound": ["Wound_Genital"], "woundgenital": ["Wound_Genital"],
       "tissue": ["Tissue"], "fnatissue": ["Tissue_FNA"], "genitaltissue": ["Tissue_genital"],
       "bodyfluid": ["BodyFluid"], "bone": ["Bone_Cx"],
       "respiratorynoncf": ["Respiratory"], "respiratorycf": ["Resp_CystFibrosis"], "respiratory": ["Respiratory"]}
STOOL_CODE = {"60134": "Stool_Ecoli", "60135": "Stool_Campy", "60136": "Stool_Vibrio", "60137": "Stool_Yersinia"}

head = pd.read_csv(a.raw, nrows=0).columns
cols = ["specimen_type", a.tat_col] + (["order_num"] if "order_num" in head else [])
df = pd.read_csv(a.raw, usecols=cols, low_memory=False)
df[a.tat_col] = pd.to_numeric(df[a.tat_col], errors="coerce")
df = df.dropna(subset=[a.tat_col])

groups = []                                   # (sim type, TAT array)
for lab, g in df.groupby("specimen_type"):
    if norm(lab) == "stool":
        if "order_num" in g.columns:
            code = g["order_num"].map(lambda v: re.sub(r"\.0+$", "", str(v).strip()).lstrip("0"))
            for c, t in STOOL_CODE.items():
                groups.append((t, g.loc[code == c, a.tat_col].to_numpy()))
        else:
            print("# NOTE: no order_num column: stool cannot be split by test code; run make_observed_csv_d1.py again")
            groups.append(("Stool_Ecoli", g[a.tat_col].to_numpy()))
        continue
    for s in MAP.get(norm(lab), []):
        groups.append((s, g[a.tat_col].to_numpy()))
    if norm(lab) not in MAP:
        print(f"# skipped LIS label {lab!r} (not in MAP)")

print("FINAL_READ_BY_TYPE = {")
for s, x in groups:
    if len(x) < 50:
        print(f"    # {s}: only {len(x)} LIS rows, not calibrated")
        continue
    th = TAIL.get(s, a.tail_h)
    tail, bulk = x[x > th], x[x <= th]
    f = len(tail) / len(x)
    lo, hi = np.quantile(bulk, [a.lo_q, a.hi_q])
    e = (np.quantile(tail, 0.10), np.quantile(tail, 0.90)) if len(tail) >= 30 and f >= 0.01 else (0, 0)
    off = a.offset_h
    r = lambda v: int(round(max(v - off, 0))) if v else 0
    print(f'    "{s}": {{"hold_hours": ({r(lo)}, {r(hi)}), "extended_fraction": {round(f if f >= 0.01 else 0.0, 3)}, '
          f'"extended_hours": ({r(e[0])}, {r(e[1])})}},   # LIS n={len(x):,}, median {np.median(x):.0f} h, p95 {np.quantile(x, .95):.0f} h, tail > {th:.0f} h')
print("}")