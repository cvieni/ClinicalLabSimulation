# Sim_d8/ScriptsForManuscriptFigs/FigS6_SpecimenCounts.py

# =============================================================================
# EDIT THESE FIRST
# =============================================================================

output_direct = "manuscript_pngs/FigS6_SpecCounts"

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

from pathlib import Path
import glob
import re

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import fig_common as fc

# =============================================================================
# SETTINGS
# =============================================================================

OUTPUT_DIR = Path(output_direct)

PNG_WIDTH = 4.6
LEFT_MARGIN_IN = 1.75
RIGHT_MARGIN_IN = 0.25
BOTTOM_MARGIN_IN = 0.65
TOP_MARGIN_IN = 0.65

PNG_HEIGHT = None
DPI = 300
BARE = False

figure_margin_size = 0.0
set_background_transparent = True

# Research/ClinicalLabSimulation
BASE_DIR = Path(__file__).resolve().parent.parent.parent
SIM_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(SIM_DIR, "manuscript_png")         
MC_DIR = Path(SIM_DIR, "results_experiments/scn_baseline")

OBS_2025 = [Path(SIM_DIR, "data/observed_2025_lis_clean.csv")]
OBS_2024 = [Path(SIM_DIR, "data/observed_2024_lis_clean.csv")]
OBS_EXCLUDE = None                                             

SPECIMEN_COLUMN_CANDIDATES = [
    "specimen_config",
    "Type",
]

REFERENCE_SPECIMEN = None


def save_both(fig, stem, out_dir: Path, dpi: int = 300, bare: bool = False):
    """Save <stem>_labelled.png and <stem>_unlabelled.png with transparent background and zero margin."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        out_dir / f"{stem}_labelled.png",
        dpi=dpi,
        transparent=set_background_transparent,
        facecolor="none" if set_background_transparent else "white",
        edgecolor="none",
        bbox_inches="tight" if figure_margin_size == 0.0 else None,
        pad_inches=0.0,
    )

    for ax in fig.axes:
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(
            which="both",
            bottom=True, left=True,
            labelbottom=False, labelleft=False, labelright=False, labeltop=False,
        )
        if bare:
            ax.set_title("")
            if ax.get_legend():
                ax.get_legend().remove()
            for t in ax.texts:
                t.set_visible(False)

    if bare:
        for lg in list(fig.legends):
            lg.remove()
        if fig._suptitle is not None:
            fig._suptitle.set_visible(False)

    fig.savefig(
        out_dir / f"{stem}_unlabelled.png",
        dpi=dpi,
        transparent=set_background_transparent,
        facecolor="none" if set_background_transparent else "white",
        edgecolor="none",
        bbox_inches="tight" if figure_margin_size == 0.0 else None,
        pad_inches=0.0,
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


def mean_ci(values):
    from scipy import stats
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

    print(f"\nReference specimen count: {reference_count:,.0f}")
    return tb


def order_specimens(tb):
    available = tb["specimen"].astype(str).tolist()
    requested = [str(x) for x in specimen_order_list if str(x) in available]
    requested = list(dict.fromkeys(requested))
    remaining = [x for x in available if x not in requested]
    remaining = tb[tb["specimen"].isin(remaining)].sort_values("samples", ascending=False)["specimen"].astype(str).tolist()
    final_order = requested + remaining
    tb["specimen"] = pd.Categorical(tb["specimen"], categories=final_order, ordered=True)
    return tb.sort_values("specimen").reset_index(drop=True)


def fig_specimen_counts(cnt):
    tb = counts_table(cnt)
    tb = normalize_counts(tb)
    tb = order_specimens(tb)

    has_iso = tb["isolates"].fillna(0).sum() > 0
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tb.to_csv(OUTPUT_DIR / "table_specimen_counts_normalized.csv", index=False)

    y = np.arange(len(tb))
    h = 0.34 if has_iso else 0.60
    height = PNG_HEIGHT if PNG_HEIGHT is not None else 0.30 * len(tb) + 1.4

    fig, ax = fc.new_fig(
        width_in=PNG_WIDTH,
        height_in=height,
        left_in=LEFT_MARGIN_IN,
        right_in=RIGHT_MARGIN_IN,
        bottom_in=BOTTOM_MARGIN_IN,
        top_in=TOP_MARGIN_IN,
    )

    sample_y = y + h / 2 if has_iso else y
    ax.barh(
        sample_y,
        tb["samples_normalized"],
        height=h,
        xerr=tb["samples_ci95_normalized"].fillna(0),
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
            xerr=tb["isolates_ci95_normalized"].fillna(0),
            color=fc.OBS24_C,
            label="Positive isolates / maximum specimen count",
            error_kw=dict(lw=0.7, ecolor=fc.INK2, capsize=1.5),
        )

    for yi, value, pct in zip(sample_y, tb["samples_normalized"], tb["samples"]):
        ax.text(value + 0.015, yi, f"{value:.2f}", va="center", ha="left", fontsize=6, color=fc.INK2)

    if has_iso:
        for yi, value, pct in zip(isolate_y, tb["isolates_normalized"], tb["isolates_pct"]):
            if pd.notna(value) and value > 0:
                pct_label = f"{pct:.1f}%" if pd.notna(pct) else "NA"
                ax.text(value + 0.015, yi, f"{value:.2f} ({pct_label} of specimens)", va="center", ha="left", fontsize=6, color=fc.INK2)

    ax.set_yticks(y)
    ax.set_yticklabels(tb["specimen"].astype(str))
    ax.invert_yaxis()
    ax.set_xlim(left=0, right=max(1.15, float(tb["samples_normalized"].max()) * 1.35))
    ax.set_xlabel("Relative count (largest specimen category = 1.0)")
    ax.set_ylabel("Specimen configuration")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)

    fc.top_legend(ax, ncol=LEGEND_COLUMNS)
    save_both(fig, "FigS6_specimen_counts", OUTPUT_DIR, dpi=DPI, bare=BARE)


def main():
    fc.apply_style()
    if set_background_transparent:
        plt.rcParams.update({"figure.facecolor": "none", "axes.facecolor": "none"})

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cnt = load_counts(MC_DIR)
    fig_specimen_counts(cnt)


if __name__ == "__main__":
    main()