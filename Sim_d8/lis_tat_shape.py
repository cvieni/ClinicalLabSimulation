"""Shape of the real TAT distribution per specimen type, to decide what a 'final report' looks like.

    python lis_tat_shape.py --raw data/observed_2024_lis_clean.csv

Prints, per type: n, TAT quantiles (hours) and the three most common 24-hour bins (where TAT piles up, e.g. a fixed
5-day or 14-day final report). Also lists every distinct specimen_type label so mapping problems are visible.
"""
import argparse

import numpy as np
import pandas as pd

from make_observed_csv import MAP, norm

ap = argparse.ArgumentParser()
ap.add_argument("--raw", required=True)
ap.add_argument("--bin-hours", type=float, default=24.0)
a = ap.parse_args()
d = pd.read_csv(a.raw, low_memory=False, usecols=lambda c: c in ("specimen_type", "TAT_Hours"))
d = d.dropna(subset=["TAT_Hours"])
print("Distinct specimen_type labels (n):")
print(d["specimen_type"].value_counts().to_string(), "\n")
d["Type"] = d["specimen_type"].map(lambda x: MAP.get(norm(x), f"?{x}"))
rows = []
for t, g in d.groupby("Type"):
    h = g["TAT_Hours"].to_numpy(float)
    b = np.floor(h / a.bin_hours).astype(int)
    top = pd.Series(b).value_counts(normalize=True).head(3)
    modes = ", ".join(f"{int(k * a.bin_hours)}-{int((k + 1) * a.bin_hours)}h {100 * v:.0f}%" for k, v in top.items())
    q = np.quantile(h, [.05, .10, .25, .50, .75, .90, .95])
    rows.append(dict(Type=t, n=len(h), **{f"p{p}": round(v, 1) for p, v in zip((5, 10, 25, 50, 75, 90, 95), q)}, top_bins=modes))
print(pd.DataFrame(rows).to_string(index=False))
