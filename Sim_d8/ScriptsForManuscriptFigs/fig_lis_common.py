"""Shared LIS-extraction and plotting helpers for FigS3_AccessionTimes_Bcx.py and FigS4_AccessionTimes_Other.py.
Nothing here needs editing; sizes, folders and file lists are set at the top of each Fig*.py."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import fig_common as fc

DATE_COLS = ["IN_LAB_WHEN", "RECEIVE_WHEN", "CULTURE_START_WHEN", "CANCEL_WHEN", "PERF_WHEN", "RPT_WHEN", "COMPLETE_WHEN"]
NO_CANCEL_DEFAULT = {"", "-1", "-1.0", "0", "0.0", "nan", "none", "null", "<na>", "nat"}
WEEKDAY_C, WEEKEND_C = "#2a78d6", "#eb6834"


def read_group(paths):
    """Read and stack the files that exist; warn about the ones that do not."""
    dfs = []
    for p in paths:
        p = Path(p)
        if p.exists():
            dfs.append(pd.read_csv(p))
        else:
            print(f"  Warning: file not found: {p}")
    return pd.concat(dfs, ignore_index=True) if dfs else None


def prepare(df, year, *, cancel_cols=("CANCEL_BY", "CANCEL_CODE"), no_cancel=NO_CANCEL_DEFAULT, ref_cancel_col="CANCEL_WHEN",
            trim_acc=False):
    """Cancellation classification, arrival features, accession-time series. Returns (df_kept, info dict).
    Pre-lab cancellations (cancelled before IN_LAB_WHEN) are dropped; lab-processed cancellations are kept as workload.
    cancel_cols: the first of these that exists is the cancel flag. trim_acc: drop accession times outside the 2.5-97.5 percentiles."""
    df = df.copy()
    total_raw = len(df)
    for c in DATE_COLS:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    col = next((c for c in cancel_cols if c in df.columns), None)
    if col:
        has_cancel = df[col].notna() & ~df[col].astype(str).str.strip().str.lower().isin(no_cancel)
    elif "CANCEL_WHEN" in df.columns:
        has_cancel = df["CANCEL_WHEN"].notna() & (df["CANCEL_WHEN"] > pd.Timestamp("2000-01-01"))
    else:
        has_cancel = pd.Series(False, index=df.index)
    if ref_cancel_col in df.columns:
        valid = df[ref_cancel_col].notna() & (df[ref_cancel_col] > pd.Timestamp("2000-01-01"))
        pre = has_cancel & (df["IN_LAB_WHEN"].isna() | (valid & (df[ref_cancel_col] < df["IN_LAB_WHEN"])))
    else:
        pre = has_cancel & df["IN_LAB_WHEN"].isna()
    df["is_lab_canceled"] = has_cancel & ~pre
    df = df[~pre].dropna(subset=["IN_LAB_WHEN"]).copy()

    df["arrival_hour"] = df["IN_LAB_WHEN"].dt.hour
    df["day_type"] = np.where(df["IN_LAB_WHEN"].dt.dayofweek >= 5, "Weekend", "Weekday")
    cal_days = 366 if (int(year) % 4 == 0 and (int(year) % 100 != 0 or int(year) % 400 == 0)) else 365
    hourly = df["arrival_hour"].value_counts().reindex(range(24), fill_value=0)

    if "Time2Accession" in df.columns:
        df["accession_time_min"] = pd.to_numeric(df["Time2Accession"], errors="coerce")
    else:
        df["accession_time_min"] = np.nan
    if df["accession_time_min"].dropna().empty:
        if "CULTURE_START_WHEN" in df.columns:
            df["accession_time_min"] = (df["CULTURE_START_WHEN"] - df["IN_LAB_WHEN"]).dt.total_seconds() / 60.0
        elif "CANCEL_WHEN" in df.columns:
            df.loc[df["is_lab_canceled"], "accession_time_min"] = (df["CANCEL_WHEN"] - df["IN_LAB_WHEN"]).dt.total_seconds() / 60.0
    acc = df["accession_time_min"].dropna()
    acc = acc[(acc >= 0.1) & (acc <= 120.0)]
    if trim_acc and not acc.empty:
        acc = acc[(acc >= acc.quantile(0.025)) & (acc <= acc.quantile(0.975))]

    ccount = (df.loc[df["is_lab_canceled"], "CANCEL_CODE"].fillna("Unspecified").value_counts()
              if "CANCEL_CODE" in df.columns else pd.Series(dtype=int))
    info = dict(n_raw=total_raw, n_pre_lab_canceled=int(pre.sum()), n_active=len(df), n_lab_canceled=int(df["is_lab_canceled"].sum()),
                lab_cancel_rate_pct=round(100 * df["is_lab_canceled"].sum() / max(len(df), 1), 2),
                daily_volume_mean=round(len(df) / cal_days, 2),
                accession_n=len(acc), accession_mean_min=float(acc.mean()) if len(acc) else np.nan,
                accession_p99_min=float(acc.quantile(0.99)) if len(acc) else np.nan,
                cancel_counts=ccount, valid_acc=acc,
                hourly_weights=(hourly / max(hourly.sum(), 1)).round(4).tolist())
    return df, info


# ------------------------------------------------------------------------------------------------ plots
def _fig(cfg, top=0.35, height=None):
    return fc.new_fig(cfg["w"], height or cfg["h"], left_in=cfg["left"], right_in=0.2, bottom_in=0.6, top_in=top)


def plot_hourly(df, name, cfg, zero_fill=True):
    """Average share of the day's arrivals in each hour, weekday vs weekend. zero_fill=True counts hours with no arrivals as 0
    (False reproduces the old script, which averaged only over days with at least one arrival in that hour)."""
    d = df.assign(date=df["IN_LAB_WHEN"].dt.date)
    piv = d.groupby(["date", "day_type", "arrival_hour"]).size().unstack("arrival_hour").reindex(columns=range(24))
    if zero_fill:
        piv = piv.fillna(0)
    avg = piv.groupby(level="day_type").mean()
    share = 100 * avg.div(avg.sum(axis=1), axis=0)
    fig, ax = _fig(cfg)
    x = np.arange(24)
    for k, (dt, col) in enumerate((("Weekday", WEEKDAY_C), ("Weekend", WEEKEND_C))):
        if dt in share.index:
            ax.bar(x + (k - 0.5) * 0.4, share.loc[dt].to_numpy(), width=0.4, color=col, edgecolor="white", linewidth=0.3, label=dt)
    ax.set_xticks(x[::2])
    ax.set_xticklabels([f"{h:02d}" for h in x[::2]])
    ax.set_xlabel("Hour of day (arrival in lab)")
    ax.set_ylabel("Share of daily arrivals (%)")
    ax.set_title(name, loc="left", fontsize=8, fontweight="bold")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left", frameon=False)
    fc.save_both(fig, f"{cfg['prefix']}_{name}_hourly_arrivals", cfg["out"], cfg["dpi"], cfg["bare"])


def plot_accession(acc, name, cfg, mean_val, p99_val):
    if acc.empty:
        return
    fig, ax = _fig(cfg)
    ax.hist(acc, bins=40, weights=np.full(len(acc), 100.0 / len(acc)), color="#2ca02c", edgecolor="white", linewidth=0.4, alpha=0.8)
    ax.axvline(mean_val, color="#d62728", linestyle="--", linewidth=1.4, label=f"Mean {mean_val:.1f} min")
    ax.axvline(p99_val, color="#eda100", linestyle=":", linewidth=1.6, label=f"99th percentile {p99_val:.1f} min")
    ax.set_xlim(0, max(p99_val * 1.15, 10))
    ax.set_xlabel("Accessioning duration (min)")
    ax.set_ylabel("Share of specimens (%)")
    ax.set_title(name, loc="left", fontsize=8, fontweight="bold")
    ax.legend(loc="upper right", frameon=False)
    fc.save_both(fig, f"{cfg['prefix']}_{name}_accession_time", cfg["out"], cfg["dpi"], cfg["bare"])


def plot_cancel(counts, name, cfg, top_n=10):
    if counts.empty:
        return
    c = counts.head(top_n)
    fig, ax = _fig(cfg, height=max(cfg["h"], 0.25 * len(c) + 1.1))
    ax.barh(range(len(c)), c.to_numpy(), color="#d9534f", edgecolor="white", linewidth=0.4, height=0.72)
    for k, v in enumerate(c.to_numpy()):
        ax.text(v + 0.01 * c.max(), k, f"{int(v):,}", va="center", fontsize=6.5, color=fc.INK2)
    ax.set_yticks(range(len(c)))
    ax.set_yticklabels([str(i) for i in c.index])
    ax.set_ylim(-0.6, len(c) - 0.4)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Cancelled specimens (n)")
    ax.set_ylabel("Cancel code")
    ax.set_title(f"{name}: {int(counts.sum()):,} lab-cancelled", loc="left", fontsize=8, fontweight="bold")
    fc.save_both(fig, f"{cfg['prefix']}_{name}_cancel_codes", cfg["out"], cfg["dpi"], cfg["bare"])


def fit_and_plot_ttp(df, name, cfg, max_ttp_min):
    """Positive-bottle time to positivity (h): histogram + lognormal fit (scipy, free loc). Returns the fit dict."""
    if "Time2Pos_min" not in df.columns:
        print(f"  {name}: no Time2Pos_min column, TTP skipped")
        return {}
    t = pd.to_numeric(df["Time2Pos_min"], errors="coerce")
    ok = (~df["is_lab_canceled"]) & (t > 0) & (t <= max_ttp_min)
    hrs = (t[ok] / 60.0).dropna()
    if hrs.empty:
        print(f"  WARNING {name}: no valid positive TTP values, TTP skipped")
        return {}
    shape, loc, scale = stats.lognorm.fit(hrs)
    edges = np.linspace(0, hrs.max(), 41)
    fig, ax = _fig(cfg)
    ax.hist(hrs, bins=edges, weights=np.full(len(hrs), 100.0 / len(hrs)), color="#2b5c8f", edgecolor="white", linewidth=0.4, alpha=0.75,
            label="LIS time to positivity")
    xx = np.linspace(0, hrs.max(), 300)
    ax.plot(xx, stats.lognorm.pdf(xx, s=shape, loc=loc, scale=scale) * (edges[1] - edges[0]) * 100, color="#d62728", linewidth=1.8,
            label=f"Lognormal fit (shape {shape:.2f}, loc {loc:.1f}, scale {scale:.1f})")
    ax.set_xlim(0, max(hrs.max(), 120))
    ax.set_xlabel("Time to positivity (h)")
    ax.set_ylabel("Share of positive specimens (%)")
    ax.set_title(name, loc="left", fontsize=8, fontweight="bold")
    ax.legend(loc="upper right", frameon=False)
    fc.save_both(fig, f"{cfg['prefix']}_{name}_time_to_positivity", cfg["out"], cfg["dpi"], cfg["bare"])
    return dict(n_positive=len(hrs), ttp_median_h=float(hrs.median()), ttp_shape=shape, ttp_loc=loc, ttp_scale=scale)


def summary_row(name, info, extra=None):
    row = {"group": name, **{k: v for k, v in info.items() if k not in ("cancel_counts", "valid_acc", "hourly_weights")}}
    row.update({f"w_{h:02d}": w for h, w in enumerate(info["hourly_weights"])})
    row.update(extra or {})
    return row
