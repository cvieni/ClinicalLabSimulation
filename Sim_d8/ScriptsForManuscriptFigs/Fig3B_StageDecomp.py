#!/usr/bin/env python3
"""Figure 3B: where the time goes, driven by params_config/event_name.py."""
import glob
import sys
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import fig_common as fc

# =========================================================== SETTINGS (edit these) ===========================================================
PROJECT_ROOT = Path("..")                    # folder that contains params_config/ (so event_name.py can be imported)
MC_DIR = "results_experiments/mc_gerada_gram"
OUTPUT_DIR = Path("manuscript_png")
PNG_WIDTH = 5.2                              # inches
PNG_HEIGHT = None                            # inches; None = automatic (0.28 in per row + room for the legend)
LEFT_MARGIN_IN = 1.2                         # room for the y-axis labels (inches)
DPI = 300
BARE = False
SHOW_TOTAL = True                            # write the total (mean TAT, hours) at the end of each bar
LEGEND_COLUMNS = 2
GRANULAR = False                             # True: ignore STAGE_GROUPS and plot every event that takes >= MIN_HOURS on average
MIN_HOURS = 0.05                             # GRANULAR only: hide events whose mean time (over all types) is below this

figure_margin_size = 0.0
set_background_transparent = True

# y-axis order, TOP to BOTTOM (simulation specimen types). Missing ones are skipped, unlisted ones go at the bottom.
SPECIMEN_ORDER = ["BCx", "BodyFluid", "Bone_Cx", "Tissue", "Tissue_FNA", "Tissue_genital", "Wound", "Wound_Genital",
                  "Stool_Ecoli", "Stool_Campy", "Stool_Vibrio", "Stool_Yersinia", "Respiratory", "Resp_CystFibrosis",
                  "Urine_Invasive", "Urine_NonInvasive"]

STAGE_GROUPS = OrderedDict([
    ("Pre-accession hold",              ["ARRIVED", "PRE_ACCESSION_HOLD"]),
    ("Accession queue",                 ["ACCESSION_STORE_WAIT"]),
    ("Accession touch",                 ["ACCESSION_START", "ACCESSION_DONE", "STEP_LABEL_WITH_LAB_NUMBER_DONE", "STEP_LIMS_DONE",
                                         "STEP_COMBINE_LABELS_DONE", "STEP_SCAN_REQUEST_FORM_DONE"]),
    ("Bottle load / instrument slot",   ["BC_INSTRUMENT_LOAD_PENDING", "BC_INSTRUMENT_LOADED", "BACTEC_SLOT_WAIT", "STEP_MOVE_LOCATION_DONE",
                                         "STEP_LOAD_ONTO_ANALYZER_DONE"]),
    ("Bactec incubation",               ["BACTEC_LOADED"]),
    ("Positive bottle: plate, BioFire, Gram", ["BC_FLAGGED_POSITIVE", "BACTEC_POSITIVE", "PRIORITY_PLATING_STARTED", "PRIORITY_PLATING_DONE",
                                         "BIOFIRE_START", "BIOFIRE_DONE", "GRAM_STAIN_START", "GRAM_STAIN_DONE"]),
    ("Plating (queue + hands-on)",      ["ROUTINE_PLATING_QUEUED", "PLATING_TECH_WAIT", "ROUTINE_PLATING_STARTED", "WASP_PREP_START",
                                         "AUTOMATED_PLATING_STARTED", "MANUAL_PLATING_STARTED"]),
    ("Media stockout delay",            ["STOCKOUT_DELAY_START"]),
    ("Primary incubation",              ["PRIMARY_INCUBATION", "BLOOD_PLATE_INCUBATION", "ROUTINE_PLATING_DONE", "AUTOMATED_PLATING_DONE",
                                         "SEEDED_INCUBATION_START", "SEEDED_INCUBATION_DONE"]),
    ("Stool GN broth",                  ["GN_BROTH_INCUBATION_START", "GN_BROTH_INCUBATION_DONE", "GN_BROTH_SUBCULTURE_START",
                                         "GN_BROTH_SUBCULTURE_DONE"]),
    ("Tech review",                     ["TECH_REVIEW", "EXTENDED_REINCUBATION", "EVALUATE_BLOOD_SUBCULTURE"]),
    ("Bench tests",                     ["BENCH:*", "RAPID_BIOCHEM_SCREEN", "DIRECT_BIOCHEM_DONE", "BIOCHEM_DISCARD"]),
    ("Repeat work-up",                  ["REPEAT_WORKUP_SINGLE", "REPEAT_WORKUP_PARALLEL_PREFIX", "REPEAT_WORKUP_INCUBATION",
                                         "REPEAT_WORKUP_READ", "MULTI_ORGANISM_PARALLEL_PREFIX", "MIXED_FLORA", "POSITIVE_NO_WORKUP"]),
    ("MALDI identification",            ["MALDI_SPOT_START", "MALDI_SPOT_DONE_PREFIX", "MALDI_RUN_START", "MALDI_ID_DONE"]),
    ("Phoenix AST",                     ["PHOENIX_PREP_START", "PHOENIX_INCUBATION_START", "PHOENIX_AST_DONE", "PHOENIX_SLOT_TIMEOUT"]),
    ("Final read (hold + verify)",      ["FINAL_READ"]),
])
SHOW_OTHER = True
STAGE_COLORS = {}
PALETTE = ["#9db4f0", "#2a78d6", "#1f4e9c", "#eda100", "#d62728", "#e377c2", "#8c564b", "#ff7f0e", "#bcbd22", "#17becf",
           "#9467bd", "#7f7f7f", "#2ca02c", "#98df8a", "#1baf7a", "#c5b0d5", "#c7c7c7"]
