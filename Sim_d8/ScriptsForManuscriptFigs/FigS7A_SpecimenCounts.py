#!/usr/bin/env python3
"""Figure S7A: Normalized specimen and positive isolate counts across specimen configurations
(both individual configurations and grouped categories, on linear and log10 scales).
Run: python FigS7A_SpecimenCounts_2.py"""
import glob
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedFormatter, FixedLocator, NullLocator
from scipy import stats

import fig_common as fc

# =============================================================================
# EDIT THESE FIRST
# =============================================================================
specimen_order_list = [
    "Urine_NonInvasive",
    "Urine_Invasive",
    "BCx",
    "Respiratory",
    "Resp_NonCF",
    "Resp_CystFibrosis",
    "Resp_CF",
    "Stool",
    "Stool_Ecoli",
    "Stool_EcoliRoutine",
    "Stool_Campy",
    "Stool_Vibrio",
    "Stool_Yersinia",
    "BodyFluid",
    "Bone_Cx",
    "Tissue",
    "Tissue_FNA",
    "Tissue_genital",
    "Wound",
    "Wound_Genital",
]

# Mapping for the combined/grouped figure
COMBINED_GROUPS = {
    "Urine (Non-Invasive)": ["Urine_NonInvasive"],
    "Urine (Invasive)": ["Urine_Invasive"],
    "Blood Culture (BCx)": ["BCx"],
    "Respiratory (Non-CF)": ["Respiratory", "Resp_NonCF"],
    "Respiratory (CF)": ["Resp_CystFibrosis", "Resp_CF"],
    "Stool": [
        "Stool", "Stool_Ecoli", "Stool_EcoliRoutine",
        "Stool_Campy", "Stool_Vibrio", "Stool_Yersinia",
    ],
    "Body Fluid": ["BodyFluid"],
    "Tissue / Bone / Wound": [
        "Bone_Cx", "Tissue", "Tissue_FNA", "Tissue_genital",
        "Wound", "Wound_Genital",
    ],
}

COMBINED_ORDER = list(COMBINED_GROUPS.keys())

# =============================================================================
# SETTINGS
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent.parent
SIM_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = SIM_DIR / "manuscript_png/FigS7_SpecCounts"
MC_DIR = SIM_DIR / "results_experiments/scn_baseline"

PNG_WIDTH = 4.8
LEFT_MARGIN_IN = 1.75
RIGHT_MARGIN_IN = 0.25
BOTTOM_MARGIN_IN = 0.65
TOP_MARGIN_IN = 0.72

PNG_HEIGHT = None
DPI = 300
LEGEND_COLUMNS = 1

SPECIMEN_COLUMN_CANDIDATES = [
    "specimen_config",
    "Type",
]

REFERENCE_SPECIMEN = None


