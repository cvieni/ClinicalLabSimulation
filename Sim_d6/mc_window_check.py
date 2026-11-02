"""Why do some types have so few specimens in the Monte Carlo plots?   Reads one saved replication.

    python mc_window_check.py                       # newest results_experiments/mc_* folder, replication 0
    python mc_window_check.py --dir results_experiments/mc_20261101_204409 --rep 0
"""
import argparse
from pathlib import Path

import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--dir", default=None)
ap.add_argument("--rep", type=int, default=0)
a = ap.parse_args()
root = Path(a.dir) if a.dir else sorted(Path("results_experiments").glob("mc_*"), key=lambda p: p.stat().st_mtime)[-1]
s = pd.read_csv(root / "replications" / f"specimens_{a.rep:03d}.csv.gz", low_memory=False)
rt = pd.read_csv(root / "run_table.csv")
w0, w1 = float(rt.get("window_start_min", pd.Series([0])).iloc[0]), float(rt.get("window_end_min", pd.Series([0])).iloc[0])
print(f"folder {root}\nmeasurement window: minute {w0:,.0f} .. {w1:,.0f}  (days {w0 / 1440:.1f} .. {w1 / 1440:.1f})\n")
s["arr_day"] = s["Arrival_Minute"] / 1440.0
s["arrived_in_window"] = (s["Arrival_Minute"] >= w0) & (s["Arrival_Minute"] < w1)
s["completed"] = s["Completed_Minute"].notna()
s["in_win"] = s["In_Window"].astype(bool)
g = s.groupby("Type")
out = pd.DataFrame({
    "n_total": g.size(),
    "arrived_in_window": g["arrived_in_window"].sum(),
    "completed(all)": g["completed"].sum(),
    "in_window_flag": g["in_win"].sum(),
    "in_win_&_has_TAT": g.apply(lambda x: (x["in_win"] & x["Total_TAT_Hours"].notna()).sum()),
    "first_arrival_day": g["arr_day"].min().round(1),
    "last_arrival_day": g["arr_day"].max().round(1),
})
print(out.to_string())
print("\nOutcome values:", s["Outcome"].astype(str).value_counts(dropna=False).head(8).to_dict())
small = [t for t in ("Urine_Invasive", "Resp_CystFibrosis", "Bone_Cx") if t in set(s["Type"])]
for t in small:
    x = s[s["Type"] == t]
    print(f"\n{t}: arrivals per day (all / completed / in window flag)")
    day = x.groupby(x["arr_day"].astype(int)).agg(arrived=("Specimen_ID", "size"), completed=("completed", "sum"), in_win=("in_win", "sum"))
    print(day.iloc[::3].T.to_string())
