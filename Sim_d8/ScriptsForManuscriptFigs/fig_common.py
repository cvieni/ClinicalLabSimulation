"""Shared helpers for the manuscript figure scripts. Keep this file in the same folder as Fig*.py.
Each Fig*.py has its own settings block at the top (output_dir, size, ordering); nothing here needs editing."""
from __future__ import annotations

import glob
import re
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from scipy import stats

INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SIM_C, OBS_C, OBS24_C = "#2a78d6", "#0b0b0b", "#eb6834"
FALLBACK_PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SHIFT_HOURS = {"Day": (7, 15), "Evening": (15, 23)}          # everything else = Night

# display group -> simulation specimen types pooled into it (validation figures: urine pooled, stool also split by test code)
GROUPS_VALIDATION = {
    "Blood culture": ["BCx"], "Body fluid": ["BodyFluid"], "Bone": ["Bone_Cx"], "Tissue": ["Tissue"],
    "Tissue (FNA)": ["Tissue_FNA"], "Tissue (genital)": ["Tissue_genital"], "Wound": ["Wound"],
    "Wound (genital)": ["Wound_Genital"],
    "Stool": ["Stool", "Stool_Ecoli", "Stool_EcoliRoutine", "Stool_Campy", "Stool_Vibrio", "Stool_Yersinia"],
    "Stool 60134 (E. coli)": [], "Stool 60135 (Campylobacter)": [], "Stool 60136 (Vibrio)": [], "Stool 60137 (Yersinia)": [],
    "Respiratory (non-CF)": ["Respiratory", "Resp_NonCF"], "Respiratory (CF)": ["Resp_CystFibrosis", "Resp_CF"],
    "Urine": ["Urine_Invasive", "Urine_NonInvasive"],
}
OBS_TO_GROUP = {"bloodculture": "Blood culture", "bodyfluid": "Body fluid", "bone": "Bone", "tissue": "Tissue",
                "fnatissue": "Tissue (FNA)", "genitaltissue": "Tissue (genital)", "wound": "Wound",
                "genitalwound": "Wound (genital)", "woundgenital": "Wound (genital)", "stool": "Stool",
                "respiratory": "Respiratory (non-CF)", "respiratorynoncf": "Respiratory (non-CF)", "respnoncf": "Respiratory (non-CF)",
                "noncf": "Respiratory (non-CF)", "respiratorycf": "Respiratory (CF)", "respcf": "Respiratory (CF)", "cf": "Respiratory (CF)",
                "cysticfibrosis": "Respiratory (CF)", "invasiveurine": "Urine", "noninvasiveurine": "Urine", "urine": "Urine"}
STOOL_SPLIT = {"60134": "Stool 60134 (E. coli)", "60135": "Stool 60135 (Campylobacter)",
               "60136": "Stool 60136 (Vibrio)", "60137": "Stool 60137 (Yersinia)"}
SIM_STOOL_CODE = {"Stool_Ecoli": "60134", "Stool_EcoliRoutine": "60134", "Stool_Campy": "60135", "Stool_Vibrio": "60136", "Stool_Yersinia": "60137"}


def invert(groups: dict) -> dict:
    return {s: g for g, ss in groups.items() for s in ss}


def apply_style():
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
        "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
        "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.8,
        "xtick.major.width": 0.8, "ytick.major.width": 0.8, "axes.grid": True, "grid.color": GRID,
        "grid.linewidth": 0.5, "axes.axisbelow": True, "figure.facecolor": "white", "axes.facecolor": "white",
        "pdf.fonttype": 42, "svg.fonttype": "none",
    })


def new_fig(width_in, height_in, left_in, right_in, bottom_in, top_in):
    """Figure of exactly width x height inches; the axes margins are given in INCHES so label space stays constant
    when you change the size."""
    fig, ax = plt.subplots(figsize=(width_in, height_in))
    fig.subplots_adjust(left=left_in / width_in, right=1 - right_in / width_in,
                        bottom=bottom_in / height_in, top=1 - top_in / height_in)
    return fig, ax


