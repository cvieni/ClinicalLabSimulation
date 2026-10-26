# % Extract_real_world_data_BCx_d2.py

  
import os
import pandas as pd
import numpy as np
import scipy.stats as stats
import matplotlib.pyplot as plt
import seaborn as sns
import json
from pathlib import Path

# Set visual style for publication-ready lab plots
sns.set_theme(style="whitegrid")
plt.rcParams.update({'font.size': 11})

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
    # 1. No IN_LAB_WHEN timestamp, OR
    # 2. CANCEL_WHEN is earlier than IN_LAB_WHEN
    # Pre-Lab Canceled: Canceled BEFORE reaching the lab
    # Filter out EDW default 1/1/1900 placeholder dates (> year 2000 required)
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

    # Hourly arrival distributions (Includes lab cancellations since techs had to unpack/scan them)
    hourly_counts = df["arrival_hour"].value_counts().reindex(range(24), fill_value=0)
    hourly_arrival_weights = (hourly_counts / max(hourly_counts.sum(), 1)).round(4).tolist()

    weekday_counts = df[~df["is_weekend"]]["arrival_hour"].value_counts().reindex(range(24), fill_value=0)
    weekend_counts = df[df["is_weekend"]]["arrival_hour"].value_counts().reindex(range(24), fill_value=0)

    weekday_weights = (weekday_counts / max(weekday_counts.sum(), 1)).round(4).tolist()
    weekend_weights = (weekend_counts / max(weekend_counts.sum(), 1)).round(4).tolist()

    # Daily volume calculation reflecting true lab receiving workload
    unique_days = df["IN_LAB_WHEN"].dt.date.nunique()
    daily_volume_mean = int(len(df) / max(unique_days, 1))

    print("daily_volume_mean", daily_volume_mean)
    print("--------------------------------------")
    # print("weekday_counts", weekday_counts)
    # print("weekday_weights", weekday_weights)
    # print("--------------------------------------")
    # print("weekend_counts", weekend_counts)
    # print("weekend_weights", weekend_weights)

    # -------------------------------------------------------------
    # 1B. Accessioning / Central Processing Time Calculation
    # -------------------------------------------------------------
    PROC_TIMESTAMP_COL = 'Time2Accession' 

    if PROC_TIMESTAMP_COL in df.columns:
        df["accession_time_min"] = pd.to_numeric(df[PROC_TIMESTAMP_COL], errors="coerce")
    else:
        df["accession_time_min"] = np.nan

    # Fallback to CULTURE_START_WHEN or CANCEL_WHEN - IN_LAB_WHEN
    if df["accession_time_min"].dropna().empty:
        if "CULTURE_START_WHEN" in df.columns:
            df["accession_time_min"] = (df["CULTURE_START_WHEN"] - df["IN_LAB_WHEN"]).dt.total_seconds() / 60.0
        elif "CANCEL_WHEN" in df.columns:
            # For lab canceled items, accessioning time = CANCEL_WHEN - IN_LAB_WHEN
            df.loc[df["is_lab_canceled"], "accession_time_min"] = (
                (df["CANCEL_WHEN"] - df["IN_LAB_WHEN"]).dt.total_seconds() / 60.0
            )

    # Filter realistic accessioning bounds (0.1 to 120 mins)
    valid_acc = df["accession_time_min"].dropna()
    valid_acc = valid_acc[(valid_acc >= 0.1) & (valid_acc <= 120.0)]

    if not valid_acc.empty:
        # Extract log normal distribution parameters for downstream sim work
        m = float(valid_acc.mean())
        s = float(valid_acc.std())

        # Mathematical conversion to Log-Normal parameters
        if s > 0 and m > 0:
            log_variance = np.log(1 + (s**2 / m**2))
            sigma_val = np.sqrt(log_variance)
            mu_val = np.log(m) - (log_variance / 2)
        else:
            mu_val, sigma_val = np.log(max(m, 0.1)), 0.1

        # Extract with Discrete Categorical (Empirical Binned) Distribution
        counts, bin_edges = np.histogram(valid_acc, bins=200)
        probabilities = counts / max(counts.sum(), 1)

        # Enforce exact 1.0 sum normalization for np.random.choice
        probabilities = probabilities / probabilities.sum()
        bin_probabilities = probabilities.tolist()
        bin_edges = bin_edges.round(3).tolist()
        
        accession_config = {
            "units": "minutes",
            "min_accession_min": round(float(valid_acc.min())),
            "max_accession_min": round(float(valid_acc.quantile(0.99))),
            "mean_accession_min": round(float(valid_acc.mean())),
            "std_accession_min": round(float(valid_acc.std())),
            # --- LOG-NORMAL PARAMETERS ---
            "lognormal_sigma": float(sigma_val),
            "lognormal_mu": float(mu_val),
            # Discrete Categorical Distribution ----
            "bin_probabilities": bin_probabilities,
            "bin_edges": bin_edges
        }

        print(f"\n=== Accessioning SUMMARY: {base_filename} ===")
        print(f"Valid Samples Analyzed: {len(valid_acc):,} / {len(df):,}")
        print(f"Time Units: {accession_config['units']}")
        print(f"Min Accession Time: {accession_config['min_accession_min']} min")
        print(f"Max (99th Percentile): {accession_config['max_accession_min']} min")
        print(f"Mean Accession Time: {accession_config['mean_accession_min']} ± {accession_config['std_accession_min']} min\n")
        print(f"Log-Normal Params -> mu: {mu_val:.4f}, sigma: {sigma_val:.4f}")
    else:
        # Fallback config if no explicit accession timestamp column is present in raw CSV
        print(f"Warning: Column '{PROC_TIMESTAMP_COL}' not found or empty in CSV. Using default accession parameters.")

        default_edges = np.linspace(1.0, 5.0, 11)
        default_probs = np.full(10, 0.1)

        accession_config = {
            "units": "minutes",
            "min_accession_min": 2.0,
            "max_accession_min": 10.0,
            "mean_accession_min": 5.0,
            "std_accession_min": 2.0,
            "lognormal_sigma": 0.7,
            "lognormal_mu": float(np.log(5.0) - (0.7**2 / 2)),
            # Discrete Categorical Distribution ----
            "bin_probabilities": default_probs.tolist(),
            "bin_edges": default_edges.round(3).tolist()
        }

    # -------------------------------------------------------------
    # 2. Extract Positivity Rate & Fit Time-to-Positivity (TTP)
    # -------------------------------------------------------------
    if "Time2Pos_min" in df.columns:
        df["ttp_min_cleaned"] = pd.to_numeric(df["Time2Pos_min"], errors="coerce")
    else:
        df["ttp_min_cleaned"] = np.nan

    # HARD BOUND: 5 Days = 7,200 mins. Allow 7,500 mins for protocol pull buffer.
    # Define max threshold: 5 days = 7,200 mins (7,500 with buffer), 10 days = 15,000 mins
    max_ttp_limit = 7500 if isblood else 15000

    # Build mask components
    # Exclude lab-canceled items from TTP (canceled specimens never generate positive TTP curves)
    not_canceled = ~df["is_lab_canceled"]
    has_positive_ttp = df["ttp_min_cleaned"] > 0
    within_time_bound = df["ttp_min_cleaned"] <= max_ttp_limit

    pos_mask = not_canceled & has_positive_ttp & within_time_bound
    # --- DETAILED DIAGNOSTIC PRINT ---
    print(f"\n--- TTP FILTERING DIAGNOSTICS: {base_filename} ---")
    print(f"Total rows in dataframe:                 {len(df)}")
    print(f"Rows NOT lab-canceled:                   {not_canceled.sum()}")
    print(f"Rows with Time2Pos_min > 0:              {has_positive_ttp.sum()}" )
    print(f"Rows with Time2Pos_min <= {max_ttp_limit}:     {within_time_bound.sum()}")
    print(f"Combined pos_mask matches:               {pos_mask.sum()}")
    print("--------------------------------------------------\n")

    positive_df = df[pos_mask].copy()
    positive_ttps_hrs = positive_df["ttp_min_cleaned"] / 60.0

    # STRICT ERROR HANDLING: Do not allow silent failures or fallback values
    if positive_ttps_hrs.empty:
        raise ValueError(
            f"CRITICAL ERROR: Zero valid positive TTP samples found for '{base_filename}'. "
            f"Inspect raw 'Time2Pos_min' values or cancellation filters."
        )

    total_bottles = len(df)

    print("--------------------------------------")
    print("total_bottles", total_bottles)

    if not positive_ttps_hrs.empty:
        shape, loc, scale = stats.lognorm.fit(positive_ttps_hrs)
        counts, bin_edges = np.histogram(positive_ttps_hrs, bins=100)
        probabilities = counts / max(counts.sum(), 1)
        probabilities = probabilities / probabilities.sum()
        bin_probabilities = probabilities.tolist()
        bin_edges = bin_edges.round(3).tolist()

        ttp_config = {
            "fit_model": "lognorm",
            "units": "hours",
            "params": {
                "shape": round(float(shape), 4),
                "loc": round(float(loc), 4),
                "scale": round(float(scale), 4)
            },
            "min_ttp_hrs": round(float(positive_ttps_hrs.min()), 2),
            "max_ttp_hrs": round(float(positive_ttps_hrs.max()), 2),
            "hourly_weights_weekday": weekday_weights,
            "hourly_weights_weekend": weekend_weights,
            # for Discrete Categorical Distribution sampling:
            "distribution": "binned_categorical",
            "bin_probabilities": bin_probabilities,
            "bin_edges": bin_edges
        }
    else:
        ttp_config = {
            "fit_model": "none",
            "units": "hours",
            "params": {"shape": 0.0, "loc": 0.0, "scale": 0.0},
            "min_ttp_hrs": 0.0,
            "max_ttp_hrs": 0.0,
            "hourly_weights_weekday": weekday_weights,
            "hourly_weights_weekend": weekend_weights,
            "distribution": "none",
            "bin_probabilities": [],
            "bin_edges": []
        }

    print(f"=== ETL SUMMARY ===")
    print(f"Total Records: {total_bottles:,}")
    print(f"Mean Daily Volume: {daily_volume_mean} bottles/day")
    print(f"Fitted LogNorm Params (hrs): {ttp_config.get('params', {})}\n")






    # -------------------------------------------------------------
    # 3. GRAPH 1: Time to Positivity (TTP) Distribution + Fit
    # -------------------------------------------------------------
    plt.figure(figsize=(10, 5))
    
    # Histogram of real TTP data
    ax1 = sns.histplot(
        positive_ttps_hrs, 
        kde=False, 
        stat="density", 
        bins=40, 
        color="#2b5c8f", 
        edgecolor="black", 
        alpha=0.6,
        label="Historical TTP Data"
    )

    # Overlay fitted Log-Normal PDF curve
    x_axis = np.linspace(0, positive_ttps_hrs.max(), 300)
    pdf_fitted = stats.lognorm.pdf(x_axis, s=shape, loc=loc, scale=scale)
    plt.plot(x_axis, pdf_fitted, 'r-', lw=2.5, label=f'Fitted LogNorm PDF (shape={shape:.2f}, scale={scale:.2f})')

    plt.title(f"{base_filename} - Time-to-Positivity (TTP) Distribution", fontsize=14, fontweight="bold")
    plt.ylabel("Density", fontsize=12)
    plt.xlim(0, max( positive_ttps_hrs.max(), 120))
    plt.legend(frameon=True)
    plt.tight_layout()
    
    if save_plots:
        plot1_path = os.path.join(png_dir, f"{base_filename}_TimeToPositive_distribution.png")
        plt.savefig(plot1_path, dpi=300)
        print(f"--> Saved plot: {plot1_path}")
    plt.show()

    # -------------------------------------------------------------
    # 4. GRAPH 2: Hourly Sample Arrivals (Weekday vs Weekend)
    # -------------------------------------------------------------
    # Calculate average arrivals per hour per day type
    hourly_daytype_avg = (
        df.groupby(['day_type', 'arrival_hour', df['IN_LAB_WHEN'].dt.date])
        .size()
        .groupby(['day_type', 'arrival_hour'])
        .mean()
        .reset_index(name='avg_samples')
    )

    plt.figure(figsize=(12, 5))
    
    palette = {"Weekday": "#1f77b4", "Weekend": "#ff7f0e"}
    ax2 = sns.barplot(
        data=hourly_daytype_avg, 
        x="arrival_hour", 
        y="avg_samples", 
        hue="day_type", 
        palette=palette,
        edgecolor="black",
        alpha=0.85
    )

    plt.title(f"{base_filename} - Average Sample Volume Received by Hour", fontsize=14, fontweight="bold")
    plt.xlabel("Hour of Day (00:00 - 23:00)", fontsize=12)
    plt.ylabel("Average Samples Received per Hour", fontsize=12)
    plt.xticks(ticks=range(0, 24), labels=[f"{h:02d}:00" for h in range(0, 24)], rotation=45)
    plt.legend(title="Day Type", frameon=True)
    plt.tight_layout()
    
    if save_plots:
        plot2_path = os.path.join(png_dir, f"{base_filename}_hourly_arrivals_weekday_vs_weekend.png")
        plt.savefig(plot2_path, dpi=300)
        print(f"--> Saved plot: {plot2_path}")
    plt.show()

    # -------------------------------------------------------------
    # 5. GRAPH 3: Cancellation Reasons Bar Graph
    # -------------------------------------------------------------
    if not cancel_counts.empty:
        plt.figure(figsize=(10, 5))
        
        # Take Top 10 most common cancel codes for visual clarity
        top_cancels = cancel_counts.head(10).reset_index()
        top_cancels.columns = ['Cancel_Code', 'Count']

        ax3 = sns.barplot(
            data=top_cancels,
            x="Count",
            y="Cancel_Code",
            palette="Reds_r",
            edgecolor="black"
        )

        cancel_rate_pct = cancellation_metrics["lab_cancel_rate_pct"]
        plt.title(f"{base_filename} - Top Cancel Codes (Total Canceled: {total_lab_canceled:,} | Rate: {cancel_rate_pct}%)", 
                  fontsize=13, fontweight="bold")
        plt.xlabel("Number of Cancelled Samples", fontsize=12)
        plt.ylabel("Cancel Code", fontsize=12)

        # Annotate count values on the ends of bars
        for p in ax3.patches:
            width = p.get_width()
            ax3.annotate(f'{int(width):,}',
                         (width, p.get_y() + p.get_height() / 2.),
                         ha='left', va='center',
                         xytext=(5, 0),
                         textcoords='offset points',
                         fontsize=10)

        plt.tight_layout()
        if save_plots:
            plot3_path = os.path.join(png_dir, f"{base_filename}_cancel_codes_distribution.png")
            plt.savefig(plot3_path, dpi=300)
            print(f"--> Saved plot: {plot3_path}")
        plt.show()

    # -------------------------------------------------------------
    # 4B. GRAPH: Accessioning / Processing Time Distribution
    # -------------------------------------------------------------
    if PROC_TIMESTAMP_COL in df.columns and not valid_acc.empty:
        plt.figure(figsize=(10, 5))
        
        # Plot histogram of valid accession times in minutes
        ax_acc = sns.histplot(
            valid_acc, 
            bins=40, 
            kde=True, 
            color="#2ca02c", 
            edgecolor="black", 
            alpha=0.65
        )

        # Plot vertical lines for mean and 99th percentile
        mean_val = accession_config["mean_accession_min"]
        p99_val = accession_config["max_accession_min"]
        
        plt.axvline(mean_val, color="red", linestyle="--", linewidth=2, label=f"Mean: {mean_val:.1f} min")
        plt.axvline(p99_val, color="darkorange", linestyle=":", linewidth=2, label=f"99th Percentile: {p99_val:.1f} min")

        plt.title(f"{base_filename} - Accessioning Processing Time Distribution", fontsize=14, fontweight="bold")
        plt.xlabel("Accessioning Duration (Minutes)", fontsize=12)
        plt.ylabel("Sample Count", fontsize=12)
        plt.xlim(0, max(p99_val * 1.15, 10))  # Scale X axis nicely around the bulk of data
        plt.legend(frameon=True)
        plt.tight_layout()

        if save_plots:
            plot_acc_path = os.path.join(png_dir, f"{base_filename}_accession_time_distribution.png")
            plt.savefig(plot_acc_path, dpi=300)
            print(f"--> Saved plot: {plot_acc_path}")
        plt.show()

    # -------------------------------------------------------------
    # 5. Export ttp_confi file to a json for my Simulation 
    # -------------------------------------------------------------
    output_data = {
        "daily_volume_mean": daily_volume_mean,
        "hourly_weights_overall": hourly_arrival_weights,
        "hourly_weights_weekday": weekday_weights,
        "hourly_weights_weekend": weekend_weights,
        "cancellation_metrics": cancellation_metrics,
        "ttp_config": ttp_config,
        "accession_time_config": accession_config,
    }

    # Save output to JSON for config/params ingestion
    # csv_dir = os.path.dirname(csv_path)
    # json_dir = os.path.join(csv_dir, "json_clned_data/")
    json_dir = os.path.join(proj_dir, f"json_clned_data_{year}/")

    os.makedirs(json_dir, exist_ok=True)

    json_out_path = os.path.join(json_dir, f"{base_filename}_calibrated_params.json")
    
    with open(json_out_path, "w") as f:
        json.dump(output_data, f, indent=4)

    print(f"--> Extracted configuration saved to: {json_out_path}")


    return hourly_arrival_weights, daily_volume_mean, ttp_config

