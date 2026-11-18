#!/usr/bin/env python3
"""Figure 3B: where the time goes, driven by params_config/event_name.py.

Generates stacked bar figures (_labelled.png & _unlabelled.png) for:
  1. Overall (all specimens):
     - 03c_stage_decomposition_p50
     - 03c_stage_decomposition_p95
     - 03c_stage_decomposition_mean
  2. Positive isolates (isolate worked up):
     - 03c_stage_decomposition_pos_p50
     - 03c_stage_decomposition_pos_p95
     - 03c_stage_decomposition_pos_mean
  3. Negative isolates (no isolate):
     - 03c_stage_decomposition_neg_p50
     - 03c_stage_decomposition_neg_p95
     - 03c_stage_decomposition_neg_mean

Also writes:
  - fig3b_event_interval_hours.csv
  - fig3b_stage_hours.csv (mean)
  - fig3b_stage_hours_p50.csv (median)
  - fig3b_stage_hours_p95.csv (95th percentile)
  - fig3b_stage_hours_by_outcome.csv (split by isolate outcome: negative vs positive)
"""
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
PROJECT_ROOT = Path(__file__).resolve().parent.parent   # Sim_d8/ (contains params_config/)
MC_DIR = PROJECT_ROOT / "results_experiments/scn_baseline_stages"
OUTPUT_DIR = PROJECT_ROOT / "manuscript_png/Fig3B_StageDecomp"
PNG_WIDTH = 5.4                              # inches
PNG_HEIGHT = None                            # inches; None = automatic (0.28 in per row + room for the legend)
LEFT_MARGIN_IN = 1.25                        # room for the y-axis labels (inches)
DPI = 300
SHOW_TOTAL = True                            # write the total (hours) at the end of each bar
LEGEND_COLUMNS = 2
GRANULAR = False                             # True: ignore STAGE_GROUPS and plot every event that takes >= MIN_HOURS on average
MIN_HOURS = 0.05                             # GRANULAR only: hide events whose mean time (over all types) is below this
QUANTILE_BAND = 0.025                        # +/- band around P50 / P95 TAT to average stage shares cleanly

# Mean sign-out / verification window (hours) from params_d3 (final_read_delay_*_hours)
VERIFY_HOURS_NEG = 1.5                       # final_read_delay_other_hours mean [1.0, 2.0] -> 1.5 h
VERIFY_HOURS_POS_NO_AST = 1.5                # final_read_delay_other_hours / blood_hours mean -> 1.5 h
VERIFY_HOURS_POS_AST = 9.0                   # final_read_delay_ast_hours mean [8.0, 10.0] -> 9.0 h

# y-axis order, TOP to BOTTOM (simulation specimen types). Missing ones are skipped, unlisted ones go at the bottom.
SPECIMEN_ORDER = ["BCx", "BodyFluid", "Bone_Cx", "Tissue", "Tissue_FNA", "Tissue_genital", "Wound", "Wound_Genital",
                  "Stool_Ecoli", "Stool_Campy", "Stool_Vibrio", "Stool_Yersinia", "Respiratory", "Resp_CystFibrosis",
                  "Urine_Invasive", "Urine_NonInvasive"]

