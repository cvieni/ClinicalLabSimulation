"""Export validation-ready LIS files from specimen-specific raw CSVs.

This script reads raw LIS files, standardizes timestamps and turnaround time
columns, and writes comparison-ready files for the Monte Carlo validation workflow.

Generated outputs:
- data/observed_<TARGET_YEAR>_lis_clean.csv
- data/observed_<TARGET_YEAR>_lis_by_specimen_month.csv
- data/observed_<TARGET_YEAR>_lis.csv
- data/observed_<TARGET_YEAR>_lis_pooled_tat.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from typing import Iterable

import numpy as np
import pandas as pd

# ===========================================================================
# TOGGLE YEAR AND DIRECTORY STRUCTURE HERE
# ===========================================================================
TARGET_YEAR = "2024"
# TARGET_YEAR = "2025"

PROJECT_ROOT = Path(__file__).resolve().parent
CLIN_SIM_FOLDER = PROJECT_ROOT.parent
REAL_DATA = CLIN_SIM_FOLDER / "ARUP_data" / f"Cleaned_{TARGET_YEAR}_sql"
OUTPUT_DIR = PROJECT_ROOT / "data_stoolupdate"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Specimen-specific LIS CSV files for the target year
# ---------------------------------------------------------------------------
def build_csv_files(year: str) -> list[Path]:
    """The raw LIS files for one year (folder ARUP_data/Cleaned_<year>_sql). Used for --year so the data AND the output name agree."""
    d = CLIN_SIM_FOLDER / "ARUP_data" / f"Cleaned_{year}_sql"
    names = ["BCx", "BodyFluid", "Bone", "InvUrine", "Inv_Urine_UofU", "NonInv_Urine", "NonInv_Urine_UofU",
             "Respiratory_NonCF", "Respiratory_CF", "Stool_Campy", "Stool_Ecoli", "Stool_Vibrio", "Stool_Yersinia",
             "Tiss_genital", "Tiss_FNA", "TissueCleaned", "Wound_genital", "Wound_Cleaned"]
    return [d / f"{n}_{year}.csv" for n in names]


CSV_FILES: list[str | Path] = [
    REAL_DATA / f"BCx_{TARGET_YEAR}.csv",
    REAL_DATA / f"BodyFluid_{TARGET_YEAR}.csv",
    REAL_DATA / f"Bone_{TARGET_YEAR}.csv",
    REAL_DATA / f"InvUrine_{TARGET_YEAR}.csv",
    REAL_DATA / f"Inv_Urine_UofU_{TARGET_YEAR}.csv",
    REAL_DATA / f"NonInv_Urine_{TARGET_YEAR}.csv",
    REAL_DATA / f"NonInv_Urine_UofU_{TARGET_YEAR}.csv",
    REAL_DATA / f"Respiratory_NonCF_{TARGET_YEAR}.csv",
    REAL_DATA / f"Respiratory_CF_{TARGET_YEAR}.csv",
    # REAL_DATA / f"Stool_{TARGET_YEAR}.csv",
    REAL_DATA / f"Stool_Campy_{TARGET_YEAR}.csv",
    REAL_DATA / f"Stool_Ecoli_{TARGET_YEAR}.csv",
    REAL_DATA / f"Stool_Vibrio_{TARGET_YEAR}.csv",
    REAL_DATA / f"Stool_Yersinia_{TARGET_YEAR}.csv",
    
    REAL_DATA / f"Tiss_genital_{TARGET_YEAR}.csv",
    REAL_DATA / f"Tiss_FNA_{TARGET_YEAR}.csv",
    REAL_DATA / f"TissueCleaned_{TARGET_YEAR}.csv",
    REAL_DATA / f"Wound_genital_{TARGET_YEAR}.csv",
    REAL_DATA / f"Wound_Cleaned_{TARGET_YEAR}.csv",
]


def _resolve_files(file_paths: Iterable[str | Path] | None = None) -> list[Path]:
    """Resolve file paths relative to the project root and handle duplicates."""
    raw_paths = list(file_paths) if file_paths is not None else list(CSV_FILES)
    resolved: list[Path] = []
    seen: set[Path] = set()

    for path in raw_paths:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        candidate = candidate.resolve()
        if not candidate.exists():
            print(f"  !! MISSING raw file (skipped): {candidate}")
        if candidate.exists() and candidate not in seen:
            resolved.append(candidate)
            seen.add(candidate)

    return resolved


def _normalize_column_map(columns: list[str]) -> dict[str, str]:
    """Normalize columns like 'IN LAB WHEN' and 'TAT Hours' to a consistent key."""
    lookup = {}
    for col in columns:
        key = str(col).strip()
        normalized = key.lower().replace(" ", "_").replace("-", "_").replace("/", "_")
        normalized = "".join(ch for ch in normalized if ch.isalnum() or ch == "_")
        lookup[key] = normalized
    return lookup


def _coerce_datetime(series: pd.Series) -> pd.Series:
    """Safely convert datetime-like columns to pandas datetime."""
    return pd.to_datetime(series, errors="coerce")


def _infer_specimen_type(file_path: Path, fallback: str | None = "Unknown") -> str:
    """Infer a human-readable specimen label from the file name."""
    stem = file_path.stem.lower()

    # Explicit mapping for ARUP LIS file naming patterns
    mappings = [
        ("bcx", "Blood Culture"),
        ("blood", "Blood Culture"),
        ("noninv_urine", "Non-Invasive Urine"),      # must come BEFORE "inv_urine" (it is a substring of it)
        ("inv_urine", "Invasive Urine"),
        ("invurine", "Invasive Urine"),
        ("urine", "Urine"),
        ("bodyfluid", "Body Fluid"),
        ("body_fluid", "Body Fluid"),
        ("respiratory_noncf", "Respiratory (Non-CF)"),
        ("respiratory_cf", "Respiratory (CF)"),
        ("resp_cf", "Respiratory (CF)"),
        ("resp_noncf", "Respiratory (Non-CF)"),
        ("respiratory", "Respiratory"),
        ("stool", "Stool"),
        ("tiss_genital", "Genital Tissue"),
        ("tiss_fna", "FNA Tissue"),
        ("tissue", "Tissue"),
        ("bone", "Bone"),
        ("wound_genital", "Genital Wound"),
        ("wound", "Wound"),
    ]

    for key, label in mappings:
        if key in stem:
            return label

    # Intelligent fallback: strips any 4-digit year suffix (e.g., 'SomeSpecimen_2025' -> 'Somespecimen')
    clean_stem = re.sub(r"_\d{4}$", "", file_path.stem).replace("_", " ").title()
    return fallback or clean_stem


def _extract_tat_hours(df: pd.DataFrame, specimen_label: str) -> pd.Series:
    """Compute TAT_Hours from whichever timestamp columns are present."""
    columns = [str(c).strip() for c in df.columns]
    cols_lower = {str(c).strip().lower().replace(" ", "_").replace("-", "_"): c for c in columns}

    tat_candidates = [
        "TAT_Hours",
        "tat_hours",
        "Turnaround_Hours",
        "turnaround_hours",
        "Total_TAT_Hours",
        "total_tat_hours",
    ]
    for candidate in tat_candidates:
        if candidate in cols_lower:
            return pd.to_numeric(df[cols_lower[candidate]], errors="coerce") / 1.0

    receive_candidates = [
        "in_lab_when",
        "received_datetime",
        "received",
        "arrival_datetime",
        "collection_datetime",
        "specimen_received_datetime",
        "date_time_received",
    ]
    complete_candidates = [
        "complete_when",
        "rpt_when",
        "final_report_datetime",
        "final_report_time",
        "resulted_datetime",
        "reported_datetime",
        "report_datetime",
        "report_time",
        "resulted",
        "completed_datetime",
        "completed_time",
        "verification_datetime",
        "date_time_reported",
        "date_time_resulted",
        "result_date",
        "result_time",
    ]

    receive_col = next((cols_lower[c] for c in receive_candidates if c in cols_lower), None)
    complete_col = next((cols_lower[c] for c in complete_candidates if c in cols_lower), None)

    if receive_col is not None and complete_col is not None:
        receive_time = _coerce_datetime(df[receive_col])
        complete_time = _coerce_datetime(df[complete_col])

        # Invalidate EDW placeholder dates (e.g. 1/1/1900)
        complete_time = complete_time.where(complete_time.dt.year > 1900, pd.NaT)
        receive_time = receive_time.where(receive_time.dt.year > 1900, pd.NaT)

        return ((complete_time - receive_time).dt.total_seconds() / 3600.0).clip(lower=0)

    raise ValueError(
        f"Could not infer TAT_Hours for {specimen_label}. Expected a direct TAT column or "
        "arrival + final-report timestamp columns in the raw LIS CSV."
    )


def _read_one_file(file_path: Path) -> pd.DataFrame:
    """Read a raw specimen-type LIS file and standardize it for validation exports."""
    df = pd.read_csv(file_path)
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    renamed = _normalize_column_map(df.columns)
    df = df.rename(columns=renamed)

    specimen_label = _infer_specimen_type(file_path)
    df["specimen_type"] = specimen_label
    df["source_file"] = file_path.stem

    arrival_candidates = [
        "IN_LAB_WHEN",
        "in_lab_when",
        "received_datetime",
        "arrival_datetime",
        "date_time_received",
        "collection_datetime",
    ]
    arrival_col = next((c for c in arrival_candidates if c in df.columns), None)
    if arrival_col is not None:
        df["arrival_datetime"] = _coerce_datetime(df[arrival_col])
    else:
        df["arrival_datetime"] = pd.NaT

    if "TAT_Hours" not in df.columns:
        df["TAT_Hours"] = _extract_tat_hours(df, specimen_label)

    df["TAT_Hours"] = pd.to_numeric(df["TAT_Hours"], errors="coerce")

    month_col = next((c for c in ["month", "Month", "REPORT_MONTH"] if c in df.columns), None)
    if month_col is not None:
        df["month"] = df[month_col].astype(str)
    elif "arrival_datetime" in df.columns and df["arrival_datetime"].notna().any():
        df["month"] = pd.to_datetime(df["arrival_datetime"], errors="coerce").dt.strftime("%b")
    else:
        df["month"] = "Unknown"

    keep_cols = [
        c
        for c in [
            "specimen_type",
            "month",
            "arrival_datetime",
            "TAT_Hours",
            "IN_LAB_WHEN",
            "in_lab_when",
            "received_datetime",
            "report_datetime",
            "final_report_datetime",
            "resulted_datetime",
        ]
        if c in df.columns
    ]
    if keep_cols:
        df = df[keep_cols + [c for c in df.columns if c not in keep_cols]]

    return df


def _summarize_monthly_overall(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate to overall month-level summary expected by the validation plot."""
    if df.empty or "TAT_Hours" not in df.columns:
        return pd.DataFrame(columns=["month", "obs_p50", "obs_p95"])

    valid = df.dropna(subset=["TAT_Hours"]).copy()
    if valid.empty:
        return pd.DataFrame(columns=["month", "obs_p50", "obs_p95"])

    monthly = (
        valid.groupby("month", as_index=False)["TAT_Hours"]
        .agg(
            obs_p50=lambda s: float(np.percentile(s, 50)),
            obs_p95=lambda s: float(np.percentile(s, 95)),
        )
    )

    month_order = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    monthly["month"] = pd.Categorical(monthly["month"], categories=month_order, ordered=True)
    monthly = monthly.dropna(subset=["month"]).sort_values("month").reset_index(drop=True)
    return monthly