def save_both(fig, stem, output_dir, dpi=300, bare=False):
    """<stem>_labelled.png and <stem>_unlabelled.png on an identical canvas (no tight bbox), so they overlay exactly.
    Unlabelled: axis titles and tick LABELS removed (tick marks kept). bare=True also drops legends, titles, in-plot text."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{stem}_labelled.png", dpi=dpi, facecolor="white")
    for ax in fig.axes:
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(labelbottom=False, labelleft=False, labelright=False, labeltop=False)
        if bare:
            ax.set_title("")
            if ax.get_legend():
                ax.get_legend().remove()
            for t in ax.texts:
                t.set_visible(False)
    if bare:
        for lg in list(fig.legends):
            lg.remove()
    fig.savefig(out / f"{stem}_unlabelled.png", dpi=dpi, facecolor="white")
    plt.close(fig)
    print(f"  wrote {stem}_labelled.png and {stem}_unlabelled.png in {out}")


def top_legend(ax, handles=None, ncol=3):
    """Legend centred on the FIGURE (not the axes) at the top, so it never runs off the canvas. Needs top_in >= legend_height_in()."""
    if handles is None:
        handles, labels = ax.get_legend_handles_labels()
    else:
        labels = [h.get_label() for h in handles]
    ax.figure.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.995), ncol=ncol, frameon=False,
                     handlelength=1.6, columnspacing=1.0)


def legend_height_in(n_items, ncol):
    """Inches the top legend needs (about 0.17 in per row plus padding)."""
    return 0.17 * int(np.ceil(n_items / max(ncol, 1))) + 0.15


def ordered(wanted, available):
    """Your list first (in your order, skipping names that are not in the data), then anything left over."""
    avail = list(dict.fromkeys(available))
    out = [w for w in wanted if w in avail]
    return out + [a for a in avail if a not in out]


def shift_of_hour(h):
    h = np.asarray(h)
    return np.where((h >= SHIFT_HOURS["Day"][0]) & (h < SHIFT_HOURS["Day"][1]), "Day",
                    np.where((h >= SHIFT_HOURS["Evening"][0]) & (h < SHIFT_HOURS["Evening"][1]), "Evening", "Night"))


def tci(x):
    x = np.asarray([v for v in x if np.isfinite(v)])
    if len(x) < 2:
        return (x.mean() if len(x) else np.nan), np.nan
    return x.mean(), stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))


def norm(s):
    return re.sub(r"[^a-z]", "", str(s).lower())


# ---------------------------------------------------------------- loading
def load_sim(mc_dir, sim_to_group):
    mc = Path(mc_dir)
    rt = pd.read_csv(mc / "run_table.csv")
    w0 = float(rt["window_start_min"].iloc[0]) if "window_start_min" in rt else 0.0
    w1 = float(rt["window_end_min"].iloc[0]) if "window_end_min" in rt else np.inf
    frames = []
    for f in sorted(glob.glob(str(mc / "replications" / "specimens_*.csv.gz"))):
        d = pd.read_csv(f, low_memory=False)
        if "rep" not in d.columns:
            d["rep"] = int(re.findall(r"(\d+)", Path(f).name)[0])
        d = d[d["In_Window"].astype(bool) & d["Total_TAT_Hours"].notna()]
        frames.append(d[["Type", "Arrival_Minute", "Total_TAT_Hours", "Arrival_Shift", "Outcome", "rep"]])
    if not frames:
        raise SystemExit(f"No replications/specimens_*.csv.gz found in {mc}")
    s = pd.concat(frames, ignore_index=True)
    s["group"] = s["Type"].map(sim_to_group)
    s = s.dropna(subset=["group"])
    s["tat_h"] = s["Total_TAT_Hours"].astype(float)
    s["hour"] = ((s["Arrival_Minute"] % 1440) // 60).astype(int)
    s["shift"] = s["Arrival_Shift"].fillna(pd.Series(shift_of_hour(s["hour"]), index=s.index))
    n_days = (min(w1, s["Arrival_Minute"].max() + 1) - w0) / 1440.0
    return s, rt, n_days


def _find_col(d, wanted):
    low = {c.lower(): c for c in d.columns}
    for w in wanted:
        if w.lower() in low:
            return low[w.lower()]
    return None


def _file_group(path):
    n = Path(path).name.lower().replace("-", "").replace("_", "")
    if "respir" in n or "resp" in n:
        return "Respiratory (non-CF)" if "noncf" in n else ("Respiratory (CF)" if "cf" in n else None)
    return None


def _code(x):
    return re.sub(r"\.0+$", "", str(x).strip()).lstrip("0")


def load_obs(paths, exclude=None):
    """One or more LIS csv files (RAW: specimen_type, TAT_Hours, arrival_datetime). Respiratory_NonCF_/Respiratory_CF_ file
    names force the group."""
    frames = []
    for path in ([paths] if isinstance(paths, (str, Path)) else paths):
        d = pd.read_csv(path, low_memory=False)
        tcol = _find_col(d, ["TAT_Hours", "tat_hours", "Total_TAT_Hours", "TAT", "tat_h"])
        if tcol is None:
            raise SystemExit(f"{path}: no TAT column. Columns are: {list(d.columns)}")
        d = d.rename(columns={tcol: "TAT_Hours"})
        forced = _file_group(path)
        if forced:
            d["group"] = forced
        else:
            scol = _find_col(d, ["specimen_type", "Type", "specimen"])
            if scol is None:
                raise SystemExit(f"{path}: no specimen_type column. Columns are: {list(d.columns)}")
            d["group"] = d[scol].map(lambda x: OBS_TO_GROUP.get(norm(x)))
            miss = d[d["group"].isna()][scol].value_counts()
            if len(miss):
                print(f"  WARNING {Path(path).name}: unmapped specimen_type labels dropped: {dict(miss.head(8))}")
        d = d.dropna(subset=["group"])
        print(f"  {Path(path).name}: {len(d):,} rows -> {dict(d['group'].value_counts())}")
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    if exclude and "source_file" in d.columns:
        d = d[~d["source_file"].astype(str).str.contains(exclude, case=False, regex=False)]
    d["tat_h"] = pd.to_numeric(d["TAT_Hours"], errors="coerce")
    return d.dropna(subset=["tat_h"])


def with_stool_split(df, kind):
    """Add the per-test-code stool rows next to the pooled 'Stool' rows. kind: 'sim' (by Type) | 'obs' (by order_num)."""
    if df is None:
        return None
    if kind == "sim":
        code = df["Type"].map(SIM_STOOL_CODE)
    else:
        ocol = _find_col(df, ["order_num", "order_number", "ordernum", "test_code", "order_code"])
        if ocol is None:
            return df
        code = df[ocol].map(_code).where(df["group"] == "Stool")
    sub = df[code.isin(STOOL_SPLIT)].copy()
    if sub.empty:
        return df
    sub["group"] = code[sub.index].map(STOOL_SPLIT)
    return pd.concat([df, sub], ignore_index=True)


def validation_table(sim, obs25, obs24, n_days, groups=GROUPS_VALIDATION):
    rows = []
    r50 = sim.groupby(["group", "rep"])["tat_h"].quantile(0.5).rename("v").reset_index()
    r95 = sim.groupby(["group", "rep"])["tat_h"].quantile(0.95).rename("v").reset_index()
    for g in groups:
        if g not in set(sim["group"]):
            continue
        s50, c50 = tci(r50[r50.group == g].v)
        s95, c95 = tci(r95[r95.group == g].v)
        row = dict(group=g, sim_per_day=(sim.group == g).sum() / sim.rep.nunique() / max(n_days, 1),
                   sim_p50=s50, sim_p50_ci=c50, sim_p95=s95, sim_p95_ci=c95)
        for lab, o in (("2025", obs25), ("2024", obs24)):
            if o is None or g not in set(o["group"]):
                continue
            x = o[o.group == g]["tat_h"].values
            row.update({f"obs{lab}_n": len(x), f"obs{lab}_p50": np.percentile(x, 50), f"obs{lab}_p95": np.percentile(x, 95)})
            row[f"p50_err_pct_vs{lab}"] = 100 * (s50 - row[f"obs{lab}_p50"]) / row[f"obs{lab}_p50"]
            row[f"p95_err_pct_vs{lab}"] = 100 * (s95 - row[f"obs{lab}_p95"]) / row[f"obs{lab}_p95"]
            ss = sim[sim.group == g]["tat_h"].values
            rng = np.random.default_rng(0)
            row[f"ks_D_vs{lab}"] = stats.ks_2samp(rng.choice(ss, min(len(ss), 20000), replace=False),
                                                  rng.choice(x, min(len(x), 20000), replace=False)).statistic
        rows.append(row)
    return pd.DataFrame(rows)
