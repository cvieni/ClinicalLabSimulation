"""Summarize LIS turnaround metrics by specimen type and shift.

This script is intentionally separate from the raw extraction files. It answers the
operational question: which specimen types and shifts are driving the longest TAT,
especially the upper-tail P95 behavior that usually matters most for calibration.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Edit these values at the top of the file to point at your LIS export and desired outputs.
INPUT_CSVS = [
    Path("data/observed_2024_lis_clean.csv"),
]
OUTPUT_CSV = Path("results_experiments/lis_shift_specimen_summary.csv")
OUTPUT_PNG = Path("output_pngs/lis_shift_specimen_summary.png")
TAIL_DRIVER_CSV = Path("results_experiments/lis_tail_drivers_summary.csv")
MC_COMPARISON_CSV = Path("results_experiments/lis_vs_mc_summary.csv")
MC_INPUT_DIR = Path("results_montecarlo_output")


def _shift_label_for_hour(hour: int) -> str:
    if 7 <= hour < 15:
        return "Day"
    if 15 <= hour < 23:
        return "Evening"
    return "Night"


def _infer_specimen_type(file_path: str | Path) -> str:
    stem = Path(file_path).stem.lower()
    if "bcx" in stem or "blood" in stem:
        return "BloodCulture"
    if "body" in stem or "fluid" in stem:
        return "BodyFluid"
    if "urine" in stem:
        return "Urine"
    if "wound" in stem:
        return "Wound"
    if "resp" in stem:
        return "Respiratory"
    if "stool" in stem:
        return "Stool"
    if "tiss" in stem or "tissue" in stem:
        return "Tissue"
    return "Unknown"


def _normalize_lis_df(df: pd.DataFrame, specimen_label: str | None = None) -> pd.DataFrame:
    """Normalize a LIS export into a validation-ready dataframe."""
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]

    arrival_col = next(
        (
            c
            for c in [
                "IN_LAB_WHEN",
                "in_lab_when",
                "RECEIVE_WHEN",
                "receive_when",
                "received_datetime",
                "arrival_datetime",
                "specimen_received_datetime",
                "collection_datetime",
                "date_time_received",
            ]
            if c in df.columns
        ),
        None,
    )
    if arrival_col is None:
        raise ValueError("No arrival timestamp column found in the LIS file.")

    df["arrival_datetime"] = pd.to_datetime(df[arrival_col], errors="coerce")
    df = df[df["arrival_datetime"].notna()].copy()

    tat_col = next(
        (
            c
            for c in [
                "TAT_Hours",
                "tat_hours",
                "Turnaround_Hours",
                "turnaround_hours",
                "total_tat_hours",
                "TOTAL_TAT_HOURS",
            ]
            if c in df.columns
        ),
        None,
    )
    if tat_col is not None:
        df["TAT_Hours"] = pd.to_numeric(df[tat_col], errors="coerce")
    else:
        complete_candidates = [
            "COMPLETE_WHEN",
            "complete_when",
            "RPT_WHEN",
            "rpt_when",
            "REPORT_WHEN",
            "report_when",
            "final_report_datetime",
            "reported_datetime",
            "report_datetime",
            "resulted_datetime",
            "verification_datetime",
        ]
        complete_col = next((c for c in complete_candidates if c in df.columns), None)
        if complete_col is None:
            raise ValueError(
                "No TAT column and no usable completion timestamp column were found in the LIS file."
            )
        df["TAT_Hours"] = (
            (pd.to_datetime(df[complete_col], errors="coerce") - df["arrival_datetime"]).dt.total_seconds() / 3600.0
        ).clip(lower=0)

    df["TAT_Hours"] = pd.to_numeric(df["TAT_Hours"], errors="coerce")
    df = df[(df["TAT_Hours"].notna()) & (df["TAT_Hours"] >= 0) & (df["TAT_Hours"] <= 30 * 24)].copy()

    specimen_col = next(
        (
            c
            for c in [
                "SPECIMEN_TYPE_HNAM",
                "SPECIMEN_TYPE",
                "GENERAL_SOURCE",
                "SPECIFIC_SOURCE_HNAC",
                "BODY_SITE_DISPLAY_KEY_HNAM",
                "SOURCE_HNAM",
                "SPECIMEN_SOURCE",
                "specimen_type",
            ]
            if c in df.columns
        ),
        None,
    )
    if specimen_col is not None:
        df["specimen_type"] = df[specimen_col].fillna("Unknown").astype(str)
    else:
        df["specimen_type"] = specimen_label or "Unknown"

    df["arrival_hour"] = df["arrival_datetime"].dt.hour
    df["shift_label"] = df["arrival_hour"].map(_shift_label_for_hour)
    df["month"] = df["arrival_datetime"].dt.strftime("%b")
    df["day_of_week"] = df["arrival_datetime"].dt.day_name()
    df["is_weekend"] = df["arrival_datetime"].dt.dayofweek >= 5
    return df


def summarize_by_specimen_and_shift(df: pd.DataFrame) -> pd.DataFrame:
    summary = (
        df.groupby(["specimen_type", "shift_label"], dropna=False)["TAT_Hours"]
        .agg(
            n_samples="size",
            p50_tat_hours=lambda s: float(np.percentile(s, 50)),
            p90_tat_hours=lambda s: float(np.percentile(s, 90)),
            p95_tat_hours=lambda s: float(np.percentile(s, 95)),
            mean_tat_hours=lambda s: float(s.mean()),
            max_tat_hours=lambda s: float(s.max()),
        )
        .reset_index()
        .sort_values(["specimen_type", "shift_label"])
        .reset_index(drop=True)
    )
    return summary


def build_tail_driver_summary(summary: pd.DataFrame) -> pd.DataFrame:
    """Flag the specimen/shift groups that contribute most to the upper-tail TAT problem."""
    if summary.empty:
        return pd.DataFrame(columns=[
            "specimen_type",
            "shift_label",
            "n_samples",
            "p50_tat_hours",
            "p90_tat_hours",
            "p95_tat_hours",
            "mean_tat_hours",
            "max_tat_hours",
            "tail_spread_hours",
            "p95_to_p50_ratio",
            "tail_flag",
        ])

    tail = summary.copy()
    tail["tail_spread_hours"] = tail["p95_tat_hours"] - tail["p50_tat_hours"]
    tail["p95_to_p50_ratio"] = tail["p95_tat_hours"] / np.where(tail["p50_tat_hours"] > 0, tail["p50_tat_hours"], 1)

    def _flag(row):
        if row["p95_tat_hours"] >= 250:
            return "Extreme tail"
        if row["p95_tat_hours"] >= 150:
            return "High tail"
        if row["p95_to_p50_ratio"] >= 2.5:
            return "Tail amplification"
        return "Moderate"

    tail["tail_flag"] = tail.apply(_flag, axis=1)
    tail = tail.sort_values(["p95_tat_hours", "tail_spread_hours"], ascending=[False, False]).reset_index(drop=True)
    return tail


def _rename_mc_column_to_specimen(column_name: str) -> str:
    key = str(column_name).replace("tat_", "").strip()
    mapping = {
        "BCx": "Blood Culture",
        "BodyFluid": "Body Fluid",
        "Bone_Cx": "Bone",
        "Resp_CystFibrosis": "Respiratory",
        "Respiratory": "Respiratory",
        "Stool": "Stool",
        "Tissue": "Tissue",
        "Tissue_FNA": "FNA Tissue",
        "Tissue_genital": "Genital Tissue",
        "Urine_Invasive": "Invasive Urine",
        "Urine_NonInvasive": "Urine",
        "Wound": "Wound",
        "Wound_Genital": "Genital Wound",
    }
    normalized = key.replace("_", " ")
    return mapping.get(key, mapping.get(normalized, normalized.strip()))


def summarize_monte_carlo_by_specimen(mc_input_dir: str | Path) -> pd.DataFrame:
    """Aggregate specimen-level MC TAT metrics so they can be compared directly with LIS values."""
    mc_dir = Path(mc_input_dir)
    if not mc_dir.exists():
        return pd.DataFrame(columns=["specimen_type", "sim_n_runs", "sim_p50", "sim_p90", "sim_p95", "sim_mean"])

    records: list[dict] = []
    for csv_path in sorted(mc_dir.glob("*.csv")):
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            continue
        tat_cols = [c for c in df.columns if str(c).startswith("tat_")]
        for col in tat_cols:
            values = pd.to_numeric(df[col], errors="coerce").dropna()
            if values.empty:
                continue
            spec_name = _rename_mc_column_to_specimen(col)
            records.append({
                "specimen_type": spec_name,
                "sim_n_runs": int(len(values)),
                "sim_p50": float(np.percentile(values, 50)),
                "sim_p90": float(np.percentile(values, 90)),
                "sim_p95": float(np.percentile(values, 95)),
                "sim_mean": float(values.mean()),
            })

    if not records:
        return pd.DataFrame(columns=["specimen_type", "sim_n_runs", "sim_p50", "sim_p90", "sim_p95", "sim_mean"])

    summary = pd.DataFrame(records)
    agg = summary.groupby("specimen_type", as_index=False).agg(
        sim_n_runs=("sim_n_runs", "sum"),
        sim_p50=("sim_p50", "mean"),
        sim_p90=("sim_p90", "mean"),
        sim_p95=("sim_p95", "mean"),
        sim_mean=("sim_mean", "mean"),
    )
    return agg.sort_values("sim_p95", ascending=False).reset_index(drop=True)


def compare_lis_to_monte_carlo(observed_summary: pd.DataFrame, mc_summary: pd.DataFrame) -> pd.DataFrame:
    """Compare the observed specimen-by-shift LIS summary against the simulation's specimen-level mean/TAT distribution."""
    if observed_summary.empty or mc_summary.empty:
        return pd.DataFrame(columns=[
            "specimen_type",
            "observed_p50",
            "observed_p95",
            "sim_p50",
            "sim_p95",
            "abs_error_p50",
            "abs_error_p95",
            "pct_error_p50",
            "pct_error_p95",
            "closest_match_rank",
            "fit_status",
        ])

    observed_by_specimen = observed_summary.groupby("specimen_type", as_index=False).agg(
        observed_p50=("p50_tat_hours", "mean"),
        observed_p90=("p90_tat_hours", "mean"),
        observed_p95=("p95_tat_hours", "mean"),
        observed_mean=("mean_tat_hours", "mean"),
    )

    merged = observed_by_specimen.merge(mc_summary, on="specimen_type", how="inner")
    if merged.empty:
        return pd.DataFrame(columns=[
            "specimen_type",
            "observed_p50",
            "observed_p95",
            "sim_p50",
            "sim_p95",
            "abs_error_p50",
            "abs_error_p95",
            "pct_error_p50",
            "pct_error_p95",
            "closest_match_rank",
            "fit_status",
        ])

    merged["abs_error_p50"] = (merged["sim_p50"] - merged["observed_p50"]).abs()
    merged["abs_error_p95"] = (merged["sim_p95"] - merged["observed_p95"]).abs()
    merged["pct_error_p50"] = np.where(
        merged["observed_p50"] > 0,
        (merged["sim_p50"] - merged["observed_p50"]) / merged["observed_p50"] * 100,
        np.nan,
    )
    merged["pct_error_p95"] = np.where(
        merged["observed_p95"] > 0,
        (merged["sim_p95"] - merged["observed_p95"]) / merged["observed_p95"] * 100,
        np.nan,
    )

    merged["fit_status"] = merged["abs_error_p95"].apply(lambda x: "Close" if x <= 25 else "Moderate" if x <= 75 else "Poor")
    merged = merged.sort_values(["abs_error_p95", "abs_error_p50"], ascending=True).reset_index(drop=True)
    merged["closest_match_rank"] = np.arange(1, len(merged) + 1)
    return merged