STAGE_GROUPS = OrderedDict([
    ("Pre-accession hold",                    ["ARRIVED", "PRE_ACCESSION_HOLD"]),
    ("Accession queue",                       ["ACCESSION_STORE_WAIT"]),
    ("Accession touch",                       ["ACCESSION_START", "ACCESSION_DONE", "STEP_LABEL_WITH_LAB_NUMBER_DONE", "STEP_LIMS_DONE",
                                               "STEP_COMBINE_LABELS_DONE", "STEP_SCAN_REQUEST_FORM_DONE"]),
    ("Bottle load / instrument slot",         ["BC_INSTRUMENT_LOAD_PENDING", "BC_INSTRUMENT_LOADED", "BACTEC_SLOT_WAIT", "STEP_MOVE_LOCATION_DONE",
                                               "STEP_LOAD_ONTO_ANALYZER_DONE"]),
    ("Bactec incubation",                     ["BACTEC_LOADED", "BACTEC_NEGATIVE", "BC_FLAGGED_NEGATIVE"]),
    ("Positive bottle: plate, BioFire, Gram", ["BC_FLAGGED_POSITIVE", "BACTEC_POSITIVE", "PRIORITY_PLATING_STARTED", "PRIORITY_PLATING_DONE",
                                               "BIOFIRE_START", "BIOFIRE_DONE", "GRAM_STAIN_START", "GRAM_STAIN_DONE"]),
    ("Plating (queue + hands-on)",            ["ROUTINE_PLATING_QUEUED", "PLATING_TECH_WAIT", "ROUTINE_PLATING_STARTED", "WASP_PREP_START",
                                               "AUTOMATED_PLATING_STARTED", "MANUAL_PLATING_STARTED"]),
    ("Media stockout delay",                  ["STOCKOUT_DELAY_START"]),
    ("Primary incubation",                    ["PRIMARY_INCUBATION", "BLOOD_PLATE_INCUBATION", "ROUTINE_PLATING_DONE", "AUTOMATED_PLATING_DONE",
                                               "SEEDED_INCUBATION_START", "SEEDED_INCUBATION_DONE"]),
    ("Stool GN broth",                        ["GN_BROTH_INCUBATION_START", "GN_BROTH_INCUBATION_DONE", "GN_BROTH_SUBCULTURE_START",
                                               "GN_BROTH_SUBCULTURE_DONE"]),
    ("Tech review",                           ["TECH_REVIEW", "EXTENDED_REINCUBATION", "EVALUATE_BLOOD_SUBCULTURE"]),
    ("Bench tests",                           ["BENCH:*", "RAPID_BIOCHEM_SCREEN", "DIRECT_BIOCHEM_DONE", "BIOCHEM_DISCARD"]),
    ("Repeat work-up",                        ["REPEAT_WORKUP_SINGLE", "REPEAT_WORKUP_PARALLEL_PREFIX", "REPEAT_WORKUP_INCUBATION",
                                               "REPEAT_WORKUP_READ", "MULTI_ORGANISM_PARALLEL_PREFIX", "MIXED_FLORA", "POSITIVE_NO_WORKUP"]),
    ("MALDI identification",                  ["MALDI_SPOT_START", "MALDI_SPOT_DONE_PREFIX", "MALDI_RUN_START", "MALDI_ID_DONE"]),
    ("Phoenix AST",                           ["PHOENIX_PREP_START", "PHOENIX_INCUBATION_START", "PHOENIX_AST_DONE", "PHOENIX_SLOT_TIMEOUT"]),
    ("Negative culture hold / incubation",    ["NEG_CULTURE_HOLD", "NO_SIGNIFICANT_GROWTH"]),
    ("Work-up / AST hold & read alignment",   ["POS_WORKUP_HOLD"]),
    ("Final verification & sign-out",         ["FINAL_VERIFICATION"]),
])
SHOW_OTHER = True
STAGE_COLORS = {
    "Negative culture hold / incubation": "#b0c4de",
    "Work-up / AST hold & read alignment": "#f6c85f",
    "Final verification & sign-out": "#c5b0d5",
}
PALETTE = ["#9db4f0", "#2a78d6", "#1f4e9c", "#eda100", "#d62728", "#e377c2", "#8c564b", "#ff7f0e", "#bcbd22", "#17becf",
           "#9467bd", "#7f7f7f", "#2ca02c", "#98df8a", "#1baf7a", "#b0c4de", "#f6c85f", "#c5b0d5", "#c7c7c7"]
# ==============================================================================================================================================

sys.path.insert(0, str(PROJECT_ROOT))
try:
    from params_config import event_name as EV
except Exception as e:
    raise SystemExit(f"cannot import params_config.event_name from PROJECT_ROOT={PROJECT_ROOT}: {e}")

META = {"Specimen_ID", "Type", "Arrival_Minute", "Completed_Minute", "In_Window", "rep",
        "Total_TAT_Hours", "Arrival_Shift", "Outcome", "N_Isolates"}