# ------------------------------------------------------------------------------
# PIPELINE EXECUTION
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    # =========================================================================
    # TOGGLE YEAR HERE ("2024" or "2025")
    # =========================================================================
    TARGET_YEAR = "2024"
    # TARGET_YEAR = "2025"

    BASE_DIR = Path(__file__).resolve().parent.parent
    # print("BASE_DIR == :", BASE_DIR_parent)
    proj_dir = BASE_DIR / "ARUP_data"
    data_dir = proj_dir / f"Cleaned_{TARGET_YEAR}_sql"
    png_dir = proj_dir / f"png_{TARGET_YEAR}_direct"

    # Dynamically build file paths based on TARGET_YEAR
    specimen_files = {
        "BCx": data_dir / f"BCx_{TARGET_YEAR}.csv",
        "BodyFluid": data_dir / f"BodyFluid_{TARGET_YEAR}.csv",
    }

    # Process all files in a single loop and collect metrics in a dict
    results = {}
    for spec_type, csv_path in specimen_files.items():
        if csv_path.exists():
            print(f"\nProcessing {spec_type} from {csv_path.name}...")
            weights, daily_vol, ttp_config = Extract_and_Plot_Metrics(str(csv_path), str(png_dir), proj_dir, year=TARGET_YEAR)
            results[spec_type] = {
                "weights": weights,
                "daily_volume": daily_vol,
                "time2pos": ttp_config
            }
        else:
            print(f"Warning: File not found for {spec_type} at {csv_path}")