# ==============================================================================================================================================

sys.path.insert(0, str(PROJECT_ROOT.resolve()))
try:
    from params_config import event_name as EV
except Exception as e:
    raise SystemExit(f"cannot import params_config.event_name from PROJECT_ROOT={PROJECT_ROOT.resolve()}: {e}")

META = {"Specimen_ID", "Type", "Arrival_Minute", "Completed_Minute", "In_Window", "rep"}


def save_both(fig, stem, out_dir=OUTPUT_DIR, dpi=DPI, bare=BARE):
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


def build_registry():
    reg = OrderedDict(EV._registry())
    for test, d in EV.BENCH_TEST_EVENTS.items():
        for kind, text in d.items():
            reg[f"BENCH_{test}_{kind}"] = text
    return reg


def column_to_name(col, reg):
    best, blen = None, -1
    for name, text in reg.items():
        if col == text:
            return name
        if col.startswith(text) and len(text) > blen:
            best, blen = name, len(text)
    return best


def resolve_groups(reg):
    groups = OrderedDict()
    seen = {}
    for label, names in STAGE_GROUPS.items():
        out = []
        for n in names:
            out += [k for k in reg if k.startswith("BENCH_")] if n == "BENCH:*" else ([n] if (n in reg or n == "FINAL_READ") else [])
        for n in out:
            if n in seen:
                pass
            else:
                seen[n] = label
        groups[label] = [n for n in out if seen[n] == label]
    return groups, seen


def process_replication(path, reg, names_order, type_ids, acc):
    d = pd.read_csv(path, low_memory=False)
    d = d[d["In_Window"].astype(bool) & d["Completed_Minute"].notna()]
    if d.empty:
        return
    col_name = {c: column_to_name(c, reg) for c in d.columns if c not in META}
    by_name = {}
    for c, n in col_name.items():
        if n and n not in ("ARRIVED", "ARRIVED_INITIAL", "COMPLETED"):
            by_name.setdefault(n, []).append(c)
    present = [n for n in names_order if n in by_name]
    K = len(present)
    T = np.full((len(d), K + 2), np.nan)
    T[:, 0] = d["Arrival_Minute"].to_numpy(float)
    for j, n in enumerate(present, start=1):
        T[:, j] = d[by_name[n]].apply(pd.to_numeric, errors="coerce").min(axis=1).to_numpy(float)
    T[:, K + 1] = d["Completed_Minute"].to_numpy(float)
    idx = np.argsort(T, axis=1, kind="stable")
    S = np.take_along_axis(T, idx, axis=1)
    dur = (S[:, 1:] - S[:, :-1]) / 60.0
    valid = ~np.isnan(dur)
    cur, nxt = idx[:, :-1], idx[:, 1:]
    target = np.where(nxt == K + 1, K + 1, cur)
    labels = ["ARRIVED"] + present + ["FINAL_READ"]
    tid = d["Type"].map(type_ids).to_numpy()
    flat = (tid[:, None] * (K + 2) + target)[valid]
    sums = np.bincount(flat, weights=dur[valid], minlength=len(type_ids) * (K + 2)).reshape(len(type_ids), K + 2)
    for t in range(len(type_ids)):
        for j, name in enumerate(labels):
            acc["sum"][t][name] = acc["sum"][t].get(name, 0.0) + sums[t, j]
    for t, n in zip(*np.unique(tid, return_counts=True)):
        acc["n"][t] += n
    acc["tat"] += np.bincount(tid, weights=((d["Completed_Minute"] - d["Arrival_Minute"]) / 60.0).to_numpy(), minlength=len(type_ids))


