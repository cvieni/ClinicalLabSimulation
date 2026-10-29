"""Pure post-processing: raw tracker log -> per-specimen table -> TAT metrics.

Kept free of simpy / module-level side effects so it can be unit-tested against a CSV of
real or simulated events.
"""
import warnings

import numpy as np
import pandas as pd

import params_config.params_d3 as p
from params_config import event_name as EV
STAGE_ABORTED, STAGE_ARRIVED, STAGE_COMPLETED = EV.ABORTED, EV.ARRIVED, EV.COMPLETED
STAGE_INCUBATION_STARTS, STAGE_NEGATIVE_MARKERS = EV.INCUBATION_STARTS, EV.NEGATIVE_MARKERS
STAGE_PLATING_STARTS, STAGE_REJECTED_PREFIX, STAGE_TECH_REVIEW = EV.PLATING_STARTS, EV.REJECTED_PREFIX, EV.TECH_REVIEW

KEYS = ["Specimen_ID", "Type"]
MIN_N_FOR_PERCENTILE = 10   # below this a P95 is just "the max"; do not report it


def _shift_labels(minutes: pd.Series) -> pd.Series:
    hour = (minutes % 1440) // 60
    label = np.select(
        [(hour >= p.shift_1_start) & (hour < p.shift_1_end),
         (hour >= p.shift_2_start) & (hour < p.shift_2_end)],
        ["Day", "Evening"],
        default="Night",
    )
    out = pd.Series(label, index=minutes.index, dtype=object)
    out[minutes.isna()] = np.nan
    return out


def build_results_frame(df_raw: pd.DataFrame, sim_minutes: float, initial_conditions_loaded: bool = False):
    """Return (df_pivot, diag).

    df_pivot keeps one column per Stage (other modules use them) and adds:
      Arrival_Minute, Completed_Minute, Total_TAT_Hours, Wait_For_Plating_Mins,
      Incubation_Hours, Arrival_Shift, Outcome, In_Window.
    TAT is arrival -> "10. Completed", looked up by exact stage name (not substring).
    """
    stage = df_raw["Stage"].astype(str)

    df_pivot = df_raw.pivot_table(
        index=KEYS, columns="Stage", values="Minute", aggfunc="min"   # explicit, not log-order dependent
    ).reset_index()

    arrived = (df_raw[stage.str.startswith(STAGE_ARRIVED)]
               .groupby(KEYS)["Minute"].min().rename("Arrival_Minute").reset_index())
    completed = (df_raw[stage == STAGE_COMPLETED]
                 .groupby(KEYS)["Minute"].max().rename("Completed_Minute").reset_index())
    if completed.empty:
        warnings.warn(f"No '{STAGE_COMPLETED}' events logged: every TAT will be NaN "
                      f"(run too short, or the completion stage was renamed).")
        completed = pd.DataFrame(columns=KEYS + ["Completed_Minute"])

    df_pivot = df_pivot.merge(arrived, on=KEYS, how="left").merge(completed, on=KEYS, how="left")
    df_pivot["Total_TAT_Hours"] = (df_pivot["Completed_Minute"] - df_pivot["Arrival_Minute"]) / 60.0

    plating_cols = [c for c in STAGE_PLATING_STARTS if c in df_pivot.columns]
    if plating_cols:
        df_pivot["Wait_For_Plating_Mins"] = df_pivot[plating_cols].min(axis=1) - df_pivot["Arrival_Minute"]
    else:
        warnings.warn("None of STAGE_PLATING_STARTS were logged; Wait_For_Plating_Mins is NaN. "
                      "Update params_config/event_name.py to your real stage names.")
        df_pivot["Wait_For_Plating_Mins"] = np.nan

    inc_cols = [c for c in STAGE_INCUBATION_STARTS if c in df_pivot.columns]
    if inc_cols and STAGE_TECH_REVIEW in df_pivot.columns:
        df_pivot["Incubation_Hours"] = (df_pivot[STAGE_TECH_REVIEW] - df_pivot[inc_cols].min(axis=1)) / 60.0
    else:
        df_pivot["Incubation_Hours"] = np.nan

    df_pivot["Arrival_Shift"] = _shift_labels(df_pivot["Arrival_Minute"])

    # Outcome: negatives and positives have very different TATs (a BCx final-negative is ~5 days),
    # so compare them separately to the LIS rather than as one pooled distribution.
    neg_ids = df_raw.loc[stage.isin(STAGE_NEGATIVE_MARKERS), "Specimen_ID"].unique()
    df_pivot["Outcome"] = np.where(
        df_pivot["Specimen_ID"].isin(neg_ids), "neg",
        np.where(df_pivot["Completed_Minute"].notna(), "pos", None),
    )

    # ---- measurement window: warm-up and right-censoring -----------------------------
    warm = 0.0 if initial_conditions_loaded else float(p.warmup_days) * 1440.0
    end = float(sim_minutes) - float(p.cooldown_days) * 1440.0
    trimmed = True
    if end <= warm:
        warnings.warn(
            f"warmup_days={p.warmup_days} + cooldown_days={p.cooldown_days} leave no measurement window "
            f"in a {sim_minutes / 1440:.1f}-day run; using the WHOLE run (biased). Increase sim_days."
        )
        warm, end, trimmed = 0.0, float(sim_minutes), False
    df_pivot["In_Window"] = (df_pivot["Arrival_Minute"] >= warm) & (df_pivot["Arrival_Minute"] < end)

    # ---- diagnostics: how many in-window specimens never finished and why not --------
    rejected = df_raw.loc[stage.str.startswith(STAGE_REJECTED_PREFIX), "Specimen_ID"].unique()
    aborted = df_raw.loc[stage == STAGE_ABORTED, "Specimen_ID"].unique()
    excluded = set(rejected) | set(aborted)
    incomplete = (df_pivot["In_Window"] & df_pivot["Completed_Minute"].isna()
                  & ~df_pivot["Specimen_ID"].isin(excluded))
    diag = {
        "window_start_min": float(warm),
        "window_end_min": float(end),
        "window_trimmed": bool(trimmed),
        "n_in_window": int(df_pivot["In_Window"].sum()),
        "n_rejected": int(len(rejected)),
        "n_aborted": int(len(aborted)),
        "n_incomplete_in_window": int(incomplete.sum()),   # >0 means the window is still censored
    }
    return df_pivot, diag