def _summarize_monthly_by_specimen(df: pd.DataFrame) -> pd.DataFrame:
    """Create a month-by-specimen comparison table for more granular validation."""
    if df.empty or "TAT_Hours" not in df.columns:
        return pd.DataFrame(columns=["month", "specimen_type", "obs_p50", "obs_p95", "n_samples"])

    valid = df.dropna(subset=["TAT_Hours"]).copy()
    if valid.empty:
        return pd.DataFrame(columns=["month", "specimen_type", "obs_p50", "obs_p95", "n_samples"])

    grouped = (
        valid.groupby(["month", "specimen_type"], as_index=False)["TAT_Hours"]
        .agg(
            obs_p50=lambda s: float(np.percentile(s, 50)),
            obs_p95=lambda s: float(np.percentile(s, 95)),
            n_samples="size",
        )
    )

    month_order = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    grouped["month"] = pd.Categorical(grouped["month"], categories=month_order, ordered=True)
    grouped = grouped.dropna(subset=["month"]).sort_values(["month", "specimen_type"]).reset_index(drop=True)
    return grouped


def export_validation_files(
    file_paths: Iterable[str | Path] | None = None,
    output_dir: str | Path | None = None,
    year: str = TARGET_YEAR,
) -> dict[str, Path]:
    """Read all raw LIS files, clean them, and export validation-ready summaries."""
    file_list = _resolve_files(file_paths)
    if not file_list:
        raise FileNotFoundError(
            "No input LIS CSV files were found. Update CSV_FILES at the top of this script "
            "or pass --file values on the command line."
        )

    output_root = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    output_root.mkdir(parents=True, exist_ok=True)

    cleaned_frames: list[pd.DataFrame] = []
    for file_path in file_list:
        if not file_path.exists():
            print(f"Skipping missing file: {file_path}")
            continue
        print(f"Processing: {file_path.name}")
        cleaned_df = _read_one_file(file_path)
        n_ok = int(cleaned_df["TAT_Hours"].notna().sum()) if not cleaned_df.empty else 0
        print(f"    -> {len(cleaned_df):,} rows, {n_ok:,} with a usable TAT, label = "
              f"{cleaned_df['specimen_type'].iloc[0] if not cleaned_df.empty else 'EMPTY FILE'}")
        if not cleaned_df.empty:
            cleaned_frames.append(cleaned_df)

    if not cleaned_frames:
        raise ValueError("No valid LIS rows were extracted from the selected files.")

    combined = pd.concat(cleaned_frames, ignore_index=True)

    clean_path = output_root / f"observed_{year}_lis_clean.csv"
    monthly_by_specimen_path = output_root / f"observed_{year}_lis_by_specimen_month.csv"
    monthly_overall_path = output_root / f"observed_{year}_lis.csv"
    pooled_tat_path = output_root / f"observed_{year}_lis_pooled_tat.csv"

    before = combined.groupby("specimen_type").size()
    combined = combined.dropna(subset=["TAT_Hours"]).copy()
    combined = combined[combined["TAT_Hours"].between(0, 1000)].copy()
    lost = (before - combined.groupby("specimen_type").size().reindex(before.index, fill_value=0))
    if lost.sum():
        print("  rows dropped (no TAT or TAT outside 0-1000 h):", {k: int(v) for k, v in lost.items() if v})
    print("  rows per specimen_type in the output:", {k: int(v) for k, v in combined.groupby("specimen_type").size().items()})
    combined.to_csv(clean_path, index=False)

    monthly_by_specimen = _summarize_monthly_by_specimen(combined)
    monthly_by_specimen.to_csv(monthly_by_specimen_path, index=False)

    monthly_overall = _summarize_monthly_overall(combined)
    monthly_overall.to_csv(monthly_overall_path, index=False)

    pooled_tat = combined["TAT_Hours"].dropna().astype(float)
    pd.DataFrame({"TAT_Hours": pooled_tat.values}).to_csv(pooled_tat_path, index=False)

    print(f"\nSaved cleaned LIS export: {clean_path}")
    print(f"Saved monthly specimen summary: {monthly_by_specimen_path}")
    print(f"Saved monthly overall validation file: {monthly_overall_path}")
    print(f"Saved pooled TAT values: {pooled_tat_path}")

    return {
        "clean": clean_path,
        "monthly_by_specimen": monthly_by_specimen_path,
        "monthly_validation": monthly_overall_path,
        "pooled_tat": pooled_tat_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export validation-friendly LIS summaries from specimen-specific raw CSV files."
    )
    parser.add_argument(
        "--file",
        dest="files",
        action="append",
        default=None,
        help="Raw LIS CSV file to include. Repeat the flag to include multiple files.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(OUTPUT_DIR),
        help="Directory where the final export CSV files will be written.",
    )
    parser.add_argument(
        "--year",
        type=str,
        default=TARGET_YEAR,
        help="Target year string (e.g., '2024' or '2025').",
    )
    args = parser.parse_args()

    files = args.files if args.files else build_csv_files(args.year)
    export_validation_files(file_paths=files, output_dir=args.output_dir, year=args.year)


if __name__ == "__main__":
    main()