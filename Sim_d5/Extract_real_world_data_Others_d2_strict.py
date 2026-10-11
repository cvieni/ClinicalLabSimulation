# %% 
import os
import json
import numpy as np
import pandas as pd
import scipy.stats as stats
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# Set visual style for publication-ready lab plots
sns.set_theme(style="whitegrid")
plt.rcParams.update({'font.size': 11})

def Extract_and_Plot_Metrics(csv_path, BASE_DIR, proj_dir, year, save_plots=True):
    base_filename = os.path.splitext(os.path.basename(csv_path))[0]
    png_dir = Path(BASE_DIR) / "ARUP_data" / f"png_{year}_direct"
    png_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(csv_path)
    total_raw_records = len(df)

    # -------------------------------------------------------------
    # 0. Datetime Parsing & Strict Cancellation Classification
    # -------------------------------------------------------------
    date_cols = ["IN_LAB_WHEN", "RECEIVE_WHEN", "CULTURE_START_WHEN", "CANCEL_WHEN"]
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Detect cancellation flags
    if "CANCEL_BY" in df.columns:
        has_cancel = (
            (df["CANCEL_BY"].notna())
            & (df["CANCEL_BY"].astype(str).str.strip() != "-1")
            & (df["CANCEL_BY"].astype(str).str.strip() != "")
        )
    elif "CANCEL_CODE" in df.columns:
        has_cancel = df["CANCEL_CODE"].notna() & (df["CANCEL_CODE"].astype(str).str.strip() != "")
    else:
        has_cancel = pd.Series(False, index=df.index)

    # Pre-Lab Canceled: Canceled BEFORE reaching the lab (Drop these)
    if "CANCEL_WHEN" in df.columns:
        pre_lab_mask = has_cancel & (df["IN_LAB_WHEN"].isna() | (df["CANCEL_WHEN"] < df["IN_LAB_WHEN"]))
    else:
        pre_lab_mask = has_cancel & df["IN_LAB_WHEN"].isna()

    # Lab-Processed Canceled: Arrived at lab, then canceled by lab staff (KEEP THESE FOR ACCESSION WORKLOAD)
    lab_cancel_mask = has_cancel & ~pre_lab_mask

    df["is_lab_canceled"] = lab_cancel_mask

    # DROP PRE-LAB CANCELLATIONS ONLY
    df = df[~pre_lab_mask].copy()

    # Drop records without valid lab arrival time
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

    # Create time features
    df['arrival_hour'] = df['IN_LAB_WHEN'].dt.hour
    df['day_of_week'] = df['IN_LAB_WHEN'].dt.day_name()
    df['is_weekend'] = df['IN_LAB_WHEN'].dt.dayofweek >= 5  # 5=Sat, 6=Sun
    df['day_type'] = np.where(df['is_weekend'], 'Weekend', 'Weekday')

    # -------------------------------------------------------------
    # 1. Arrival Weights & Daily Mean Volumes
    # -------------------------------------------------------------
    hourly_counts = df['arrival_hour'].value_counts().reindex(range(24), fill_value=0)
    hourly_arrival_weights = (hourly_counts / max(hourly_counts.sum(), 1)).round(4).tolist()

    weekday_counts = df[~df['is_weekend']]['arrival_hour'].value_counts().reindex(range(24), fill_value=0)
    weekend_counts = df[df['is_weekend']]['arrival_hour'].value_counts().reindex(range(24), fill_value=0)
    
    weekday_weights = (weekday_counts / max(weekday_counts.sum(), 1)).round(4).tolist()
    weekend_weights = (weekend_counts / max(weekend_counts.sum(), 1)).round(4).tolist()

    unique_days = df['IN_LAB_WHEN'].dt.date.nunique()
    daily_volume_mean = int(len(df) / max(unique_days, 1))

    print(f"\n=== ETL SUMMARY: {base_filename} ===")
    print(f"Total Raw Records: {total_raw_records:,}")
    print(f"Pre-Lab Canceled (Dropped): {total_pre_lab:,}")
    print(f"Lab Processed & Canceled (Retained): {total_lab_canceled:,} ({cancellation_metrics['lab_cancel_rate_pct']}%)")
    print(f"Active Workload Samples Analyzed: {len(df):,}")
    print(f"Daily Volume Mean: {daily_volume_mean} samples/day")
    print("--------------------------------------")

    # -------------------------------------------------------------
    # 1B. Accessioning / Central Processing Time Calculation
    # -------------------------------------------------------------
    PROC_TIMESTAMP_COL = 'Time2Accession' 
    valid_acc = pd.Series(dtype=float)

    if PROC_TIMESTAMP_COL in df.columns:
        df['accession_time_min'] = pd.to_numeric(df[PROC_TIMESTAMP_COL], errors='coerce')
    else:
        df['accession_time_min'] = np.nan

    # Fallback calculation if column is empty
    if df['accession_time_min'].dropna().empty:
        if "CULTURE_START_WHEN" in df.columns:
            df["accession_time_min"] = (df["CULTURE_START_WHEN"] - df["IN_LAB_WHEN"]).dt.total_seconds() / 60.0
        elif "CANCEL_WHEN" in df.columns:
            df.loc[df["is_lab_canceled"], "accession_time_min"] = (
                (df["CANCEL_WHEN"] - df["IN_LAB_WHEN"]).dt.total_seconds() / 60.0
            )

    raw_acc = df['accession_time_min'].dropna()
    raw_acc = raw_acc[(raw_acc >= 0.1) & (raw_acc <= 120.0)]

    if not raw_acc.empty:
        # Outlier truncation between 2.5th and 97.5th percentiles
        low_bound = raw_acc.quantile(0.025)
        high_bound = raw_acc.quantile(0.975)
        valid_acc = raw_acc[(raw_acc >= low_bound) & (raw_acc <= high_bound)]

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
                "min_accession_min": round(float(valid_acc.min()), 2),
                "max_accession_min": round(float(valid_acc.quantile(0.99)), 2),
                "mean_accession_min": round(float(valid_acc.mean()), 2),
                "std_accession_min": round(float(valid_acc.std()), 2),
                "lognormal_sigma": float(sigma_val),
                "lognormal_mu": float(mu_val),
                "bin_probabilities": probabilities.tolist(),
                "bin_edges": bin_edges.round(3).tolist()
            }

            print(f"=== Accessioning SUMMARY: {base_filename} ===")
            print(f"Valid Samples Analyzed: {len(valid_acc):,} / {len(df):,}")
            print(f"Mean Accession Time: {accession_config['mean_accession_min']} ± {accession_config['std_accession_min']} min")
            print(f"Log-Normal Params -> mu: {mu_val:.4f}, sigma: {sigma_val:.4f}\n")
        else:
            accession_config = {}
    else:
        print(f"Warning: Column '{PROC_TIMESTAMP_COL}' missing/empty. Using fallback defaults.")
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
            "bin_probabilities": default_probs.tolist(),
            "bin_edges": default_edges.round(3).tolist()
        }

    # -------------------------------------------------------------
    # 2. GRAPH 1: Hourly Sample Arrivals (Weekday vs Weekend)
    # -------------------------------------------------------------
    hourly_daytype_avg = (
        df.groupby(['day_type', 'arrival_hour', df['IN_LAB_WHEN'].dt.date])
        .size()
        .groupby(['day_type', 'arrival_hour'])
        .mean()
        .reset_index(name='avg_samples')
    )

    plt.figure(figsize=(12, 5))
    palette = {"Weekday": "#1f77b4", "Weekend": "#ff7f0e"}
    sns.barplot(
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
        plot_path = png_dir / f"{base_filename}_hourly_arrivals_weekday_vs_weekend.png"
        plt.savefig(plot_path, dpi=300)
        print(f"--> Saved plot: {plot_path}")
    plt.close()

    # -------------------------------------------------------------
    # 3. GRAPH 2: Cancellation Reasons Bar Graph
    # -------------------------------------------------------------
    if not cancel_counts.empty:
        plt.figure(figsize=(10, 5))
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

        for p in ax3.patches:
            width = p.get_width()
            ax3.annotate(
                f'{int(width):,}',
                (width, p.get_y() + p.get_height() / 2.),
                ha='left', va='center',
                xytext=(5, 0),
                textcoords='offset points',
                fontsize=10
            )

        plt.tight_layout()
        if save_plots:
            plot_path = png_dir / f"{base_filename}_cancel_codes_distribution.png"
            plt.savefig(plot_path, dpi=300)
            print(f"--> Saved plot: {plot_path}")
        plt.close()

    # -------------------------------------------------------------
    # 4. GRAPH 3: Accessioning / Processing Time Distribution
    # -------------------------------------------------------------
    if not valid_acc.empty:
        plt.figure(figsize=(10, 5))
        sns.histplot(
            valid_acc, 
            bins=40, 
            kde=True, 
            color="#2ca02c", 
            edgecolor="black", 
            alpha=0.65
        )

        mean_val = accession_config["mean_accession_min"]
        p99_val = accession_config["max_accession_min"]
        
        plt.axvline(mean_val, color="red", linestyle="--", linewidth=2, label=f"Mean: {mean_val:.1f} min")
        plt.axvline(p99_val, color="darkorange", linestyle=":", linewidth=2, label=f"99th Percentile: {p99_val:.1f} min")

        plt.title(f"{base_filename} - Accessioning Processing Time Distribution", fontsize=14, fontweight="bold")
        plt.xlabel("Accessioning Duration (Minutes)", fontsize=12)
        plt.ylabel("Sample Count", fontsize=12)
        plt.xlim(0, max(p99_val * 1.15, 10))
        plt.legend(frameon=True)
        plt.tight_layout()

        if save_plots:
            plot_path = png_dir / f"{base_filename}_accession_time_distribution.png"
            plt.savefig(plot_path, dpi=300)
            print(f"--> Saved plot: {plot_path}")
        plt.close()

    # -------------------------------------------------------------
    # 5. Export Calibrated Config to JSON for Simulation
    # -------------------------------------------------------------
    output_data = {
        "daily_volume_mean": daily_volume_mean,
        "hourly_weights_overall": hourly_arrival_weights,
        "hourly_weights_weekday": weekday_weights,
        "hourly_weights_weekend": weekend_weights,
        "cancellation_metrics": cancellation_metrics,
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


    return hourly_arrival_weights, daily_volume_mean

# ------------------------------------------------------------------------------
# PIPELINE EXECUTION
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    # =========================================================================
    # TOGGLE YEAR HERE ("2024" or "2025")
    # =========================================================================
    # TARGET_YEAR = "2024"
    TARGET_YEAR = "2025"

    BASE_DIR = Path(__file__).resolve().parent.parent
    proj_dir = BASE_DIR / "ARUP_data"
    data_dir = proj_dir / f"Cleaned_{TARGET_YEAR}_sql"

    print("BASE_DIR:", BASE_DIR)
    print("data_dir:", data_dir)

    # Unique dictionary mapping for non-automated specimen files
    specimen_files = {
        "Bone": data_dir / f"Bone_{TARGET_YEAR}.csv",
        "Urine_Inv": data_dir / f"InvUrine_{TARGET_YEAR}.csv",
        "Urine_Inv_UofU": data_dir / f"Inv_Urine_UofU_{TARGET_YEAR}.csv",
        "Urine_NonInv": data_dir / f"NonInv_Urine_{TARGET_YEAR}.csv",
        "Urine_NonInv_UofU": data_dir / f"NonInv_Urine_UofU_{TARGET_YEAR}.csv",
        "Resp_NonCF": data_dir / f"Respiratory_NonCF_{TARGET_YEAR}.csv",
        "Resp_CF": data_dir / f"Respiratory_CF_{TARGET_YEAR}.csv",
        "Stool": data_dir / f"Stool_{TARGET_YEAR}.csv",
        "Tissue_genital": data_dir / f"Tiss_genital_{TARGET_YEAR}.csv",
        "Tissue_FNA": data_dir / f"Tiss_FNA_{TARGET_YEAR}.csv",
        "Tissue_other": data_dir / f"TissueCleaned_{TARGET_YEAR}.csv",
        "Wound_genital": data_dir / f"Wound_genital_{TARGET_YEAR}.csv",
        "Wound_other": data_dir / f"Wound_Cleaned_{TARGET_YEAR}.csv",
    }

    results = {}
    for spec_type, csv_path in specimen_files.items():
        if csv_path.exists():
            print(f"\nProcessing {spec_type} from {csv_path.name}...")
            weights, daily_vol = Extract_and_Plot_Metrics(str(csv_path), BASE_DIR, proj_dir, save_plots=True,  year=TARGET_YEAR)
            results[spec_type] = {
                "weights": weights,
                "daily_volume": daily_vol,
            }
        else:
            print(f"Warning: File not found for {spec_type} at {csv_path}")