def _pct(s: pd.Series, q: float) -> float:
    return round(float(np.percentile(s, q)), 2)


def compute_tat_metrics(df_pivot: pd.DataFrame):
    """Return (tat_metrics, tat_summary, tat_values), all restricted to the measurement window.

    tat_summary keys:
      tat_<type>                 mean (legacy key, kept for existing tuning scripts)
      n_tat_<type>               count
      tat_p50_<type>, tat_p95_<type>
      tat_p50_shift_<shift>, tat_p95_shift_<shift>            by ARRIVAL shift
      tat_p50_<type>_<shift>, tat_p95_<type>_<shift>
      tat_p50_<type>_neg|pos, tat_p95_<type>_neg|pos          by culture outcome
    """
    if df_pivot is None or df_pivot.empty or "Total_TAT_Hours" not in df_pivot.columns:
        return {}, {}, []

    df = df_pivot
    if "In_Window" in df.columns:
        df = df[df["In_Window"]]
    df = df.assign(Total_TAT_Hours=pd.to_numeric(df["Total_TAT_Hours"], errors="coerce"))
    df = df.dropna(subset=["Total_TAT_Hours"])
    if df.empty:
        return {}, {}, []

    v = df["Total_TAT_Hours"]
    metrics = {
        "tat_overall_mean": round(float(v.mean()), 2),
        "tat_overall_p50": _pct(v, 50),
        "tat_overall_p95": _pct(v, 95),
        "tat_overall_n": int(len(v)),
    }

    def key(x):
        return str(x).strip().replace(" ", "_")

    summary = {}
    for t, g in df.groupby("Type"):
        s, k = g["Total_TAT_Hours"], key(t)
        summary[f"tat_{k}"] = round(float(s.mean()), 2)
        summary[f"n_tat_{k}"] = int(len(s))
        if len(s) >= MIN_N_FOR_PERCENTILE:
            summary[f"tat_p50_{k}"], summary[f"tat_p95_{k}"] = _pct(s, 50), _pct(s, 95)

    if "Arrival_Shift" in df.columns:
        for sh, g in df.groupby("Arrival_Shift"):
            s = g["Total_TAT_Hours"]
            if len(s) >= MIN_N_FOR_PERCENTILE:
                summary[f"tat_p50_shift_{sh}"], summary[f"tat_p95_shift_{sh}"] = _pct(s, 50), _pct(s, 95)
        for (t, sh), g in df.groupby(["Type", "Arrival_Shift"]):
            s = g["Total_TAT_Hours"]
            if len(s) >= MIN_N_FOR_PERCENTILE:
                k = key(t)
                summary[f"tat_p50_{k}_{sh}"], summary[f"tat_p95_{k}_{sh}"] = _pct(s, 50), _pct(s, 95)

    if "Outcome" in df.columns:
        for (t, oc), g in df.groupby(["Type", "Outcome"]):
            s = g["Total_TAT_Hours"]
            summary[f"n_tat_{key(t)}_{oc}"] = int(len(s))
            if len(s) >= MIN_N_FOR_PERCENTILE:
                summary[f"tat_p50_{key(t)}_{oc}"], summary[f"tat_p95_{key(t)}_{oc}"] = _pct(s, 50), _pct(s, 95)

    return metrics, summary, v.tolist()
