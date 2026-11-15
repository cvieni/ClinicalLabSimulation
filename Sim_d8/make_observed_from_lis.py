#!/usr/bin/env python
"""Rebuild observed_lis_month.csv (+ _by_shift) from the SAME cleaned LIS files the manuscript figures use, so the
troubleshooting plots and the manuscript show identical observed values.

    python make_observed_from_lis.py --obs data/observed_2025_lis_clean.csv --out observed_lis_month.csv
    (then)  python run_montecarlo_and_plot.py ... --observed observed_lis_month.csv

Needs make_manuscript_figures_micro.py in the same folder (uses its loader, stool split and name mapping).
Observed percentiles are POOLED over every specimen of the year (not an average of monthly percentiles).
Column Basis says how exact the match is: 'exact' (one LIS group = one sim type, incl. stool by test code and CF / non-CF) or
'pooled' (one LIS group shared by several sim types, e.g. both urine types get the same urine value).
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_manuscript_figures_micro as mm

ap = argparse.ArgumentParser()
ap.add_argument("--obs", nargs="+", required=True, help="cleaned LIS csv(s), e.g. data/observed_2025_lis_clean.csv")
ap.add_argument("--out", default="observed_lis_month.csv")
a = ap.parse_args()

obs = mm.load_obs(a.obs)
obs = mm.with_stool_split(obs, "obs")
rows, rows_sh = [], []
for group, sims in mm.GROUPS.items():
    g = obs[obs["group"] == group]
    if g.empty:
        continue
    sims = [s for s in sims if s not in ("Stool_EcoliRoutine", "Resp_NonCF", "Resp_CF", "Stool")]
    if group == "Stool" and any(k in set(obs["group"]) for k in mm.STOOL_SPLIT.values()):
        continue                                   # pooled stool is superseded by the four test codes
    if not sims:                                   # stool test-code groups
        sims = [s for s, c in mm.SIM_STOOL_CODE.items() if mm.STOOL_SPLIT.get(c) == group and s != "Stool_EcoliRoutine"]
    basis = "exact" if len(sims) == 1 else "pooled"
    for s in sims:
        rows.append(dict(Type=s, P50=np.percentile(g["tat_h"], 50), P95=np.percentile(g["tat_h"], 95), n=len(g), Basis=basis, LIS_group=group))
        if "shift" in g:
            for sh in mm.SHIFTS:
                gs = g[g["shift"] == sh]["tat_h"]
                if len(gs) >= 10:
                    rows_sh.append(dict(Type=s, Shift=sh, P50=np.percentile(gs, 50), P95=np.percentile(gs, 95), n=len(gs)))
out = pd.DataFrame(rows)
out.to_csv(a.out, index=False, float_format="%.2f")
print(out.to_string(index=False))
if rows_sh:
    p = Path(a.out).with_name(Path(a.out).stem + "_by_shift.csv")
    pd.DataFrame(rows_sh).to_csv(p, index=False, float_format="%.2f")
    print("wrote", p)
print("wrote", a.out)
