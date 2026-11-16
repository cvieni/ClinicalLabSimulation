# Extract_real_world_data_BCx_d2.py

import os
import pandas as pd
import numpy as np
import scipy.stats as stats
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# Set visual style for publication-ready lab plots
sns.set_theme(style="whitegrid")
plt.rcParams.update({'font.size': 11})


# =========================================================== SETTINGS (edit these) ===========================================================
OUTPUT_DIR = Path("manuscript_png")          # where the PNGs (and table2_validation.csv) go
PNG_WIDTH = 4.2                              # inches
LEFT_MARGIN_IN = 1.75                        # room for the y-axis labels (inches); raise it if a label is cut off
LEGEND_COLUMNS = 1
PNG_HEIGHT = None                            # inches; None = automatic from the number of rows (0.3 in per row + 1.4)
DPI = 300
BARE = False                                 # True: the unlabelled version also loses the legend and in-plot text

MC_DIR = "results_experiments/mc_gerada_gram"                       # Monte Carlo folder (has replications/ and run_table.csv)
OBS_2025 = ["data/observed_2025_lis_clean.csv"]                     # list of RAW LIS files (tuned / calibration year)
OBS_2024 = ["data/observed_2024_lis_clean.csv"]                                                       # list of RAW LIS files (held-out validation year); [] = none
OBS_EXCLUDE = None                                                  # drop LIS rows whose source file name contains this text

# ==============================================================================================================================================