def save_both(fig, stem, out_dir=OUTPUT_DIR, dpi=DPI):
    """Save <stem>_labelled.png (white bg, visible axes & labels) and <stem>_unlabelled.png (transparent bg, tight crop around axes & ticks)."""
    out_dir.mkdir(parents=True, exist_ok=True)

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
        edgecolor="none",
        bbox_inches="tight",
        pad_inches=0.04,
    )

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
        for t in ax.texts:
            t.set_visible(False)

    for lg in list(fig.legends):
        lg.remove()
    if fig._suptitle is not None:
        fig._suptitle.set_visible(False)

    fig.patch.set_facecolor("none")
    fig.patch.set_alpha(0.0)
    for ax in fig.axes:
        ax.set_facecolor("none")
        ax.patch.set_alpha(0.0)

    fig.savefig(
        out_dir / f"{stem}_unlabelled.png",
        dpi=dpi,
        transparent=True,
        facecolor="none",
        edgecolor="none",
        bbox_inches="tight",
        pad_inches=0.02,
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
    synthetic = {"NEG_CULTURE_HOLD", "POS_WORKUP_HOLD", "FINAL_VERIFICATION"}
    groups = OrderedDict()
    seen = {}
    for label, names in STAGE_GROUPS.items():
        out = []
        for n in names:
            if n == "BENCH:*":
                out += [k for k in reg if k.startswith("BENCH_")]
            elif n in reg or n in synthetic:
                out.append(n)
        for n in out:
            if n not in seen:
                seen[n] = label
        groups[label] = [n for n in out if seen[n] == label]
    return groups, seen


def _classify_negative(d: pd.DataFrame) -> np.ndarray:
    """Boolean mask: True if specimen has negative isolate outcome."""
    if "Outcome" in d.columns:
        return d["Outcome"].astype(str).str.lower().isin(["neg", "negative", "no_growth", "none"]).to_numpy()
    if "N_Isolates" in d.columns:
        return (pd.to_numeric(d["N_Isolates"], errors="coerce").fillna(0) == 0).to_numpy()
    neg_cols = [c for c in d.columns if any(str(c).startswith(m) for m in EV.NEGATIVE_MARKERS)]
    if neg_cols:
        return d[neg_cols].notna().any(axis=1).to_numpy()
    return np.zeros(len(d), dtype=bool)


def extract_specimen_stages(path, reg, names_order, groups, seen):
    """Compute per-specimen stage durations (hours) for one replication file."""
    d = pd.read_csv(path, low_memory=False)
    d = d[d["In_Window"].astype(bool) & d["Completed_Minute"].notna()].copy()
    if d.empty:
        return pd.DataFrame(), pd.DataFrame(), np.array([], dtype=bool)

    is_neg = _classify_negative(d)
    ast_cols = [c for c in d.columns if str(c).startswith(EV.PHOENIX_AST_DONE) or str(c).startswith(EV.PHOENIX_INCUBATION_START)]
    has_ast = d[ast_cols].notna().any(axis=1).to_numpy() if ast_cols else np.zeros(len(d), dtype=bool)

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

    n_states = K + 4
    terminal = (nxt == K + 1) & valid
    term_dur = np.where(terminal, dur, 0.0).sum(axis=1)

    verify_cap = np.where(is_neg, VERIFY_HOURS_NEG, np.where(has_ast, VERIFY_HOURS_POS_AST, VERIFY_HOURS_POS_NO_AST))
    verify_dur = np.minimum(term_dur, verify_cap)
    hold_dur = np.maximum(term_dur - verify_dur, 0.0)

    dur_nonterm = np.where(terminal, 0.0, dur)
    labels = ["ARRIVED"] + present + ["NEG_CULTURE_HOLD", "POS_WORKUP_HOLD", "FINAL_VERIFICATION"]

    # Per-specimen event matrix (N_specimens x n_states)
    n_spec = len(d)
    ev_mat = np.zeros((n_spec, n_states), dtype=float)
    rows_idx = np.broadcast_to(np.arange(n_spec)[:, None], cur.shape)[valid]
    cols_idx = cur[valid]
    np.add.at(ev_mat, (rows_idx, cols_idx), dur_nonterm[valid])
    ev_mat[is_neg, K + 1] += hold_dur[is_neg]
    ev_mat[~is_neg, K + 2] += hold_dur[~is_neg]
    ev_mat[:, K + 3] += verify_dur

    ev_df = pd.DataFrame(ev_mat, columns=labels)
    ev_df.insert(0, "Type", d["Type"].to_numpy())
    ev_df["tat_h"] = ((d["Completed_Minute"] - d["Arrival_Minute"]) / 60.0).to_numpy()

    # Roll up into stage columns per specimen
    st_df = pd.DataFrame({"Type": d["Type"].to_numpy(), "tat_h": ev_df["tat_h"].to_numpy()})
    for label, names in groups.items():
        cols = [c for c in names if c in ev_df.columns]
        if cols:
            st_df[label] = ev_df[cols].sum(axis=1).to_numpy()
    other = [c for c in labels if c not in seen]
    if other and SHOW_OTHER:
        st_df["Other"] = ev_df[other].sum(axis=1).to_numpy()

    return ev_df, st_df, is_neg


def quantile_stage_profile(st_all: pd.DataFrame, stage_cols: list[str], q: float, band: float = QUANTILE_BAND) -> pd.DataFrame:
    """For each specimen type, compute the stage decomposition at quantile q (e.g., 0.50 or 0.95) of total TAT.

    Averages stage shares across specimens within [q - band, q + band] of each type's total TAT distribution
    and scales to the exact q-th percentile TAT so stacked bars sum cleanly to P50 / P95 TAT.
    """
    rows = {}
    for t, grp in st_all.groupby("Type"):
        tat = grp["tat_h"].to_numpy()
        target_tat = float(np.percentile(tat, q * 100.0))
        lo_q = max(0.0, q - band)
        hi_q = min(1.0, q + band)
        lo_v, hi_v = np.percentile(tat, [lo_q * 100.0, hi_q * 100.0])
        sub = grp[(grp["tat_h"] >= lo_v) & (grp["tat_h"] <= hi_v)]
        if sub.empty:
            idx_closest = np.abs(tat - target_tat).argmin()
            sub = grp.iloc[[idx_closest]]
        vals = sub[stage_cols].mean(axis=0)
        s_sum = float(vals.sum())
        if s_sum > 0 and target_tat > 0:
            vals = vals * (target_tat / s_sum)
        rows[t] = vals
    out = pd.DataFrame.from_dict(rows, orient="index")
    return out.loc[:, out.abs().sum() > 0]


def render_stage_bar(stage_df: pd.DataFrame, order: list[str], colors: dict, xlabel: str, stem: str, title: str | None = None):
    plot_order = [t for t in order if t in stage_df.index]
    cols = [c for c in stage_df.columns if c in colors]
    top_in = fc.legend_height_in(len(cols), LEGEND_COLUMNS) + (0.25 if title else 0.0)
    h_in = PNG_HEIGHT if PNG_HEIGHT else 0.28 * len(plot_order) + 0.8 + top_in
    fig, ax = fc.new_fig(PNG_WIDTH, h_in, left_in=LEFT_MARGIN_IN, right_in=0.5, bottom_in=0.6, top_in=top_in)
    left = np.zeros(len(plot_order))
    for c in cols:
        vals = stage_df.loc[plot_order, c].to_numpy()
        ax.barh(range(len(plot_order)), vals, left=left, color=colors[c], label=c, edgecolor="white", linewidth=0.4, height=0.72)
        left += vals
    if SHOW_TOTAL:
        for k, tot in enumerate(left):
            ax.text(tot + 0.01 * left.max(), k, f"{tot:.0f}", va="center", fontsize=6.5, color=fc.INK2)
    ax.set_yticks(range(len(plot_order)))
    ax.set_yticklabels(plot_order)
    ax.set_ylim(-0.6, len(plot_order) - 0.4)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Specimen type")
    if title:
        ax.set_title(title, fontsize=9, fontweight="bold", pad=28)
    fc.top_legend(ax, ncol=LEGEND_COLUMNS)
    save_both(fig, stem, OUTPUT_DIR, DPI)


def plot_cohort_suite(st_sub: pd.DataFrame, active_stage_cols: list[str], order: list[str], colors: dict,
                      stem_prefix: str, cohort_label: str):
    """Render P50, P95, and Mean stage decomposition figures for a given specimen cohort."""
    stage_mean = st_sub.groupby("Type")[active_stage_cols].mean()
    stage_mean = stage_mean.loc[:, stage_mean.abs().sum() > 0]
    stage_p50 = quantile_stage_profile(st_sub, active_stage_cols, q=0.50)
    stage_p95 = quantile_stage_profile(st_sub, active_stage_cols, q=0.95)

    render_stage_bar(
        stage_p50,
        order=order,
        colors=colors,
        xlabel=f"Median (P50) hours per stage — {cohort_label}",
        stem=f"{stem_prefix}_p50",
    )
    render_stage_bar(
        stage_p95,
        order=order,
        colors=colors,
        xlabel=f"95th percentile (P95) hours per stage — {cohort_label}",
        stem=f"{stem_prefix}_p95",
    )
    render_stage_bar(
        stage_mean,
        order=order,
        colors=colors,
        xlabel=f"Mean hours per stage — {cohort_label}",
        stem=f"{stem_prefix}_mean",
    )
    return stage_mean, stage_p50, stage_p95


def main():
    fc.apply_style()
    plt.rcParams.update({"figure.facecolor": "white", "axes.facecolor": "white"})

    reg = build_registry()
    files = sorted(glob.glob(str(Path(MC_DIR) / "replications" / "stages_*.csv.gz")))
    if not files:
        raise SystemExit(f"No replications/stages_*.csv.gz in {MC_DIR}.")

    names_order = [n for n in reg if n not in ("ARRIVED", "ARRIVED_INITIAL", "COMPLETED")]
    if GRANULAR:
        groups_init, seen_init = resolve_groups(reg)
        ev_list, st_list, neg_list = [], [], []
        for f in files:
            ev_df, st_df, is_neg = extract_specimen_stages(f, reg, names_order, groups_init, seen_init)
            if not ev_df.empty:
                ev_list.append(ev_df)
                st_list.append(st_df)
                neg_list.append(is_neg)
        ev_all = pd.concat(ev_list, ignore_index=True)
        ev_cols = [c for c in ev_all.columns if c not in ("Type", "tat_h") and ev_all[c].mean() >= MIN_HOURS]
        groups = OrderedDict((c.replace("_", " ").capitalize(), [c]) for c in ev_cols)
        seen = {c: c.replace("_", " ").capitalize() for c in ev_cols}
        st_all = pd.DataFrame({"Type": ev_all["Type"], "tat_h": ev_all["tat_h"]})
        for lbl, clist in groups.items():
            st_all[lbl] = ev_all[clist].sum(axis=1)
        is_neg_all = np.concatenate(neg_list)
    else:
        groups, seen = resolve_groups(reg)
        ev_list, st_list, neg_list = [], [], []
        for f in files:
            ev_df, st_df, is_neg = extract_specimen_stages(f, reg, names_order, groups, seen)
            if not ev_df.empty:
                ev_list.append(ev_df)
                st_list.append(st_df)
                neg_list.append(is_neg)
        ev_all = pd.concat(ev_list, ignore_index=True).fillna(0.0)
        st_all = pd.concat(st_list, ignore_index=True).fillna(0.0)
        is_neg_all = np.concatenate(neg_list)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Mean event-level and stage-level tables (all specimens)
    ev_num_cols = [c for c in ev_all.columns if c not in ("Type", "tat_h")]
    out_tab = ev_all.groupby("Type")[ev_num_cols].mean()
    out_tab = out_tab[[c for c in out_tab.columns if out_tab[c].abs().sum() > 0 or c == "FINAL_VERIFICATION"]]
    out_tab.insert(0, "n_specimens", ev_all.groupby("Type").size())
    out_tab["mean_TAT_h"] = ev_all.groupby("Type")["tat_h"].mean()
    out_tab.round(3).to_csv(OUTPUT_DIR / "fig3b_event_interval_hours.csv")

    stage_cols = [c for c in st_all.columns if c not in ("Type", "tat_h")]
    stage_mean_all = st_all.groupby("Type")[stage_cols].mean()
    stage_mean_all = stage_mean_all.loc[:, stage_mean_all.abs().sum() > 0]
    active_stage_cols = list(stage_mean_all.columns)

    # Shared order and color mapping across all figures
    order = fc.ordered(SPECIMEN_ORDER, stage_mean_all.index)
    colors = {c: STAGE_COLORS.get(c, PALETTE[i % len(PALETTE)]) for i, c in enumerate(active_stage_cols)}

    # 2. Render Overall (P50, P95, Mean) + save CSVs
    st_mean, st_p50, st_p95 = plot_cohort_suite(
        st_all, active_stage_cols, order, colors,
        stem_prefix="03c_stage_decomposition",
        cohort_label="All specimens",
    )
    st_mean.round(3).to_csv(OUTPUT_DIR / "fig3b_stage_hours.csv")
    st_p50.round(3).to_csv(OUTPUT_DIR / "fig3b_stage_hours_p50.csv")
    st_p95.round(3).to_csv(OUTPUT_DIR / "fig3b_stage_hours_p95.csv")

    # 3. Render Positive Isolates (P50, P95, Mean) & Negative Isolates (P50, P95, Mean) + export CSV
    outcome_frames = []
    for oc_mask, stem_pfx, oc_label in [
        (~is_neg_all, "03c_stage_decomposition_pos", "Positive isolates"),
        (is_neg_all,  "03c_stage_decomposition_neg", "Negative isolates"),
    ]:
        sub_st = st_all.loc[oc_mask]
        if sub_st.empty:
            continue
        m_oc, _, _ = plot_cohort_suite(
            sub_st, active_stage_cols, order, colors,
            stem_prefix=stem_pfx,
            cohort_label=oc_label,
        )
        m_oc.insert(0, "n_specimens", sub_st.groupby("Type").size())
        m_oc.insert(1, "mean_TAT_h", sub_st.groupby("Type")["tat_h"].mean())
        m_oc.insert(2, "p50_TAT_h", sub_st.groupby("Type")["tat_h"].quantile(0.50))
        m_oc.insert(3, "p95_TAT_h", sub_st.groupby("Type")["tat_h"].quantile(0.95))
        m_oc.insert(0, "isolate_outcome", oc_label)
        outcome_frames.append(m_oc)

    if outcome_frames:
        pd.concat(outcome_frames).round(3).to_csv(OUTPUT_DIR / "fig3b_stage_hours_by_outcome.csv")


if __name__ == "__main__":
    main()