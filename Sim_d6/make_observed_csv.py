"""Build observed_lis_month.csv (Type,P50,P95[,Shift], hours) for run_montecarlo_and_plot.py --observed.

From your monthly summary (month, specimen_type, obs_p50, obs_p95, n_samples):
    python make_observed_csv.py --by-month data/observed_2024_lis_by_specimen_month.csv --out observed_lis_month.csv
From the raw LIS rows (specimen_type, arrival_datetime, TAT_Hours, ...), optionally split by ARRIVAL shift:
    python make_observed_csv.py --raw data/observed_2024_lis_clean.csv --out observed_lis_month.csv [--by-shift]

P50 / P95 = the n-weighted MEAN of the 12 monthly P50s / P95s. That is what one simulated month is compared with
(the Monte Carlo band is the spread of ONE simulated month). It also writes p50_min/p50_max/p95_min/p95_max (the
spread across real months) and n. --pooled uses the P50/P95 of all rows pooled instead (raw file only).

LIS specimen_type names are mapped to the simulation's names by MAP below. Names it cannot map are PRINTED and skipped:
add them to MAP (or pass --map "Blood Culture=BCx,Body Fluid=BodyFluid").
"""
from __future__ import annotations

import argparse
import re
import sys

import numpy as np
import pandas as pd

# normalised LIS label (lower case, letters/digits only) -> simulation type
MAP = {
    "bloodculture": "BCx", "bcx": "BCx", "bloodcultures": "BCx",
    "bodyfluid": "BodyFluid", "bodyfluids": "BodyFluid",
    "bone": "Bone_Cx", "bonecx": "Bone_Cx", "boneculture": "Bone_Cx",
    "invasiveurine": "Urine_Invasive", "urineinvasive": "Urine_Invasive", "invurine": "Urine_Invasive",
    "noninvasiveurine": "Urine_NonInvasive", "urinenoninvasive": "Urine_NonInvasive", "noninvurine": "Urine_NonInvasive",
    "noninvasiveurinecultur": "Urine_NonInvasive",
    "respiratory": "Respiratory", "respiratorynoncf": "Respiratory", "respiratorynoncfculture": "Respiratory",
    "respiratorycf": "Resp_CystFibrosis", "cfrespiratory": "Resp_CystFibrosis", "respcf": "Resp_CystFibrosis",
    "stool": "Stool", "stoolculture": "Stool",
    "tissue": "Tissue", "tissuecleaned": "Tissue", "tissueother": "Tissue",
    "tissuefna": "Tissue_FNA", "tissfna": "Tissue_FNA", "fna": "Tissue_FNA", "fnatissue": "Tissue_FNA",
    "tissuegenital": "Tissue_genital", "tissgenital": "Tissue_genital", "genitaltissue": "Tissue_genital",
    "wound": "Wound", "woundcleaned": "Wound", "woundother": "Wound",
    "woundgenital": "Wound_Genital", "genitalwound": "Wound_Genital",
}


def norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def shift_of(hour: int) -> str:                       # same rule as get_shift_label_for_hour in the simulation
    return "Day" if 7 <= hour < 15 else "Evening" if 15 <= hour < 23 else "Night"


def wmean(x, w):
    w = np.asarray(w, float)
    return float(np.average(np.asarray(x, float), weights=w)) if w.sum() > 0 else float("nan")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--by-month", type=str)
    ap.add_argument("--raw", type=str)
    ap.add_argument("--out", type=str, default="observed_lis_month.csv")
    ap.add_argument("--by-shift", action="store_true", help="(raw only) one row per type x ARRIVAL shift")
    ap.add_argument("--pooled", action="store_true", help="(raw only) P50/P95 of all rows pooled, not mean of months")
    ap.add_argument("--map", type=str, default=None, help='extra mappings "LIS name=SimType,..."')
    a = ap.parse_args()
    if bool(a.by_month) == bool(a.raw):
        sys.exit("Give exactly one of --by-month or --raw")
    extra = dict(kv.split("=", 1) for kv in a.map.split(",")) if a.map else {}
    mp = {**MAP, **{norm(k): v for k, v in extra.items()}}

    if a.by_month:
        d = pd.read_csv(a.by_month)
        need = {"month", "specimen_type", "obs_p50", "obs_p95", "n_samples"}
        if not need <= set(d.columns):
            sys.exit(f"{a.by_month} needs columns {sorted(need)}; found {list(d.columns)}")
        d["Type"] = d["specimen_type"].map(lambda x: mp.get(norm(x)))
        rows = [dict(Type=t, P50=wmean(g.obs_p50, g.n_samples), P95=wmean(g.obs_p95, g.n_samples),
                     p50_min=g.obs_p50.min(), p50_max=g.obs_p50.max(), p95_min=g.obs_p95.min(), p95_max=g.obs_p95.max(),
                     n=int(g.n_samples.sum()), n_months=g["month"].nunique()) for t, g in d.dropna(subset=["Type"]).groupby("Type")]
    else:
        d = pd.read_csv(a.raw, low_memory=False)
        need = {"specimen_type", "arrival_datetime", "TAT_Hours"}
        if not need <= set(d.columns):
            sys.exit(f"{a.raw} needs columns {sorted(need)}; found {list(d.columns)[:12]}...")
        d["Type"] = d["specimen_type"].map(lambda x: mp.get(norm(x)))
        d["arrival_datetime"] = pd.to_datetime(d["arrival_datetime"], errors="coerce")
        d = d.dropna(subset=["TAT_Hours", "arrival_datetime"])
        d["month"] = d["arrival_datetime"].dt.to_period("M")
        d["Shift"] = d["arrival_datetime"].dt.hour.map(shift_of)
        keys = ["Type", "Shift"] if a.by_shift else ["Type"]
        rows = []
        for k, g in d.dropna(subset=["Type"]).groupby(keys):
            m = g.groupby("month")["TAT_Hours"].agg(p50=lambda s: s.quantile(.5), p95=lambda s: s.quantile(.95), n="size")
            r = dict(zip(keys, k if isinstance(k, tuple) else (k,)))
            if a.pooled:
                r.update(P50=g["TAT_Hours"].quantile(.5), P95=g["TAT_Hours"].quantile(.95))
            else:
                r.update(P50=wmean(m.p50, m.n), P95=wmean(m.p95, m.n))
            r.update(p50_min=m.p50.min(), p50_max=m.p50.max(), p95_min=m.p95.min(), p95_max=m.p95.max(),
                     n=int(len(g)), n_months=len(m))
            rows.append(r)

    unmapped = sorted({str(x) for x in d.loc[d["Type"].isna(), "specimen_type"].unique()})
    out = pd.DataFrame(rows).round(2)
    out.to_csv(a.out, index=False)
    print(out.to_string(index=False))
    print(f"\nWrote {a.out}")
    if unmapped:
        print("\nNOT MAPPED (skipped). Add them with --map \"LIS name=SimType\" or edit MAP:")
        for u in unmapped:
            print("   ", u)
    print("\nUnits: HOURS. Check that TAT_Hours / obs_p50 is arrival -> final result, like the simulation's "
          "'10. Completed'.")


if __name__ == "__main__":
    main()
