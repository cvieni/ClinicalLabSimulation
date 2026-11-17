# %%
import os
import numpy as np
import pandas as pd
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
OUTPUT_DIR = Path("manuscript_png/FigS4_AccessTime_Others")
PNG_WIDTH = 10.0     # inches
PNG_HEIGHT = 5.0     # inches
DPI = 300

figure_margin_size = 0.0
set_background_transparent = True

# ==============================================================================================================================================


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


def Process_and_Plot_Group(df, base_filename, out_dir, year, save_plots=True):
    png_dir = Path(out_dir)
    png_dir.mkdir(parents=True, exist_ok=True)

    total_raw_records = len(df)

    # -------------------------------------------------------------
    # 0. Datetime Parsing & Strict Cancellation Classification
    # -------------------------------------------------------------
    date_cols = ["IN_LAB_WHEN", "RECEIVE_WHEN", "CULTURE_START_WHEN", "CANCEL_WHEN"]
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    NO_CANCEL = {"", "-1", "-1.0", "0", "0.0", "nan", "none", "null", "<na>", "nat"}
    if "CANCEL_BY" in df.columns:
        has_cancel = df["CANCEL_BY"].notna() & ~df["CANCEL_BY"].astype(str).str.strip().str.lower().isin(NO_CANCEL)
    elif "CANCEL_CODE" in df.columns:
        has_cancel = df["CANCEL_CODE"].notna() & ~df["CANCEL_CODE"].astype(str).str.strip().str.lower().isin(NO_CANCEL)
    else:
        has_cancel = pd.Series(False, index=df.index)

    if "CANCEL_WHEN" in df.columns:
        valid_cw = df["CANCEL_WHEN"].notna() & (df["CANCEL_WHEN"] > pd.Timestamp("2000-01-01"))
        pre_lab_mask = has_cancel & (df["IN_LAB_WHEN"].isna() | (valid_cw & (df["CANCEL_WHEN"] < df["IN_LAB_WHEN"])))
    else:
        pre_lab_mask = has_cancel & df["IN_LAB_WHEN"].isna()

    lab_cancel_mask = has_cancel & ~pre_lab_mask
    df["is_lab_canceled"] = lab_cancel_mask

    df = df[~pre_lab_mask].copy()
    df = df.dropna(subset=["IN_LAB_WHEN"]).copy()

    total_pre_lab = pre_lab_mask.sum()
    total_lab_canceled = lab_cancel_mask.sum()
    cancel_counts = (
        df[df["is_lab_canceled"]]["CANCEL_CODE"].fillna("Unspecified").value_counts()
        if "CANCEL_CODE" in df.columns
        else pd.Series(dtype=int)
    )

    cancellation_metrics = {
        "total_raw_records": total_raw_records,
        "pre_lab_canceled": int(total_pre_lab),
        "lab_processed_then_canceled": int(total_lab_canceled),
        "lab_cancel_rate_pct": round((total_lab_canceled / max(len(df), 1)) * 100, 2),
        "cancel_code_counts": cancel_counts.to_dict(),
    }

    # Create time features
    df["arrival_hour"] = df["IN_LAB_WHEN"].dt.hour
    df["day_of_week"] = df["IN_LAB_WHEN"].dt.day_name()
    df["is_weekend"] = df["IN_LAB_WHEN"].dt.dayofweek >= 5
    df["day_type"] = np.where(df["is_weekend"], "Weekend", "Weekday")

    # -------------------------------------------------------------
    # 1. Arrival Weights & Daily Mean Volumes
    # -------------------------------------------------------------
    hourly_counts = df["arrival_hour"].value_counts().reindex(range(24), fill_value=0)
    hourly_arrival_weights = (hourly_counts / max(hourly_counts.sum(), 1)).round(4).tolist()

    calendar_days = 366 if (int(year) % 4 == 0 and (int(year) % 100 != 0 or int(year) % 400 == 0)) else 365
    daily_volume_mean = round(len(df) / calendar_days, 2)

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
    PROC_TIMESTAMP_COL = "Time2Accession"
    valid_acc = pd.Series(dtype=float)

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

    raw_acc = df["accession_time_min"].dropna()
    raw_acc = raw_acc[(raw_acc >= 0.1) & (raw_acc <= 120.0)]

    if not raw_acc.empty:
        low_bound = raw_acc.quantile(0.025)
        high_bound = raw_acc.quantile(0.975)
        valid_acc = raw_acc[(raw_acc >= low_bound) & (raw_acc <= high_bound)]

        if not valid_acc.empty:
            mean_val = float(valid_acc.mean())
            p99_val = float(valid_acc.quantile(0.99))
        else:
            mean_val, p99_val = 5.0, 10.0
    else:
        mean_val, p99_val = 5.0, 10.0

    # -------------------------------------------------------------
    # 2. GRAPH 1: Hourly Sample Arrivals (Weekday vs Weekend as Percentage Share)
    # -------------------------------------------------------------
    hourly_daytype_avg = (
        df.groupby(["day_type", "arrival_hour", df["IN_LAB_WHEN"].dt.date])
        .size()
        .groupby(["day_type", "arrival_hour"])
        .mean()
        .reset_index(name="avg_samples")
    )
    hourly_daytype_avg["pct_share"] = hourly_daytype_avg.groupby("day_type")["avg_samples"].transform(lambda x: (x / x.sum()) * 100)

    fig1, ax2 = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
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
    fig1.tight_layout()

    if save_plots:
        save_labelled_and_unlabelled(fig1, png_dir, f"{base_filename}_hourly_arrivals_weekday_vs_weekend", dpi=DPI)
    else:
        plt.close(fig1)

    # -------------------------------------------------------------
    # 3. GRAPH 2: Cancellation Reasons Bar Graph
    # -------------------------------------------------------------
    if not cancel_counts.empty:
        fig2, ax3 = plt.subplots(figsize=(PNG_WIDTH, PNG_HEIGHT))
        top_cancels = cancel_counts.head(10).reset_index()
        top_cancels.columns = ["Cancel_Code", "Count"]

        sns.barplot(
            data=top_cancels,
            x="Count",
            y="Cancel_Code",
            hue="Cancel_Code",
            palette="Reds_r",
            legend=False,
            edgecolor="black",
            ax=ax3,
        )

        cancel_rate_pct = cancellation_metrics["lab_cancel_rate_pct"]
        ax3.set_title(
            f"{base_filename} Top Cancel Codes (Total Canceled: {total_lab_canceled:,} | Rate: {cancel_rate_pct}%)",
            fontsize=13,
            fontweight="bold",
        )
        ax3.set_xlabel("Number of Cancelled Samples", fontsize=12)
        ax3.set_ylabel("Cancel Code", fontsize=12)

        for p in ax3.patches:
            width = p.get_width()
            ax3.annotate(
                f"{int(width):,}",
                (width, p.get_y() + p.get_height() / 2.0),
                ha="left",
                va="center",
                xytext=(5, 0),
                textcoords="offset points",
                fontsize=10,
            )

        fig2.tight_layout()
        if save_plots:
            save_labelled_and_unlabelled(fig2, png_dir, f"{base_filename}_cancel_codes_distribution", dpi=DPI)
        else:
            plt.close(fig2)

    # -------------------------------------------------------------
    # 4. GRAPH 3: Accessioning / Processing Time Distribution (Percentage)
    # -------------------------------------------------------------
    if not valid_acc.empty:
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

        ax_acc.axvline(mean_val, color="red", linestyle="--", linewidth=2, label=f"Mean: {mean_val:.1f} min")
        ax_acc.axvline(p99_val, color="darkorange", linestyle=":", linewidth=2, label=f"99th Percentile: {p99_val:.1f} min")

        ax_acc.set_title(f"{base_filename} Accessioning Processing Time Distribution", fontsize=14, fontweight="bold")
        ax_acc.set_xlabel("Accessioning Duration (Minutes)", fontsize=12)
        ax_acc.set_ylabel("Percentage of Samples (%)", fontsize=12)
        ax_acc.set_xlim(0, max(p99_val * 1.15, 10))
        ax_acc.legend(frameon=True)
        fig3.tight_layout()

        if save_plots:
            save_labelled_and_unlabelled(fig3, png_dir, f"{base_filename}_accession_time_distribution", dpi=DPI)
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

    print("BASE_DIR:", BASE_DIR)
    print("data_dir:", data_dir)

    specimen_groups = {
        "Bone": [data_dir / f"Bone_{TARGET_YEAR}.csv"],
        "Urine_Invasive": [
            data_dir / f"InvUrine_{TARGET_YEAR}.csv",
            data_dir / f"Inv_Urine_UofU_{TARGET_YEAR}.csv",
        ],
        "Urine_NonInvasive": [
            data_dir / f"NonInv_Urine_{TARGET_YEAR}.csv",
            data_dir / f"NonInv_Urine_UofU_{TARGET_YEAR}.csv",
        ],
        "Resp_NonCF": [data_dir / f"Respiratory_NonCF_{TARGET_YEAR}.csv"],
        "Resp_CF": [data_dir / f"Respiratory_CF_{TARGET_YEAR}.csv"],
        "Tissue": [
            data_dir / f"Tiss_genital_{TARGET_YEAR}.csv",
            data_dir / f"Tiss_FNA_{TARGET_YEAR}.csv",
            data_dir / f"TissueCleaned_{TARGET_YEAR}.csv",
        ],
        "Wound": [
            data_dir / f"Wound_genital_{TARGET_YEAR}.csv",
            data_dir / f"Wound_Cleaned_{TARGET_YEAR}.csv",
        ],
        "Stool": [
            data_dir / f"Stool_Ecoli_{TARGET_YEAR}.csv",
            data_dir / f"Stool_Campy_{TARGET_YEAR}.csv",
            data_dir / f"Stool_Vibrio_{TARGET_YEAR}.csv",
            data_dir / f"Stool_Yersinia_{TARGET_YEAR}.csv",
        ],
    }

    results = {}
    for group_name, file_paths in specimen_groups.items():
        valid_dfs = []
        for fp in file_paths:
            if fp.exists():
                valid_dfs.append(pd.read_csv(fp))
            else:
                print(f"Warning: File not found: {fp}")

        if valid_dfs:
            print(f"\nProcessing combined group: {group_name} ({len(valid_dfs)} files)...")
            combined_df = pd.concat(valid_dfs, ignore_index=True)
            weights, daily_vol = Process_and_Plot_Group(combined_df, group_name, out_dir, year=TARGET_YEAR, save_plots=True)
            results[group_name] = {
                "weights": weights,
                "daily_volume": daily_vol,
            }