def main():
    fc.apply_style()
    if set_background_transparent:
        plt.rcParams.update({"figure.facecolor": "none", "axes.facecolor": "none"})

    reg = build_registry()
    files = sorted(glob.glob(str(Path(MC_DIR) / "replications" / "stages_*.csv.gz")))
    if not files:
        raise SystemExit(f"No replications/stages_*.csv.gz in {MC_DIR}.")
    types = sorted(pd.read_csv(files[0], usecols=["Type"])["Type"].unique())
    type_ids = {t: i for i, t in enumerate(types)}
    names_order = [n for n in reg if n not in ("ARRIVED", "ARRIVED_INITIAL", "COMPLETED")]
    acc = {"sum": [dict() for _ in types], "n": np.zeros(len(types)), "tat": np.zeros(len(types))}
    for f in files:
        process_replication(f, reg, names_order, type_ids, acc)

    n = acc["n"]
    wide = pd.DataFrame([{k: v / n[i] for k, v in acc["sum"][i].items()} for i in range(len(types))], index=types).fillna(0.0)
    wide = wide[[c for c in wide.columns if wide[c].abs().sum() > 0 or c == "FINAL_READ"]]
    mean_tat = pd.Series(acc["tat"] / np.where(n == 0, np.nan, n), index=types)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_tab = wide.copy()
    out_tab.insert(0, "n_specimens", n.astype(int))
    out_tab["mean_TAT_h"] = mean_tat
    out_tab.round(3).to_csv(OUTPUT_DIR / "fig3b_event_interval_hours.csv")

    if GRANULAR:
        keep = [c for c in wide.columns if wide[c].mean() >= MIN_HOURS]
        groups = OrderedDict((c.replace("_", " ").capitalize(), [c]) for c in keep)
        seen = {c: c.replace("_", " ").capitalize() for c in keep}
    else:
        groups, seen = resolve_groups(reg)
    stage = pd.DataFrame(index=wide.index)
    for label, names in groups.items():
        cols = [c for c in names if c in wide.columns]
        if cols:
            stage[label] = wide[cols].sum(axis=1)
    other = [c for c in wide.columns if c not in seen]
    if other and SHOW_OTHER:
        stage["Other"] = wide[other].sum(axis=1)
    stage = stage.loc[:, stage.abs().sum() > 0]
    stage.round(3).to_csv(OUTPUT_DIR / "fig3b_stage_hours.csv")

    order = fc.ordered(SPECIMEN_ORDER, stage.index)
    cols = list(stage.columns)
    colors = {c: STAGE_COLORS.get(c, PALETTE[i % len(PALETTE)]) for i, c in enumerate(cols)}
    top_in = fc.legend_height_in(len(cols), LEGEND_COLUMNS)
    h_in = PNG_HEIGHT if PNG_HEIGHT else 0.28 * len(order) + 0.8 + top_in
    fig, ax = fc.new_fig(PNG_WIDTH, h_in, left_in=LEFT_MARGIN_IN, right_in=0.5, bottom_in=0.6, top_in=top_in)
    left = np.zeros(len(order))
    for c in cols:
        vals = stage.loc[order, c].to_numpy()
        ax.barh(range(len(order)), vals, left=left, color=colors[c], label=c, edgecolor="white", linewidth=0.4, height=0.72)
        left += vals
    if SHOW_TOTAL:
        for k, tot in enumerate(left):
            ax.text(tot + 0.01 * left.max(), k, f"{tot:.0f}", va="center", fontsize=6.5, color=fc.INK2)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order)
    ax.set_ylim(-0.6, len(order) - 0.4)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Mean hours per stage")
    ax.set_ylabel("Specimen type")
    fc.top_legend(ax, ncol=LEGEND_COLUMNS)
    save_both(fig, "03c_stage_decomposition", OUTPUT_DIR, DPI, BARE)


if __name__ == "__main__":
    main()