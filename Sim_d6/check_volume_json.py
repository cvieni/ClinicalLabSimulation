"""Why is daily_volume_mean wrong?   Re-computes it exactly like the Extract_real_world_data_* scripts, step by step.

    python check_volume_json.py --year 2025 --data-dir "<...>/ARUP_data/Cleaned_2025_sql" --json-dir "<...>/ARUP_data/json_clned_data_2025"
(--data-dir / --json-dir default to ARUP_data next to or one level above this script.)
"""
import argparse, json
from pathlib import Path
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--year", default="2025")
ap.add_argument("--data-dir", default=None)
ap.add_argument("--json-dir", default=None)
a = ap.parse_args()
here = Path(__file__).resolve().parent
cands = [here / "ARUP_data", here.parent / "ARUP_data"]
root = next((c for c in cands if c.exists()), None)
data_dir = Path(a.data_dir) if a.data_dir else (root / f"Cleaned_{a.year}_sql" if root else None)
json_dir = Path(a.json_dir) if a.json_dir else (root / f"json_clned_data_{a.year}" if root else None)
print("data_dir:", data_dir, "\njson_dir:", json_dir, "\n")

rows = []
for f in sorted(Path(data_dir).glob("*.csv")):
    df = pd.read_csv(f, low_memory=False)
    n_raw = len(df)
    t = pd.to_datetime(df["IN_LAB_WHEN"], errors="coerce") if "IN_LAB_WHEN" in df.columns else pd.Series(pd.NaT, index=df.index)
    has_t = t.notna()
    cancel_col = "CANCEL_BY" if "CANCEL_BY" in df.columns else ("CANCEL_CODE" if "CANCEL_CODE" in df.columns else None)
    # alternative arrival stamps, in case IN_LAB_WHEN is mostly empty
    alt = {c: int(pd.to_datetime(df[c], errors="coerce").notna().sum()) for c in ("RECEIVE_WHEN", "CULTURE_START_WHEN") if c in df.columns}
    days = t[has_t].dt.date.nunique()
    name = f.stem
    # ---- what the Extract script's cancellation filter does to this file ----
    def _kept(df, robust):
        if "CANCEL_BY" not in df.columns:
            return len(df)
        cb = df["CANCEL_BY"].astype(str).str.strip()
        if robust:
            hc = df["CANCEL_BY"].notna() & ~cb.str.lower().isin({"", "-1", "-1.0", "0", "0.0", "nan", "none", "null", "<na>", "nat"})
        else:
            hc = df["CANCEL_BY"].notna() & (cb != "-1") & (cb != "")
        cw = pd.to_datetime(df["CANCEL_WHEN"], errors="coerce") if "CANCEL_WHEN" in df.columns else pd.Series(pd.NaT, index=df.index)
        if robust:
            pre = hc & (t.isna() | ((cw > pd.Timestamp("2000-01-01")) & (cw < t)))
        else:
            pre = hc & (t.isna() | (cw < t)) if "CANCEL_WHEN" in df.columns else hc & t.isna()
        return int((~pre & t.notna()).sum())
    kept_old, kept_new = _kept(df, False), _kept(df, True)
    cb_top = df["CANCEL_BY"].astype(str).value_counts().head(3).to_dict() if "CANCEL_BY" in df.columns else {}
    js = json_dir / f"{name}_calibrated_params.json"
    jv = json.load(open(js))["daily_volume_mean"] if js.exists() else None
    rows.append(dict(file=name, rows=n_raw, valid_IN_LAB_WHEN=int(has_t.sum()), distinct_days=days,
                     first=str(t[has_t].min())[:10], last=str(t[has_t].max())[:10],
                     rows_per_day=round(n_raw / max(days, 1), 1), valid_per_day=round(has_t.sum() / max(days, 1), 1),
                     json_daily_volume=jv, kept_old_filter=kept_old, kept_robust_filter=kept_new, CANCEL_BY_top=str(cb_top), **{f"valid_{k}": v for k, v in alt.items()}))
pd.set_option("display.width", 250)
print(pd.DataFrame(rows).to_string(index=False))