def Extract_and_Plot_Metrics(csv_path, png_dir, proj_dir, year, save_plots=True):
    base_filename = os.path.splitext(os.path.basename(csv_path))[0]
    isblood = "bcx" in base_filename.lower()

    df = pd.read_csv(csv_path)
    total_raw_records = len(df)
    print(f"\n================ ROW COUNT AUDIT: {base_filename} ================")
    print(f"1. Raw CSV total rows:                      {len(df):,}")

    # --- DEBUGGING INSPECTION ---
    print(f"\n--- Column Names for {base_filename} ---")
    print(df.columns.tolist())
    print("\n--- First 3 Rows ---")
    print(df.head(3))
    print("------------------------------------------\n")

    # Convert timestamps
    date_cols = ["IN_LAB_WHEN", "RECEIVE_WHEN", "CULTURE_START_WHEN", "CANCEL_WHEN", "PERF_WHEN", "RPT_WHEN", "COMPLETE_WHEN",]
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    print(f"2. Rows with valid IN_LAB_WHEN timestamp:   {df['IN_LAB_WHEN'].notna().sum():,}")

    # -------------------------------------------------------------
    # 0. STRICT CANCELLATION CLASSIFICATION
    # -------------------------------------------------------------
    ref_cancel_col = "PERF_WHEN" if not isblood and "PERF_WHEN" in df.columns else "CANCEL_WHEN"

    if ref_cancel_col in df.columns:
        df[ref_cancel_col] = pd.to_datetime(df[ref_cancel_col], errors="coerce")

    # Identify cancellation flag (ignoring default system IDs / empty values)
    if "CANCEL_CODE" in df.columns:
        has_cancel = (
            df["CANCEL_CODE"].notna()
            & (df["CANCEL_CODE"].astype(str).str.strip() != "")
            & (~df["CANCEL_CODE"].astype(str).str.strip().str.upper().isin(["NONE", "0", "-1", "NULL"]))
        )
        if ref_cancel_col in df.columns:
            print(f"3. Rows with valid {ref_cancel_col} timestamp:  {df[ref_cancel_col].notna().sum():,}")
    elif "CANCEL_WHEN" in df.columns:
        has_cancel = (df["CANCEL_WHEN"].notna()) & (pd.to_datetime(df["CANCEL_WHEN"], errors="coerce") > pd.Timestamp("2000-01-01"))        
    else:
        has_cancel = pd.Series(False, index=df.index)

    # Pre-Lab Canceled: Canceled BEFORE reaching the lab (Drop these)
    if ref_cancel_col in df.columns:
        valid_ref_date = (df[ref_cancel_col].notna()) & (df[ref_cancel_col] > pd.Timestamp("2000-01-01"))
        pre_lab_mask = has_cancel & (df["IN_LAB_WHEN"].isna() | (valid_ref_date & (df[ref_cancel_col] < df["IN_LAB_WHEN"])))
        
        earlier_cancel = has_cancel & df["IN_LAB_WHEN"].notna() & valid_ref_date & (df[ref_cancel_col] < df["IN_LAB_WHEN"])
        print(f"4. Rows where {ref_cancel_col} < IN_LAB_WHEN:    {earlier_cancel.sum():,}")
    else:
        pre_lab_mask = has_cancel & df["IN_LAB_WHEN"].isna()

    # Lab-Processed Canceled: Arrived at lab, then canceled by lab staff (KEEP THESE)
    lab_cancel_mask = has_cancel & ~pre_lab_mask

    # Flag for downstream simulation parameter assignment
    df["is_lab_canceled"] = lab_cancel_mask

    # DROP PRE-LAB CANCELLATIONS ONLY
    df_after_prelab = df[~pre_lab_mask].copy()
    df = df[~pre_lab_mask].copy()
    print(f"5. Rows remaining after pre-lab drop:       {len(df_after_prelab):,}")

    # Drop any remaining records without valid lab arrival time
    df = df.dropna(subset=["IN_LAB_WHEN"]).copy()

    # Metrics on Lab Cancellations
    total_pre_lab = pre_lab_mask.sum()
    total_lab_canceled = lab_cancel_mask.sum()
    cancel_counts = df[df["is_lab_canceled"]]["CANCEL_CODE"].fillna("Unspecified").value_counts() if "CANCEL_CODE" in df.columns else pd.Series(dtype=int)

    cancellation_metrics = {
        "total_raw_records": total_raw_records,
        "pre_lab_canceled": int(total_pre_lab),
        "lab_processed_then_canceled": int(total_lab_canceled),
        "lab_cancel_rate_pct": round((total_lab_canceled / max(len(df), 1)) * 100, 2),
        "cancel_code_counts": cancel_counts.to_dict(),
    }

    # -------------------------------------------------------------
    # 1. ARRIVAL WEIGHTS & DAILY VOLUMES (Includes Lab-Canceled Workload)
    # -------------------------------------------------------------
    df["arrival_hour"] = df["IN_LAB_WHEN"].dt.hour
    df["is_weekend"] = df["IN_LAB_WHEN"].dt.dayofweek >= 5
    df["day_type"] = np.where(df["is_weekend"], "Weekend", "Weekday")

    hourly_counts = df["arrival_hour"].value_counts().reindex(range(24), fill_value=0)
    hourly_arrival_weights = (hourly_counts / max(hourly_counts.sum(), 1)).round(4).tolist()

    weekday_counts = df[~df["is_weekend"]]["arrival_hour"].value_counts().reindex(range(24), fill_value=0)
    weekend_counts = df[df["is_weekend"]]["arrival_hour"].value_counts().reindex(range(24), fill_value=0)

    weekday_weights = (weekday_counts / max(weekday_counts.sum(), 1)).round(4).tolist()
    weekend_weights = (weekend_counts / max(weekend_counts.sum(), 1)).round(4).tolist()

    calendar_days = 366 if (int(year) % 4 == 0 and (int(year) % 100 != 0 or int(year) % 400 == 0)) else 365
    daily_volume_mean = round(len(df) / calendar_days, 2)

    # -------------------------------------------------------------
    # 1B. Accessioning / Central Processing Time Calculation
    # -------------------------------------------------------------
    PROC_TIMESTAMP_COL = 'Time2Accession' 

    if PROC_TIMESTAMP_COL in df.columns:
        df["accession_time_min"] = pd.to_numeric(df[PROC_TIMESTAMP_COL], errors="coerce")
    else:
        df["accession_time_min"] = np.nan

    if df["accession_time_min"].dropna().empty:
        if "CULTURE_START_WHEN" in df.columns:
            df["accession_time_min"] = (df["CULTURE_START_WHEN"] - df["IN_LAB_WHEN"]).dt.total_seconds() / 60.0
        elif "CANCEL_WHEN" in df.columns:
            df.loc[df["is_lab_canceled"], "accession_time_min"] = (
                (df["CANCEL_WHEN"] - df["IN_LAB_WHEN"]).dt.total_seconds() / 60.0
            )

    valid_acc = df["accession_time_min"].dropna()
    valid_acc = valid_acc[(valid_acc >= 0.1) & (valid_acc <= 120.0)]

    if not valid_acc.empty:
        m = float(valid_acc.mean())
        s = float(valid_acc.std())

        if s > 0 and m > 0:
            log_variance = np.log(1 + (s**2 / m**2))
            sigma_val = np.sqrt(log_variance)
            mu_val = np.log(m) - (log_variance / 2)
        else:
            mu_val, sigma_val = np.log(max(m, 0.1)), 0.1

        counts, bin_edges = np.histogram(valid_acc, bins=200)
        probabilities = counts / max(counts.sum(), 1)
        probabilities = probabilities / probabilities.sum()
        
        accession_config = {
            "units": "minutes",
            "min_accession_min": round(float(valid_acc.min())),
            "max_accession_min": round(float(valid_acc.quantile(0.99))),
            "mean_accession_min": round(float(valid_acc.mean())),
            "std_accession_min": round(float(valid_acc.std())),
        }
    else:
        accession_config = {
            "units": "minutes",
            "min_accession_min": 2.0,
            "max_accession_min": 10.0,
            "mean_accession_min": 5.0,
            "std_accession_min": 2.0,
        }

    # -------------------------------------------------------------
    # 2. Extract Positivity Rate & Fit Time-to-Positivity (TTP)
    # -------------------------------------------------------------
    if "Time2Pos_min" in df.columns:
        df["ttp_min_cleaned"] = pd.to_numeric(df["Time2Pos_min"], errors="coerce")
    else:
        df["ttp_min_cleaned"] = np.nan

    max_ttp_limit = 7500 if isblood else 15000

    not_canceled = ~df["is_lab_canceled"]
    has_positive_ttp = df["ttp_min_cleaned"] > 0
    within_time_bound = df["ttp_min_cleaned"] <= max_ttp_limit

    pos_mask = not_canceled & has_positive_ttp & within_time_bound
    positive_df = df[pos_mask].copy()
    positive_ttps_hrs = positive_df["ttp_min_cleaned"] / 60.0

    if positive_ttps_hrs.empty:
        raise ValueError(
            f"CRITICAL ERROR: Zero valid positive TTP samples found for '{base_filename}'."
        )

    if not positive_ttps_hrs.empty:
        shape, loc, scale = stats.lognorm.fit(positive_ttps_hrs)
    else:
        shape, loc, scale = 0.0, 0.0, 0.0

    # Directory for figures
    fig_s3_dir = os.path.join(proj_dir, "manuscript_figures", "FigS3_Bcx_time")
    os.makedirs(fig_s3_dir, exist_ok=True)

    # -------------------------------------------------------------
    # 3. GRAPH 1: Time to Positivity (TTP) Distribution + Fit (Percentage)
    # -------------------------------------------------------------
    plt.figure(figsize=(10, 5))
    
    ax1 = sns.histplot(
        positive_ttps_hrs, 
        kde=False, 
        stat="probability", 
        bins=40, 
        color="#2b5c8f", 
        edgecolor="black", 
        alpha=0.6,
        label="Historical TTP Data"
    )
    
    vals = ax1.get_yticks()
    ax1.set_yticklabels(['{:,.1f}%'.format(x * 100) for x in vals])

    x_axis = np.linspace(0, positive_ttps_hrs.max(), 300)
    pdf_fitted = stats.lognorm.pdf(x_axis, s=shape, loc=loc, scale=scale)
    bin_width = (positive_ttps_hrs.max() - 0) / 40
    plt.plot(x_axis, pdf_fitted * bin_width, 'r-', lw=2.5, label=f'Fitted LogNorm (shape={shape:.2f}, scale={scale:.2f})')

    plt.title(f"{base_filename} Time-to-Positivity (TTP) Distribution", fontsize=14, fontweight="bold")
    plt.ylabel("Percentage of Positive Samples (%)", fontsize=12)
    plt.xlabel("Time to Positivity (Hours)", fontsize=12)
    plt.xlim(0, max(positive_ttps_hrs.max(), 120))
    plt.legend(frameon=True)
    plt.tight_layout()
    
    if save_plots:
        plot1_path = os.path.join(fig_s3_dir, f"{base_filename}_TimeToPositive_distribution.png")
        plt.savefig(plot1_path, dpi=300)
        print(f"--> Saved plot: {plot1_path}")
    plt.show()

    # -------------------------------------------------------------
    # 4. GRAPH 2: Hourly Sample Arrivals (Weekday vs Weekend as Percentage Share)
    # -------------------------------------------------------------
    hourly_daytype_avg = (
        df.groupby(['day_type', 'arrival_hour', df['IN_LAB_WHEN'].dt.date])
        .size()
        .groupby(['day_type', 'arrival_hour'])
        .mean()
        .reset_index(name='avg_samples')
    )
    
    hourly_daytype_avg['pct_share'] = hourly_daytype_avg.groupby('day_type')['avg_samples'].transform(lambda x: (x / x.sum()) * 100)

    plt.figure(figsize=(12, 5))
    
    palette = {"Weekday": "#1f77b4", "Weekend": "#ff7f0e"}
    ax2 = sns.barplot(
        data=hourly_daytype_avg, 
        x="arrival_hour", 
        y="pct_share", 
        hue="day_type", 
        palette=palette,
        edgecolor="black",
        alpha=0.85
    )

    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: '{:.1f}%'.format(y)))

    plt.title(f"{base_filename} Average Sample Arrival Share by Hour", fontsize=14, fontweight="bold")
    plt.xlabel("Hour of Day (00:00 - 23:00)", fontsize=12)
    plt.ylabel("Percentage Share of Daily Arrivals (%)", fontsize=12)
    plt.xticks(ticks=range(0, 24), labels=[f"{h:02d}:00" for h in range(0, 24)], rotation=45)
    plt.legend(title="Day Type", frameon=True)
    plt.tight_layout()
    
    if save_plots:
        plot2_path = os.path.join(fig_s3_dir, f"{base_filename}_hourly_arrivals_weekday_vs_weekend.png")
        plt.savefig(plot2_path, dpi=300)
        print(f"--> Saved plot: {plot2_path}")
    plt.show()

    # -------------------------------------------------------------
    # 4B. GRAPH: Accessioning / Processing Time Distribution (Percentage)
    # -------------------------------------------------------------
    if PROC_TIMESTAMP_COL in df.columns and not valid_acc.empty:
        plt.figure(figsize=(10, 5))
        
        ax_acc = sns.histplot(
            valid_acc, 
            bins=40, 
            stat="percent",
            color="#2ca02c", 
            edgecolor="black", 
            alpha=0.65
        )

        mean_val = accession_config["mean_accession_min"]
        p99_val = accession_config["max_accession_min"]
        
        plt.axvline(mean_val, color="red", linestyle="--", linewidth=2, label=f"Mean: {mean_val:.1f} min")
        plt.axvline(p99_val, color="darkorange", linestyle=":", linewidth=2, label=f"99th Percentile: {p99_val:.1f} min")

        plt.title(f"{base_filename} Accessioning Processing Time Distribution", fontsize=14, fontweight="bold")
        plt.xlabel("Accessioning Duration (Minutes)", fontsize=12)
        plt.ylabel("Percentage of Samples (%)", fontsize=12)
        plt.xlim(0, max(p99_val * 1.15, 10))
        plt.legend(frameon=True)
        plt.tight_layout()

        if save_plots:
            plot_acc_path = os.path.join(fig_s3_dir, f"{base_filename}_accession_time_distribution.png")
            plt.savefig(plot_acc_path, dpi=300)
            print(f"--> Saved plot: {plot_acc_path}")
        plt.show()

    return hourly_arrival_weights, daily_volume_mean

# ------------------------------------------------------------------------------
# PIPELINE EXECUTION
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    TARGET_YEAR = "2025"

    BASE_DIR = Path(__file__).resolve().parent.parent
    proj_dir = BASE_DIR / "ARUP_data"
    data_dir = proj_dir / f"Cleaned_{TARGET_YEAR}_sql"
    png_dir = proj_dir / f"png_{TARGET_YEAR}_direct"

    specimen_files = {
        "BCx": data_dir / f"BCx_{TARGET_YEAR}.csv",
        "BodyFluid": data_dir / f"BodyFluid_{TARGET_YEAR}.csv",
    }

    results = {}
    for spec_type, csv_path in specimen_files.items():
        if csv_path.exists():
            print(f"\nProcessing {spec_type} from {csv_path.name}...")
            weights, daily_vol = Extract_and_Plot_Metrics(str(csv_path), str(png_dir), proj_dir, year=TARGET_YEAR)
            results[spec_type] = {
                "weights": weights,
                "daily_volume": daily_vol,
            }
        else:
            print(f"Warning: File not found for {spec_type} at {csv_path}")