def plot_shift_specimen_summary(summary: pd.DataFrame, output_png: str | Path) -> None:
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)

    shift_order = ["Day", "Evening", "Night"]
    summary["shift_label"] = pd.Categorical(summary["shift_label"], categories=shift_order, ordered=True)
    summary = summary.sort_values(["specimen_type", "shift_label"]).reset_index(drop=True)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    specimen_names = sorted(summary["specimen_type"].unique())

    # Panel A: P95 TAT (Hours)
    panel_a = summary.pivot(index="specimen_type", columns="shift_label", values="p95_tat_hours").reindex(specimen_names)
    ax = axes[0]
    panel_a.reindex(columns=shift_order).plot(kind="bar", ax=ax, width=0.8)
    ax.set_title("P95 TAT by specimen type and shift")
    ax.set_ylabel("Hours")
    ax.set_xlabel("Specimen type")
    ax.legend(title="Shift")
    ax.grid(axis="y", linestyle=":", alpha=0.5)

    # Panel B: n_samples (Count)
    panel_b = summary.pivot(index="specimen_type", columns="shift_label", values="n_samples").reindex(specimen_names)
    ax2 = axes[1]
    panel_b.reindex(columns=shift_order).plot(kind="bar", ax=ax2, width=0.8, colormap="viridis")
    ax2.set_title("Sample count by specimen type and shift")
    ax2.set_ylabel("Count")
    ax2.set_xlabel("Specimen type")
    ax2.legend(title="Shift")
    ax2.grid(axis="y", linestyle=":", alpha=0.5)

    fig.tight_layout()
    fig.savefig(output_png, dpi=300)
    plt.close(fig)


