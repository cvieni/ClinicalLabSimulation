# %% 
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

def Extract_and_Plot_Metrics(csv_path, save_plots=True):
    base_filename = os.path.splitext(os.path.basename(csv_path))[0]
    if "bcx" in base_filename.lower():
        isblood = True 
    else:
        isblood = False

    df = pd.read_csv(csv_path)

    # -------------------------------------------------------------
    # 0. Datetime Parsing & Fixes
    # -------------------------------------------------------------
    # Identify culture arrival timestamp column (handles partial SQL column headers)
    df['IN_LAB_WHEN'] = pd.to_datetime(df['IN_LAB_WHEN'])

    # Extract hour of the day (0-23)
    df['arrival_hour'] = df['IN_LAB_WHEN'].dt.hour

    # Count arrivals per hour across all days
    hourly_counts = df['arrival_hour'].value_counts().reindex(range(24), fill_value=0)

    # Normalize into a 24-element probability distribution array (sums to 1.0)
    hourly_arrival_weights = (hourly_counts / hourly_counts.sum()).round(4).tolist()

    # Calculate average daily volume for BCx
    unique_days = df['IN_LAB_WHEN'].dt.date.nunique()
    daily_volume_mean = int(len(df) / max(unique_days, 1))
    
    # Drop rows where arrival timestamp is missing
    df = df.dropna(subset=['IN_LAB_WHEN']).copy()

    # Create time features
    df['arrival_hour'] = df['IN_LAB_WHEN'].dt.hour
    df['day_of_week'] = df['IN_LAB_WHEN'].dt.day_name()
    df['is_weekend'] = df['IN_LAB_WHEN'].dt.dayofweek >= 5  # 5=Sat, 6=Sun
    df['day_type'] = np.where(df['is_weekend'], 'Weekend', 'Weekday')

    # print("df arrival struct", df.head())


    # -------------------------------------------------------------
    # 1. Arrival Weights & Daily Mean Volumes
    # -------------------------------------------------------------
    # Calculate overall hourly arrival weights
    hourly_counts = df['arrival_hour'].value_counts().reindex(range(24), fill_value=0)
    hourly_arrival_weights = (hourly_counts / hourly_counts.sum()).round(4).tolist()

    # Separate weights by Weekday vs. Weekend
    weekday_counts = df[~df['is_weekend']]['arrival_hour'].value_counts().reindex(range(24), fill_value=0)
    weekend_counts = df[df['is_weekend']]['arrival_hour'].value_counts().reindex(range(24), fill_value=0)
    
    weekday_weights = (weekday_counts / max(weekday_counts.sum(), 1)).round(4).tolist()
    weekend_weights = (weekend_counts / max(weekend_counts.sum(), 1)).round(4).tolist()

    # Average Daily Volume calculations
    unique_days = df['IN_LAB_WHEN'].dt.date.nunique()
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
    accession_config = {}
    valid_acc = pd.Series(dtype=float)  # Scoped for downstream plotting

    if PROC_TIMESTAMP_COL in df.columns:
        # Convert column directly to numeric minutes (handling strings/blanks safely)
        df['accession_time_min'] = pd.to_numeric(df[PROC_TIMESTAMP_COL], errors='coerce')
        
        # Filter realistic processing bounds (e.g. between 0.1 and 120 minutes)
        valid_acc = df['accession_time_min'].dropna()
        valid_acc = valid_acc[(valid_acc >= 0.1) & (valid_acc <= 120)]
        
        if not valid_acc.empty:
            # -----------------------------------------------------
            # Extract log normal distribution parameters for downstream sim work ------------------
            # -----------------------------------------------------
            m = float(valid_acc.mean())
            s = float(valid_acc.std())

            # Mathematical conversion to Log-Normal parameters
            # (Handles edge case if std is 0)
            if s > 0 and m > 0:
                log_variance = np.log(1 + (s**2 / m**2))
                sigma_val = np.sqrt(log_variance)
                mu_val = np.log(m) - (log_variance / 2)
            else:
                mu_val, sigma_val = np.log(m), 0.1
            # -----------------------------------------------------
            # -----------------------------------------------------

            # -----------------------------------------------------
            # -----------------------------------------------------
            # Extract with Discrete Categorical (Empirical Binned) Distribution
            # Convert historical data into 200 bins up to max time
            counts, bin_edges = np.histogram(valid_acc, bins=200)

            # Calculate percentages (sums to 1.0)
            probabilities = counts / counts.sum()
            # Enforce exact 1.0 sum normalization for np.random.choice
            probabilities = probabilities / probabilities.sum()
            bin_probabilities = probabilities.tolist()
            bin_edges = bin_edges.round(3).tolist()

            # -----------------------------------------------------
            # -----------------------------------------------------

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
            print(f"Mean Accession Time: {accession_config['mean_accession_min']} ± {accession_config['std_accession_min']} min\n"),
            print(f"Mean Accession Time: {accession_config['mean_accession_min']} ± {accession_config['std_accession_min']} min\n")
            print(f"Log-Normal Params -> mu: {mu_val:.4f}, sigma: {sigma_val:.4f}")
        else:
            raw_series = pd.to_numeric(df[PROC_TIMESTAMP_COL], errors='coerce').dropna()
            print(f"\nWarning: '{PROC_TIMESTAMP_COL}' exists, but no values were between 0.1 and 120 min.")
            if not raw_series.empty:
                print(f"Raw minute stats -> Min: {raw_series.min()}, Max: {raw_series.max()}, Mean: {raw_series.mean():.2f}")
    else:
        # Fallback config if no explicit accession timestamp column is present in raw CSV
        print(f"Warning: Column '{PROC_TIMESTAMP_COL}' not found in CSV. Using default accession parameters.")
                # Fallback config if no explicit accession timestamp column is present in raw CSV
        print(f"Warning: Column '{PROC_TIMESTAMP_COL}' not found in CSV. Using default accession parameters.")

        # 10 default uniform bins between 1.0 and 5.0 minutes
        default_edges = np.linspace(1.0, 5.0, 11)
        default_probs = np.full(10, 0.1)

        accession_config = {
            "units": "minutes",
            "min_accession_min": 2.0,
            "max_accession_min": 10.0,
            "mean_accession_min": 5.0,
            "std_accession_min": 2.0,
            "lognormal_sigma": 0.7,
            "lognormal_mu": np.log(mean_time) - (sigma**2 / 2),
            # Discrete Categorical Distribution ----
            "bin_probabilities": default_probs.tolist(),
            "bin_edges": default_edges.round(3).tolist()
        }

    # -------------------------------------------------------------
    # 2. Extract Positivity Rate & Fit Time-to-Positivity (TTP)
    # -------------------------------------------------------------
    # Cultures are held for 5 days. I don't know if the machine is a true @ 5 days then the bottle is removed
    # but 5 days = 7200 minutes, ill be a little generous and give 7500 min.
    if isblood is True:
        pos_mask = (df['Time2Pos_min'] > 0) & (df['Time2Pos_min'] <= 7500)
    else:
        # Per SOP body fluids held for 5 days (shoulders held for 10 days)
        pos_mask = (df['Time2Pos_min'] > 0) & (df['Time2Pos_min'] <= 2*7500)
    positive_df = df[pos_mask].copy()

    # Convert TTP minutes to hours for readable modeling & plotting
    positive_ttps_hrs = positive_df['Time2Pos_min'] / 60.0

    total_bottles = len(df)
    # positive_count = len(positive_df)
    # positivity_rate = round(positive_count / total_bottles, 4)

    print("--------------------------------------")
    print("total_bottles", total_bottles)
    # print("positive_count", positive_count)
    # print("positivity_rate", positivity_rate)

    # Fit Log-Normal distribution in hours
    shape, loc, scale = stats.lognorm.fit(positive_ttps_hrs)

    # Bin-probability sampling / Discrete Categorical Distribution
    # Convert historical data into 5-minute bins up to max time
    counts, bin_edges = np.histogram(positive_ttps_hrs, bins=100)

    # Calculate percentages (sums to 1.0)
    probabilities = counts / counts.sum()
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

    print(f"=== ETL SUMMARY ===")
    print(f"Total Records: {total_bottles:,}")
    print(f"Mean Daily Volume: {daily_volume_mean} bottles/day")
    print(f"Fitted LogNorm Params (hrs): {ttp_config['params']}\n")


    # -------------------------------------------------------------
    # 1C. Cancellation Metrics & Reason Distribution
    # -------------------------------------------------------------
    # Filter canceled tests: CANCEL_BY != -1
    if 'CANCEL_BY' in df.columns:
        cancelled_df = df[df['CANCEL_BY'] != -1].copy()
    else:
        print("Warning: Column 'CANCEL_BY' not found in CSV. Defaulting to empty canceled set.")
        cancelled_df = pd.DataFrame()


    total_samples = len(df)
    total_cancelled = len(cancelled_df)
    cancel_rate_percent = round((total_cancelled / max(total_samples, 1)) * 100, 2)

    # Distribution by cancel_code
    if not cancelled_df.empty and 'CANCEL_CODE' in cancelled_df.columns:
        # Fill NA cancel codes with 'Unspecified' to prevent grouping drops
        cancel_counts = cancelled_df['CANCEL_CODE'].fillna('Unspecified').value_counts()
    else:
        cancel_counts = pd.Series(dtype=int)

    cancellation_metrics = {
        "total_samples": total_samples,
        "total_cancelled": total_cancelled,
        "cancel_rate_percent": cancel_rate_percent,
        "cancel_code_counts": cancel_counts.to_dict()
    }

    print(f"\n=== ETL SUMMARY: {base_filename} ===")
    print(f"Total Records: {total_samples:,}")
    print(f"Mean Daily Volume: {daily_volume_mean} samples/day")
    print(f"Total Cancelled (CANCEL_BY != -1): {total_cancelled:,} ({cancel_rate_percent}%)")
    if not cancel_counts.empty:
        print(f"Top Cancel Code: {cancel_counts.index[0]} ({cancel_counts.iloc[0]} occurrences)\n")





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
        plot1_path = os.path.join("ARUP_data/png_direct", f"{base_filename}_TimeToPositive_distribution.png")
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
        plot2_path = os.path.join("ARUP_data/png_direct", f"{base_filename}_hourly_arrivals_weekday_vs_weekend.png")
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

        plt.title(f"{base_filename} - Top Cancel Codes (Total Canceled: {total_cancelled:,} | Rate: {cancel_rate_percent}%)", 
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
            plot3_path = os.path.join("ARUP_data/png_direct", f"{base_filename}_cancel_codes_distribution.png")
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
            plot_acc_path = os.path.join("ARUP_data/png_direct", f"{base_filename}_accession_time_distribution.png")
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
    csv_dir = os.path.dirname(csv_path)
    json_dir = os.path.join(csv_dir, "json_clned_data/")
    
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
    BASE_DIR = Path(__file__).resolve().parent
    data_dir = BASE_DIR / "ARUP_data"

    # Define files and their descriptive labels/keys
    specimen_files = {
        "BCx": data_dir / "BCx_2024.csv",
        "BodyFluid": data_dir / "BodyFluid_2024.csv",
    }

    # Process all files in a single loop and collect metrics in a dict
    results = {}
    for spec_type, csv_path in specimen_files.items():
        if csv_path.exists():
            print(f"\nProcessing {spec_type} from {csv_path.name}...")
            weights, daily_vol, ttp_config = Extract_and_Plot_Metrics(str(csv_path))
            results[spec_type] = {
                "weights": weights,
                "daily_volume": daily_vol,
                "time2pos": ttp_config
            }
        else:
            print(f"Warning: File not found for {spec_type} at {csv_path}")


# %%
