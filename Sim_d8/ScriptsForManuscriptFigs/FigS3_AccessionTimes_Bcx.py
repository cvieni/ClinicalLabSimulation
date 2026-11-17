# Extract_real_world_data_BCx_d2.py
import os
import pandas as pd
import numpy as np
import scipy.stats as stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# Set visual style for publication-ready lab plots
sns.set_theme(style="whitegrid")
plt.rcParams.update({
    "font.size": 11,
    "xtick.bottom": True,
    "ytick.left": True,
    "xtick.major.size": 4,
    "ytick.major.size": 4,
})

# =========================================================== SETTINGS (edit these) ===========================================================
OUTPUT_DIR = Path("manuscript_png/FigS3_AccessTime_Bcx")
DPI = 300
PNG_WIDTH = 10.0     # inches
PNG_HEIGHT = 5.0     # inches
BARE = False                                 # True: the unlabelled version also loses the legend and in-plot text

figure_margin_size = 0.0
set_background_transparent = True

# =========================================================== SETTINGS (edit these) ===========================================================

def save_labelled_and_unlabelled(fig, out_dir: Path, stem: str, dpi: int = 300):
    """Save <stem>_labelled.png and <stem>_unlabelled.png on an identical canvas."""
    out_dir.mkdir(parents=True, exist_ok=True)
    labelled_path = out_dir / f"{stem}_labelled.png"
    unlabelled_path = out_dir / f"{stem}_unlabelled.png"

    # 1. Save full labelled version with transparent background and zero margin
    fig.savefig(
        labelled_path, 
        dpi=dpi, 
        transparent=set_background_transparent,
        facecolor="none" if set_background_transparent else "white",
        edgecolor="none",
        bbox_inches="tight" if figure_margin_size == 0.0 else None,
        pad_inches=0.0
    )

    # 2. Strip titles, axis titles, tick value labels, legends, and text annotations (keep tick marks)
    for ax in fig.axes:
        ax.set_title("")
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(
            which="both",
            bottom=True, left=True,
            labelbottom=False, labelleft=False, labelright=False, labeltop=False,
        )
        if ax.get_legend():
            ax.get_legend().remove()
        for txt in ax.texts:
            txt.set_visible(False)

    for lg in list(fig.legends):
        lg.remove()
    if fig._suptitle is not None:
        fig._suptitle.set_visible(False)

    # 3. Save unlabelled version with transparent background and zero margin
    fig.savefig(
        unlabelled_path, 
        dpi=dpi, 
        transparent=set_background_transparent,
        facecolor="none" if set_background_transparent else "white",
        edgecolor="none",
        bbox_inches="tight" if figure_margin_size == 0.0 else None,
        pad_inches=0.0
    )
    plt.close(fig)
    print(f"--> Saved: {labelled_path} & {unlabelled_path}")