def _resolve_input_files(paths: list[str | Path] | None = None) -> list[Path]:
    if paths:
        resolved: list[Path] = []
        for p in paths:
            candidate = Path(p)
            if candidate.exists():
                resolved.append(candidate.resolve())
        return resolved

    resolved_paths: list[Path] = []
    for candidate in INPUT_CSVS:
        if candidate.exists():
            resolved_paths.append(candidate.resolve())
    return resolved_paths


def _demo_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "IN_LAB_WHEN": pd.to_datetime(
                [
                    "2024-01-01 07:05:00",
                    "2024-01-01 08:10:00",
                    "2024-01-01 15:35:00",
                    "2024-01-02 23:40:00",
                    "2024-01-02 07:20:00",
                    "2024-01-03 20:00:00",
                    "2024-01-03 09:15:00",
                    "2024-01-04 18:40:00",
                ]
            ),
            "TAT_Hours": [16.0, 20.0, 30.0, 48.0, 18.0, 42.0, 24.0, 39.0],
            "specimen_type": [
                "BloodCulture",
                "BloodCulture",
                "BodyFluid",
                "BloodCulture",
                "BloodCulture",
                "BodyFluid",
                "BloodCulture",
                "BodyFluid",
            ],
        }
    )


def _build_summary_from_files(input_files: list[str | Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for file_path in input_files:
        file_path = Path(file_path)
        specimen_name = _infer_specimen_type(file_path)
        try:
            df = pd.read_csv(file_path)
            frames.append(_normalize_lis_df(df, specimen_name))
        except Exception as exc:  # pragma: no cover - non-LIS warnings are expected
            print(f"Skipping {file_path.name}: {exc}")

    if not frames:
        print("No valid LIS CSV inputs were found. Falling back to demo data.")
        return summarize_by_specimen_and_shift(_normalize_lis_df(_demo_dataframe(), specimen_label=None)).fillna(0)

    combined = pd.concat(frames, ignore_index=True)
    return summarize_by_specimen_and_shift(combined).fillna(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize LIS turnaround metrics by specimen type and shift.")
    parser.add_argument(
        "--csv",
        action="append",
        default=None,
        help="Optional LIS CSV path override. Repeat as needed for multiple files.",
    )
    parser.add_argument("--output-csv", type=str, default=str(OUTPUT_CSV))
    parser.add_argument("--output-png", type=str, default=str(OUTPUT_PNG))
    args = parser.parse_args()

    input_files = _resolve_input_files(args.csv) if args.csv else _resolve_input_files()
    if not input_files:
        final_summary = summarize_by_specimen_and_shift(_normalize_lis_df(_demo_dataframe(), specimen_label=None)).fillna(0)
    else:
        final_summary = _build_summary_from_files(input_files)

    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    final_summary.to_csv(output_csv, index=False)

    tail_summary = build_tail_driver_summary(final_summary)
    if not tail_summary.empty:
        tail_output = Path(TAIL_DRIVER_CSV)
        tail_output.parent.mkdir(parents=True, exist_ok=True)
        tail_summary.to_csv(tail_output, index=False)
        print(f"Saved tail-driver summary to: {tail_output}")
        print(tail_summary.head(10).to_string(index=False))

    mc_summary = summarize_monte_carlo_by_specimen(MC_INPUT_DIR)
    comparison = compare_lis_to_monte_carlo(final_summary, mc_summary)
    if not comparison.empty:
        comparison_output = Path(MC_COMPARISON_CSV)
        comparison_output.parent.mkdir(parents=True, exist_ok=True)
        comparison.to_csv(comparison_output, index=False)
        print(f"Saved LIS-vs-MC comparison to: {comparison_output}")
        print(comparison.head(10).to_string(index=False))

    plot_shift_specimen_summary(final_summary, args.output_png)
    print(f"Saved shift/specimen summary to: {output_csv}")
    print(f"Saved figure to: {args.output_png}")
    print(final_summary.to_string(index=False))


if __name__ == "__main__":
    main()