def save_both(fig, stem, out_dir: Path, dpi: int = 300):
    """Save <stem>_labelled.png (white bg, visible axes) and <stem>_unlabelled.png (transparent bg, tick marks only) on an identical canvas."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Labelled version: solid white background, visible axes, tick labels, text annotations, and legend
    fig.patch.set_facecolor("white")
    fig.patch.set_alpha(1.0)
    for ax in fig.axes:
        ax.set_facecolor("white")
        ax.patch.set_alpha(1.0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_visible(True)
        ax.spines["left"].set_visible(True)
        ax.tick_params(which="both", bottom=True, left=True)

    fig.savefig(
        out_dir / f"{stem}_labelled.png",
        dpi=dpi,
        transparent=False,
        facecolor="white",
    )

    # 2. Strip all titles, axis labels, tick values, legends, and bar value text (keep tick marks & axis lines)
    for ax in fig.axes:
        ax.set_title("")
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(
            which="both",
            bottom=True, left=True,
            labelbottom=False, labelleft=False, labelright=False, labeltop=False,
        )
        ax.xaxis.set_minor_formatter(plt.NullFormatter())
        ax.yaxis.set_minor_formatter(plt.NullFormatter())
        if ax.get_legend():
            ax.get_legend().remove()
        for t in ax.texts:
            t.set_visible(False)

    for lg in list(fig.legends):
        lg.remove()
    if fig._suptitle is not None:
        fig._suptitle.set_visible(False)

    # 3. Unlabelled version: transparent background, visible axes & tick marks, identical canvas alignment
    fig.patch.set_alpha(0.0)
    for ax in fig.axes:
        ax.patch.set_alpha(0.0)

    fig.savefig(
        out_dir / f"{stem}_unlabelled.png",
        dpi=dpi,
        transparent=True,
        facecolor="none",
    )
    plt.close(fig)
    print(f"  wrote {stem}_labelled.png & {stem}_unlabelled.png")


def load_counts(mc_dir):
    mc = Path(mc_dir)
    files = sorted(glob.glob(str(mc / "replications" / "specimens_*.csv.gz")))
    if not files:
        raise FileNotFoundError(f"No specimens_*.csv.gz files found in {mc / 'replications'}")

    frames = []
    for f in files:
        d = pd.read_csv(f, low_memory=False)
        if "In_Window" in d.columns:
            d = d[d["In_Window"].astype(bool)].copy()
        if d.empty:
            continue
        if "rep" not in d.columns:
            match = re.search(r"(\d+)", Path(f).name)
            if match is None:
                raise ValueError(f"Could not identify replication number from {f}")
            d["rep"] = int(match.group(1))

        specimen_col = next((c for c in SPECIMEN_COLUMN_CANDIDATES if c in d.columns), None)
        if specimen_col is None:
            raise KeyError(f"{f} must contain one of {SPECIMEN_COLUMN_CANDIDATES}. Available columns: {list(d.columns)}")

        d = d.rename(columns={specimen_col: "specimen"})
        if "N_Isolates" not in d.columns:
            d["N_Isolates"] = np.nan
        if "Outcome" not in d.columns:
            d["Outcome"] = np.nan

        frames.append(d[["specimen", "Outcome", "N_Isolates", "rep"]])

    if not frames:
        raise RuntimeError("No in-window specimens were found.")

    cnt = pd.concat(frames, ignore_index=True)
    cnt["N_Isolates"] = pd.to_numeric(cnt["N_Isolates"], errors="coerce")
    cnt["positive"] = (cnt["Outcome"].astype(str).str.lower() == "pos").astype(int)
    print(f"Loaded {len(cnt):,} specimens from {cnt['rep'].nunique()} replications.")
    return cnt


def apply_combined_groups(cnt: pd.DataFrame) -> pd.DataFrame:
    """Map individual specimen configurations into COMBINED_GROUPS."""
    raw_to_group = {raw: grp for grp, members in COMBINED_GROUPS.items() for raw in members}
    out = cnt.copy()
    out["specimen"] = out["specimen"].map(lambda x: raw_to_group.get(str(x), str(x)))
    return out


def mean_ci(values):
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return np.nan, np.nan
    mean = np.mean(x)
    if len(x) < 2:
        return mean, np.nan
    ci = stats.t.ppf(0.975, len(x) - 1) * np.std(x, ddof=1) / np.sqrt(len(x))
    return mean, ci


def counts_table(cnt):
    per_rep = (
        cnt.groupby(["specimen", "rep"])
        .agg(
            samples=("specimen", "size"),
            positive=("positive", "sum"),
            isolates=("N_Isolates", "sum"),
        )
        .reset_index()
    )

    rows = []
    for specimen, d in per_rep.groupby("specimen"):
        row = {"specimen": specimen}
        for variable in ["samples", "positive", "isolates"]:
            m, ci = mean_ci(d[variable])
            row[variable] = m
            row[f"{variable}_ci95"] = ci

        row["positive_pct"] = 100 * row["positive"] / row["samples"] if row["samples"] > 0 else np.nan
        row["isolates_pct"] = 100 * row["isolates"] / row["samples"] if row["samples"] > 0 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def normalize_counts(tb):
    tb = tb.copy()
    if REFERENCE_SPECIMEN is not None:
        reference_rows = tb[tb["specimen"] == REFERENCE_SPECIMEN]
        if reference_rows.empty:
            raise ValueError(f"Reference specimen '{REFERENCE_SPECIMEN}' was not found in the counts table.")
        reference_count = float(reference_rows["samples"].iloc[0])
    else:
        reference_count = float(tb["samples"].max())

    if not np.isfinite(reference_count) or reference_count <= 0:
        raise ValueError("Reference specimen count must be greater than zero.")

    tb["reference_count"] = reference_count
    tb["samples_normalized"] = tb["samples"] / reference_count
    tb["samples_ci95_normalized"] = tb["samples_ci95"] / reference_count
    tb["isolates_normalized"] = tb["isolates"] / reference_count
    tb["isolates_ci95_normalized"] = tb["isolates_ci95"] / reference_count
    tb["isolates_pct"] = np.where(tb["samples"] > 0, 100 * tb["isolates"] / tb["samples"], np.nan)
    tb["isolates_pct_reference"] = 100 * tb["isolates_normalized"]

    print(f"Reference specimen count: {reference_count:,.0f}")
    return tb


def order_specimens(tb, order_list):
    available = tb["specimen"].astype(str).tolist()
    requested = [str(x) for x in order_list if str(x) in available]
    requested = list(dict.fromkeys(requested))
    remaining = [x for x in available if x not in requested]
    remaining = tb[tb["specimen"].isin(remaining)].sort_values("samples", ascending=False)["specimen"].astype(str).tolist()
    final_order = requested + remaining
    tb["specimen"] = pd.Categorical(tb["specimen"], categories=final_order, ordered=True)
    return tb.sort_values("specimen").reset_index(drop=True)


def _render_bars(tb: pd.DataFrame, log_scale: bool, stem: str, y_label: str = "Specimen configuration"):
    has_iso = tb["isolates"].fillna(0).sum() > 0
    y = np.arange(len(tb))
    h = 0.34 if has_iso else 0.60
    height = PNG_HEIGHT if PNG_HEIGHT is not None else max(3.4, 0.34 * len(tb) + 1.4)

    fig, ax = fc.new_fig(
        width_in=PNG_WIDTH,
        height_in=height,
        left_in=LEFT_MARGIN_IN,
        right_in=RIGHT_MARGIN_IN,
        bottom_in=BOTTOM_MARGIN_IN,
        top_in=TOP_MARGIN_IN,
    )

    sample_vals = tb["samples_normalized"].replace(0, np.nan) if log_scale else tb["samples_normalized"]
    sample_y = y + h / 2 if has_iso else y
    ax.barh(
        sample_y,
        sample_vals,
        height=h,
        xerr=tb["samples_ci95_normalized"].fillna(0) if not log_scale else None,
        color=fc.SIM_C,
        label="Total specimens / maximum specimen count",
        error_kw=dict(lw=0.7, ecolor=fc.INK2, capsize=1.5),
    )

    if has_iso:
        isolate_y = y - h / 2
        ax.barh(
            isolate_y,
            tb["isolates_normalized"].replace(0, np.nan),
            height=h,
            xerr=tb["isolates_ci95_normalized"].fillna(0) if not log_scale else None,
            color=fc.OBS24_C,
            label="Positive isolates / maximum specimen count",
            error_kw=dict(lw=0.7, ecolor=fc.INK2, capsize=1.5),
        )

    if log_scale:
        pos_vals = pd.concat([tb["samples_normalized"], tb["isolates_normalized"]]).dropna()
        pos_vals = pos_vals[pos_vals > 0]
        min_pos = float(pos_vals.min()) if not pos_vals.empty else 1e-4
        lo = 10.0 ** np.floor(np.log10(min_pos))
        hi = 1.5

        ax.set_xscale("log")
        ax.set_xlim(left=lo, right=hi)

        ticks = [10.0 ** e for e in range(int(np.floor(np.log10(lo))), int(np.ceil(np.log10(hi))) + 1)]
        ticks = [t for t in ticks if lo <= t <= hi]
        ax.xaxis.set_major_locator(FixedLocator(ticks))
        ax.xaxis.set_major_formatter(FixedFormatter([f"{t:g}" for t in ticks]))
        ax.xaxis.set_minor_locator(NullLocator())

        for yi, value in zip(sample_y, tb["samples_normalized"]):
            if pd.notna(value) and value > 0:
                lbl = f"{value:.3f}" if value < 0.01 else f"{value:.2f}"
                ax.text(value * 1.15, yi, lbl, va="center", ha="left", fontsize=5.8, color=fc.INK2)

        if has_iso:
            for yi, value, pct in zip(isolate_y, tb["isolates_normalized"], tb["isolates_pct"]):
                if pd.notna(value) and value > 0:
                    lbl = f"{value:.3f}" if value < 0.01 else f"{value:.2f}"
                    pct_label = f"{pct:.1f}%" if pd.notna(pct) else "NA"
                    ax.text(value * 1.15, yi, f"{lbl} ({pct_label})", va="center", ha="left", fontsize=5.8, color=fc.INK2)

        ax.set_xlabel("Relative count, log scale (largest category = 1.0)")
    else:
        for yi, value in zip(sample_y, tb["samples_normalized"]):
            ax.text(value + 0.015, yi, f"{value:.2f}", va="center", ha="left", fontsize=6, color=fc.INK2)

        if has_iso:
            for yi, value, pct in zip(isolate_y, tb["isolates_normalized"], tb["isolates_pct"]):
                if pd.notna(value) and value > 0:
                    pct_label = f"{pct:.1f}%" if pd.notna(pct) else "NA"
                    ax.text(value + 0.015, yi, f"{value:.2f} ({pct_label} of specimens)", va="center", ha="left", fontsize=6, color=fc.INK2)

        ax.set_xlim(left=0, right=max(1.15, float(tb["samples_normalized"].max()) * 1.42))
        ax.set_xlabel("Relative count (largest specimen category = 1.0)")

    ax.set_yticks(y)
    ax.set_yticklabels(tb["specimen"].astype(str))
    ax.invert_yaxis()
    ax.set_ylabel(y_label)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)

    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(
            handles,
            labels,
            loc="lower left",
            bbox_to_anchor=(0.0, 1.01),
            ncol=LEGEND_COLUMNS,
            frameon=False,
            fontsize=7.0,
        )

    save_both(fig, stem, OUTPUT_DIR, dpi=DPI)


def fig_specimen_counts(cnt):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Individual specimen configurations
    tb = counts_table(cnt)
    tb = normalize_counts(tb)
    tb = order_specimens(tb, specimen_order_list)
    tb.to_csv(OUTPUT_DIR / "table_specimen_counts_normalized.csv", index=False)

    _render_bars(tb, log_scale=False, stem="FigS7A_specimen_counts", y_label="Specimen configuration")
    _render_bars(tb, log_scale=True, stem="FigS7A_specimen_counts_log", y_label="Specimen configuration")

    # 2. Combined specimen categories (all Stool combined; Tissue + Bone + Wound combined)
    cnt_grouped = apply_combined_groups(cnt)
    tb_grp = counts_table(cnt_grouped)
    tb_grp = normalize_counts(tb_grp)
    tb_grp = order_specimens(tb_grp, COMBINED_ORDER)
    tb_grp.to_csv(OUTPUT_DIR / "table_specimen_counts_grouped_normalized.csv", index=False)

    _render_bars(tb_grp, log_scale=False, stem="FigS7A_specimen_counts_grouped", y_label="Specimen group")
    _render_bars(tb_grp, log_scale=True, stem="FigS7A_specimen_counts_grouped_log", y_label="Specimen group")


def main():
    fc.apply_style()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cnt = load_counts(MC_DIR)
    fig_specimen_counts(cnt)


if __name__ == "__main__":
    main()