def Extract_and_Plot_Metrics(csv_path, out_dir, year, save_plots=True):
    base_filename = os.path.splitext(os.path.basename(csv_path))[0]
    isblood = "bcx" in base_filename.lower()

    df = pd.read_csv(csv_path)
    total_raw_records = len(df)
    print(f"\n================ ROW COUNT AUDIT: {base_filename} ================")
    print(f"1. Raw CSV total rows:                      {len(df):,}")

    # Convert timestamps
    date_cols = ["IN_LAB_WHEN", "RECEIVE_WHEN", "CULTURE_START_WHEN", "CANCEL_WHEN", "PERF_WHEN", "RPT_WHEN", "COMPLETE_WHEN"]
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

    if ref_cancel_col in df.columns:
        valid_ref_date = (df[ref_cancel_col].notna()) & (df[ref_cancel_col] > pd.Timestamp("2000-01-01"))
        pre_lab_mask = has_cancel & (df["IN_LAB_WHEN"].isna() | (valid_ref_date & (df[ref_cancel_col] < df["IN_LAB_WHEN"])))
        earlier_cancel = has_cancel & df["IN_LAB_WHEN"].notna() & valid_ref_date & (df[ref_cancel_col] < df["IN_LAB_WHEN"])
        print(f"4. Rows where {ref_cancel_col} < IN_LAB_WHEN:    {earlier_cancel.sum():,}")
    else:
        pre_lab_mask = has_cancel & df["IN_LAB_WHEN"].isna()

    lab_cancel_mask = has_cancel & ~pre_lab_mask
    df["is_lab_canceled"] = lab_cancel_mask

    df = df[~pre_lab_mask].copy()
    print(f"5. Rows remaining after pre-lab drop:       {len(df):,}")

    df = df.dropna(subset=["IN_LAB_WHEN"]).copy()

    # -------------------------------------------------------------
    # 1. ARRIVAL WEIGHTS & DAILY VOLUMES (Includes Lab-Canceled Workload)
    # -------------------------------------------------------------
    df["arrival_hour"] = df["IN_LAB_WHEN"].dt.hour
    df["is_weekend"] = df["IN_LAB_WHEN"].dt.dayofweek >= 5
    df["day_type"] = np.where(df["is_weekend"], "Weekend", "Weekday")

    hourly_counts = df["arrival_hour"].value_counts().reindex(range(24), fill_value=0)
    hourly_arrival_weights = (hourly_counts / max(hourly_counts.sum(), 1)).round(4).tolist()

    calendar_days = 366 if (int(year) % 4 == 0 and (int(year) % 100 != 0 or int(year) % 400 == 0)) else 365
    daily_volume_mean = round(len(df) / calendar_days, 2)

    # -------------------------------------------------------------
    # 1B. Accessioning / Central Processing Time Calculation
    # -------------------------------------------------------------
    PROC_TIMESTAMP_COL = "Time2Accession"

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
        accession_config = {
            "max_accession_min": round(float(valid_acc.quantile(0.99))),
            "mean_accession_min": round(float(valid_acc.mean())),
        }
    else:
        accession_config = {
            "max_accession_min": 10.0,
            "mean_accession_min": 5.0,
        }

    # -------------------------------------------------------------
    # 2. Extract Positivity Rate & Fit Time-to-Positivity (TTP)
    # -------------------------------------------------------------
    if "Time2Pos_min" in df.columns:
        df["ttp_min_cleaned"] = pd.to_numeric(df["Time2Pos_min"], errors="coerce")
    else:
        df["ttp_min_cleaned"] = np.nan

    max_ttp_limit = 7500 if isblood else 15000
    pos_mask = (~df["is_lab_canceled"]) & (df["ttp_min_cleaned"] > 0) & (df["ttp_min_cleaned"] <= max_ttp_limit)
    positive_ttps_hrs = df.loc[pos_mask, "ttp_min_cleaned"] / 60.0

    if positive_ttps_hrs.empty:
        raise ValueError(f"CRITICAL ERROR: Zero valid positive TTP samples found for '{base_filename}'.")

    shape, loc, scale = stats.lognorm.fit(positive_ttps_hrs)

    fig_s3_dir = Path(out_dir)

    # -------------------------------------------------------------
    # 3. GRAPH 1: Time to Positivity (TTP) Distribution + Fit (Percentage)
    # -------------------------------------------------------------
    fig1, ax1 = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
    sns.histplot(
        positive_ttps_hrs,
        kde=False,
        stat="probability",
        bins=40,
        color="#2b5c8f",
        edgecolor="black",
        alpha=0.6,
        label="Historical TTP Data",
        ax=ax1,
    )

    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: "{:,.1f}%".format(y * 100)))

    x_axis = np.linspace(0, positive_ttps_hrs.max(), 300)
    pdf_fitted = stats.lognorm.pdf(x_axis, s=shape, loc=loc, scale=scale)
    bin_width = positive_ttps_hrs.max() / 40
    ax1.plot(x_axis, pdf_fitted * bin_width, "r-", lw=2.5, label=f"Fitted LogNorm (shape={shape:.2f}, scale={scale:.2f})")

    ax1.set_title(f"{base_filename} Time-to-Positivity (TTP) Distribution", fontsize=14, fontweight="bold")
    ax1.set_ylabel("Percentage of Positive Samples (%)", fontsize=12)
    ax1.set_xlabel("Time to Positivity (Hours)", fontsize=12)
    ax1.set_xlim(0, max(positive_ttps_hrs.max(), 120))
    ax1.legend(frameon=True)
    fig1.tight_layout()

    if save_plots:
        save_labelled_and_unlabelled(fig1, fig_s3_dir, f"{base_filename}_TimeToPositive_distribution", dpi=DPI)
    else:
        plt.close(fig1)

    # -------------------------------------------------------------
    # 4. GRAPH 2: Hourly Sample Arrivals (Weekday vs Weekend as Percentage Share)
    # -------------------------------------------------------------
    hourly_daytype_avg = (
        df.groupby(["day_type", "arrival_hour", df["IN_LAB_WHEN"].dt.date])
        .size()
        .groupby(["day_type", "arrival_hour"])
        .mean()
        .reset_index(name="avg_samples")
    )
    hourly_daytype_avg["pct_share"] = hourly_daytype_avg.groupby("day_type")["avg_samples"].transform(lambda x: (x / x.sum()) * 100)

    fig2, ax2 = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
    palette = {"Weekday": "#1f77b4", "Weekend": "#ff7f0e"}
    sns.barplot(
        data=hourly_daytype_avg,
        x="arrival_hour",
        y="pct_share",
        hue="day_type",
        palette=palette,
        edgecolor="black",
        alpha=0.85,
        ax=ax2,
    )

    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: "{:.1f}%".format(y)))
    ax2.set_title(f"{base_filename} Average Sample Arrival Share by Hour", fontsize=14, fontweight="bold")
    ax2.set_xlabel("Hour of Day (00:00 - 23:00)", fontsize=12)
    ax2.set_ylabel("Percentage Share of Daily Arrivals (%)", fontsize=12)
    ax2.set_xticks(ticks=range(0, 24))
    ax2.set_xticklabels([f"{h:02d}:00" for h in range(0, 24)], rotation=45)
    ax2.legend(title="Day Type", frameon=True)
    fig2.tight_layout()

    if save_plots:
        save_labelled_and_unlabelled(fig2, fig_s3_dir, f"{base_filename}_hourly_arrivals_weekday_vs_weekend", dpi=DPI)
    else:
        plt.close(fig2)

    # -------------------------------------------------------------
    # 4B. GRAPH: Accessioning / Processing Time Distribution (Percentage)
    # -------------------------------------------------------------
    if PROC_TIMESTAMP_COL in df.columns and not valid_acc.empty:
        fig3, ax_acc = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
        sns.histplot(
            valid_acc,
            bins=40,
            stat="percent",
            color="#2ca02c",
            edgecolor="black",
            alpha=0.65,
            ax=ax_acc,
        )

        mean_val = accession_config["mean_accession_min"]
        p99_val = accession_config["max_accession_min"]

        ax_acc.axvline(mean_val, color="red", linestyle="--", linewidth=2, label=f"Mean: {mean_val:.1f} min")
        ax_acc.axvline(p99_val, color="darkorange", linestyle=":", linewidth=2, label=f"99th Percentile: {p99_val:.1f} min")

        ax_acc.set_title(f"{base_filename} Accessioning Processing Time Distribution", fontsize=14, fontweight="bold")
        ax_acc.set_xlabel("Accessioning Duration (Minutes)", fontsize=12)
        ax_acc.set_ylabel("Percentage of Samples (%)", fontsize=12)
        ax_acc.set_xlim(0, max(p99_val * 1.15, 10))
        ax_acc.legend(frameon=True)
        fig3.tight_layout()

        if save_plots:
            save_labelled_and_unlabelled(fig3, fig_s3_dir, f"{base_filename}_accession_time_distribution", dpi=DPI)
        else:
            plt.close(fig3)

    return hourly_arrival_weights, daily_volume_mean


# ------------------------------------------------------------------------------
# PIPELINE EXECUTION
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    TARGET_YEAR = "2025"

    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    SIM_DIR = Path(__file__).resolve().parent.parent
    proj_dir = BASE_DIR / "ARUP_data"
    data_dir = proj_dir / f"Cleaned_{TARGET_YEAR}_sql"
    out_dir = SIM_DIR / OUTPUT_DIR

    specimen_files = {
        "BCx": data_dir / f"BCx_{TARGET_YEAR}.csv",
        "BodyFluid": data_dir / f"BodyFluid_{TARGET_YEAR}.csv",
    }

    results = {}
    for spec_type, csv_path in specimen_files.items():
        if csv_path.exists():
            print(f"\nProcessing {spec_type} from {csv_path.name}...")
            weights, daily_vol = Extract_and_Plot_Metrics(str(csv_path), out_dir, year=TARGET_YEAR)
            results[spec_type] = {
                "weights": weights,
                "daily_volume": daily_vol,
            }
        else:
            print(f"Warning: File not found for {spec_type} at {csv_path}")