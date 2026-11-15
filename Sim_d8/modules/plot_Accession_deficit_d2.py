"""Accessioning deficit plot (fixed).

What was wrong in the old version
---------------------------------
1. `str.contains("Arrived")` matches TWO events per specimen: "1. Arrived" and
   "1c. Arrived at Pre-Accession Hold". Cumulative incoming was therefore 2x the real arrivals, and
   "Current_Queue = incoming - processed" could never fall below the number of specimens that had
   arrived. With zero-delay accessioning it still drew a backlog equal to all arrivals, so adding
   techs could not make the deficit go away.
2. "Queue" mixed three different things: specimens sitting in the pre-accession HOLD (a pure delay,
   no tech involved), specimens waiting in the accession store for a tech (the real queue), and
   specimens being touched. They are now separate lines.
3. It evaluated every unique timestamp with a Python lambda (O(N^2)); it now uses searchsorted on a
   fixed grid.

Accepts the long-format event log (tracker.logs as a list of dicts, or a DataFrame) with columns
Specimen_ID / Type / Stage / Minute (older names Time, Timestamp, stage, Event also work).
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Exact stage names from accession_d2.py / specimen_process. startswith() is deliberate:
# "1. Arrived" does NOT match "1c. Arrived at Pre-Accession Hold" but does match
# "1. Arrived (Initial State)" from the initial-conditions loader.
from Sim_d6.params_config import event_name as EV
ARRIVED, REJECTED, IN_STORE = EV.ARRIVED, EV.REJECTED_PREFIX, EV.ACCESSION_STORE_WAIT
TOUCH_START, TOUCH_DONE = EV.ACCESSION_START, EV.ACCESSION_DONE


def _columns(df: pd.DataFrame):
    low = {c.lower(): c for c in df.columns}
    t = next((low[k] for k in ("minute", "timestamp", "time") if k in low), None)
    s = next((low[k] for k in ("stage", "event") if k in low), None)
    if t is None or s is None:
        raise KeyError(f"Need a time column and a stage column; found {list(df.columns)}")
    return t, s


def _times(df, tcol, scol, prefix):
    m = df[scol].astype(str).str.startswith(prefix)
    return np.sort(df.loc[m, tcol].to_numpy(dtype=float))


def _cum(times, grid):
    return np.searchsorted(times, grid, side="right")


def accession_series(df_raw, step_min: float = 30.0) -> pd.DataFrame:
    """Cumulative counts and inventories on a regular grid (also handy for your own analysis)."""
    df = pd.DataFrame(df_raw) if not isinstance(df_raw, pd.DataFrame) else df_raw
    tcol, scol = _columns(df)
    arrived = _times(df, tcol, scol, ARRIVED)
    rejected = _times(df, tcol, scol, REJECTED)
    in_store = _times(df, tcol, scol, IN_STORE)
    started = _times(df, tcol, scol, TOUCH_START)
    done = _times(df, tcol, scol, TOUCH_DONE)

    grid = np.arange(0.0, float(df[tcol].max()) + step_min, step_min)
    A, R, S, T, D = (_cum(x, grid) for x in (arrived, rejected, in_store, started, done))
    return pd.DataFrame({
        "Day": grid / 1440.0,
        "cum_arrived": A,
        "cum_entered_store": S,
        "cum_accessioned": D,
        "in_preaccession_hold": A - R - S,     # delay, no tech involved
        "store_backlog": S - T,                # waiting for an accession tech  <- the real queue
        "being_touched": T - D,
    })


def plot_accession_deficit(df_raw, output_path: str = "output_pngs/accession_deficit.png", step_min: float = 30.0):
    df = pd.DataFrame(df_raw) if not isinstance(df_raw, pd.DataFrame) else df_raw
    if df.empty:
        print("Raw event log is empty. Cannot generate deficit plot.")
        return None
    ts = accession_series(df, step_min)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 9), dpi=200, sharex=True)
    ax1.plot(ts["Day"], ts["cum_arrived"], "--", color="#1f77b4", lw=2, label="Cumulative arrived (lab)")
    ax1.plot(ts["Day"], ts["cum_entered_store"], ":", color="#2ca02c", lw=2, label="Cumulative entered accession store (after hold)")
    ax1.plot(ts["Day"], ts["cum_accessioned"], "-", color="black", lw=2.5, label="Cumulative accessioned")
    ax1.set_ylabel("Specimens")
    ax1.set_title("Accessioning flow: the gap between the black and green lines is the real accession queue",
                  fontsize=11, fontweight="bold")
    ax1.legend(loc="upper left", frameon=False)
    ax1.grid(True, ls=":", alpha=0.6)

    ax2.plot(ts["Day"], ts["store_backlog"], color="#d62728", lw=2, label="Waiting in accession store for a tech (REAL QUEUE)")
    ax2.plot(ts["Day"], ts["in_preaccession_hold"], color="#9467bd", lw=1.5, label="In pre-accession hold (delay, not a queue)")
    ax2.plot(ts["Day"], ts["being_touched"], color="0.4", lw=1, label="Being accessioned")
    ax2.set_xlabel("Simulation day")
    ax2.set_ylabel("Specimens at that instant")
    ax2.legend(loc="upper left", frameon=False)
    ax2.grid(True, ls=":", alpha=0.6)
    for ax in (ax1, ax2):
        ax.yaxis.set_major_formatter("{x:,.0f}")

    fig.tight_layout()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)

    days = max(ts["Day"].max(), 1e-9)
    print(f"Deficit visualization saved to: {output_path}")
    print(f"  arrived {ts['cum_arrived'].iloc[-1]:,} | entered store {ts['cum_entered_store'].iloc[-1]:,} | "
          f"accessioned {ts['cum_accessioned'].iloc[-1]:,}")
    print(f"  per day: arrive {ts['cum_arrived'].iloc[-1] / days:,.0f} | accessioned {ts['cum_accessioned'].iloc[-1] / days:,.0f}")
    print(f"  store backlog: now {ts['store_backlog'].iloc[-1]:,} | peak {ts['store_backlog'].max():,}")
    return ts
