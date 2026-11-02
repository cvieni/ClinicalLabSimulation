"""Derive FINAL_READ_BY_TYPE from the raw LIS file.

    python calibrate_final_read.py --raw data/observed_2024_lis_clean.csv [--tail-h 250] [--lo-q 0.05] [--hi-q 0.25]

Per type: tail = TAT above --tail-h  ->  extended_fraction, extended_hours = (P10, P90 of the tail);
the rest ("bulk") -> hold_hours = (bulk quantile lo-q, bulk quantile hi-q).
Raise --hi-q (0.5 -> 0.75) to push the sim's median toward the LIS; keep it low to leave room for the lab's
own simulated delays. Urine: LIS has one pooled 'Invasive Urine' label; the same values go to both sim urine types.
"""
import argparse
import re

import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--raw", required=True)
ap.add_argument("--tail-h", type=float, default=250.0)
ap.add_argument("--lo-q", type=float, default=0.05)
ap.add_argument("--hi-q", type=float, default=0.75)
ap.add_argument("--tat-col", default="TAT_Hours")
a = ap.parse_args()

norm = lambda s: re.sub(r"[^a-z]", "", str(s).lower())
MAP = {"invasiveurine": ["Urine_Invasive", "Urine_NonInvasive"], "urineinvasive": ["Urine_Invasive", "Urine_NonInvasive"],
       "wound": ["Wound"], "genitalwound": ["Wound_Genital"], "woundgenital": ["Wound_Genital"],
       "tissue": ["Tissue"], "fnatissue": ["Tissue_FNA"], "genitaltissue": ["Tissue_genital"],
       "stool": ["Stool"], "bodyfluid": ["BodyFluid"], "bone": ["Bone_Cx"], "respiratory": ["Respiratory", "Resp_CystFibrosis"]}
df = pd.read_csv(a.raw, usecols=["specimen_type", a.tat_col], low_memory=False)
df[a.tat_col] = pd.to_numeric(df[a.tat_col], errors="coerce")
df = df.dropna()
rows = {}
for lab, g in df.groupby("specimen_type"):
    sims = MAP.get(norm(lab))
    if not sims:
        continue
    x = g[a.tat_col].to_numpy()
    tail, bulk = x[x > a.tail_h], x[x <= a.tail_h]
    f = len(tail) / len(x)
    lo, hi = np.quantile(bulk, [a.lo_q, a.hi_q])
    e = (np.quantile(tail, 0.10), np.quantile(tail, 0.90)) if len(tail) >= 30 and f >= 0.01 else (0, 0)
    for s in sims:
        rows[s] = (round(lo), round(hi), round(f if f >= 0.01 else 0.0, 3), round(e[0]), round(e[1]), len(x))
print("FINAL_READ_BY_TYPE = {")
for s, (lo, hi, f, e0, e1, n) in rows.items():
    print(f'    "{s}": {{"hold_hours": ({lo}, {hi}), "extended_fraction": {f}, "extended_hours": ({e0}, {e1})}},   # LIS n={n:,}')
print("}")
