#!/usr/bin/env python3
"""
Manuscript figures + tables for the microbiology-lab simulation (reads the Monte Carlo output folders directly).

Every figure is written twice to <out>/ :  <name>_labelled.png  (axis titles)  and  <name>_unlabelled.png
(axis titles removed; tick labels, panel titles, legends and colourbars stay). Canvas and axes positions are IDENTICAL
in both, so they overlay exactly in Affinity Designer.  Tables go to <tables>/ as CSV.

    python make_manuscript_figures_micro.py ^
        --mc-dir results_experiments/mc_20261103_073004 ^
        --obs-2025 data/observed_2025_lis_clean.csv ^
        [--obs-2024 data/observed_2024_lis_clean.csv] ^
        [--obs-month-2024 data/observed_2024_lis_by_specimen_month.csv --obs-month-2025 data/observed_2025_lis_by_specimen_month.csv] ^
        [--scenario baseline=results_experiments/mc_A --scenario no_float=results_experiments/mc_B ...] ^
        [--out manuscript_png] [--tables manuscript_tables]

Inputs
  --mc-dir        a run_montecarlo_and_plot.py folder (replications/specimens_###.csv.gz, state_###.csv.gz, run_table.csv)
  --obs-2025/24   RAW LIS files (columns specimen_type, TAT_Hours, arrival_datetime) -> validation against the sim
  --obs-month-*   by-month LIS files (month, specimen_type, obs_p50, obs_p95, n_samples) -> optional BCx monthly figure
  --scenario      NAME=<mc folder>; the scenario called "baseline" is the reference. Same seeds across scenarios ->
                  differences are paired by replication (common random numbers).
Anything missing is skipped with a message.
"""
import argparse
import calendar
import glob
import re
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
from scipy import stats

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
# display group -> simulation specimen types pooled into it
GROUPS = {
    "Blood culture": ["BCx"], "Body fluid": ["BodyFluid"], "Bone": ["Bone_Cx"], "Tissue": ["Tissue"],
    "Tissue (FNA)": ["Tissue_FNA"], "Tissue (genital)": ["Tissue_genital"], "Wound": ["Wound"],
    "Wound (genital)": ["Wound_Genital"], "Stool": ["Stool"], "Respiratory": ["Respiratory", "Resp_CystFibrosis"],
    "Urine": ["Urine_Invasive", "Urine_NonInvasive"],
}
SIM_TO_GROUP = {s: g for g, ss in GROUPS.items() for s in ss}
# LIS label (letters only, lower case) -> display group
OBS_TO_GROUP = {"bloodculture": "Blood culture", "bodyfluid": "Body fluid", "bone": "Bone", "tissue": "Tissue",
                "fnatissue": "Tissue (FNA)", "genitaltissue": "Tissue (genital)", "wound": "Wound",
                "genitalwound": "Wound (genital)", "woundgenital": "Wound (genital)", "stool": "Stool",
                "respiratory": "Respiratory", "invasiveurine": "Urine", "urine": "Urine"}
SHIFTS = ["Day", "Evening", "Night"]
SHIFT_HOURS = {"Day": (7, 15), "Evening": (15, 23)}          # everything else = Night
BENCH_LABELS = {  # state-file resource -> manuscript label (rows of the utilisation heat-map, in this order)
    "tech_accession": "Accessioning", "tech_float_accession": "Float (accession/plating)", "tech_plating": "Plating",
    "tech_blood": "Blood culture bench", "tech_urine": "Urine bench", "tech_stool": "Stool bench",
    "tech_new": "New-plate bench", "tech_float_newroutine": "Float (new/routine)", "tech_routine": "Routine bench",
    "tech_supervisor": "Supervisor",
}
QUEUE_LABELS = {"Tech_New_Queue_Length": "New-plate bench", "Tech_Routine_Queue_Length": "Routine bench",
                "Tech_Plating_Queue_Length": "Plating", "Tech_Accession_Queue_Length": "Accessioning",
                "Tech_Urine_Queue_Length": "Urine bench", "Tech_Blood_Queue_Length": "Blood culture bench",
                "Tech_Stool_Queue_Length": "Stool bench", "Plating_Queue_Length": "Plating bench (physical)"}
BASELINE_SCENARIO = "baseline"
SHORTAGE_START, SHORTAGE_END = pd.Timestamp("2024-06-11"), pd.Timestamp("2024-11-01")   # bottle shortage (optional fig)
YEAR_COLORS = {2024: "#eb6834", 2025: "#2a78d6"}
DPI = 300

INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SIM_C, OBS_C, OBS24_C = "#2a78d6", "#0b0b0b", "#eb6834"
SHIFT_COLORS = {"Day": "#2a78d6", "Evening": "#eb6834", "Night": "#1baf7a"}
SPEC_FALLBACK = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SEQ = LinearSegmentedColormap.from_list("seq_blue", ["#cde2fb", "#6da7ec", "#256abf", "#104281"])

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.8,
    "xtick.major.width": 0.8, "ytick.major.width": 0.8, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.5, "axes.axisbelow": True, "figure.facecolor": "white", "axes.facecolor": "white",
    "pdf.fonttype": 42, "svg.fonttype": "none",
})
OUT, TAB = Path("manuscript_png"), Path("manuscript_tables")


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def save_both(fig, stem):
    fig.savefig(OUT / f"{stem}_labelled.png", dpi=DPI, facecolor="white")
    for ax in fig.axes:
        ax.set_xlabel("")
        ax.set_ylabel("")
    fig.savefig(OUT / f"{stem}_unlabelled.png", dpi=DPI, facecolor="white")
    plt.close(fig)
    print(f"  wrote {stem}")


def top_legend(ax, handles=None, ncol=4):
    kw = dict(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=ncol, frameon=False, handlelength=1.6,
              columnspacing=1.2)
    ax.legend(handles=handles, **kw) if handles is not None else ax.legend(**kw)


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


def run(label, fn, *a):
    try:
        fn(*a)
    except Exception as e:
        print(f"  SKIPPED {label}: {type(e).__name__}: {e}")


# ----------------------------------------------------------------------------
# loading
# ----------------------------------------------------------------------------
def load_sim(mc_dir):
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
        raise SystemExit(f"no replications/specimens_*.csv.gz in {mc}")
    s = pd.concat(frames, ignore_index=True)
    s["group"] = s["Type"].map(SIM_TO_GROUP)
    s = s.dropna(subset=["group"])
    s["tat_h"] = s["Total_TAT_Hours"].astype(float)
    s["hour"] = ((s["Arrival_Minute"] % 1440) // 60).astype(int)
    s["shift"] = s["Arrival_Shift"].fillna(pd.Series(shift_of_hour(s["hour"]), index=s.index))
    n_days = (min(w1, s["Arrival_Minute"].max() + 1) - w0) / 1440.0
    return s, rt, n_days


def load_state(mc_dir, rt):
    mc = Path(mc_dir)
    w0 = float(rt["window_start_min"].iloc[0]) / 1440 if "window_start_min" in rt else 0.0
    w1 = float(rt["window_end_min"].iloc[0]) / 1440 if "window_end_min" in rt else np.inf
    frames = []
    for f in sorted(glob.glob(str(mc / "replications" / "state_*.csv.gz"))):
        d = pd.read_csv(f, low_memory=False)
        d["rep"] = int(re.findall(r"(\d+)", Path(f).name)[0])
        if "Day" in d.columns:
            d = d[(d["Day"] >= w0) & (d["Day"] < w1)]
        frames.append(d)
    if not frames:
        raise SystemExit("no state_*.csv.gz")
    st = pd.concat(frames, ignore_index=True)
    st["hod"] = (st["Hour"] % 24).astype(int)
    st["shift"] = shift_of_hour(st["hod"])
    return st


def load_obs(paths):
    """paths: one or more LIS csv files (e.g. the main 2025 file plus Respiratory_NonCF_2025.csv and
    Respiratory_CF_2025.csv). A file whose NAME contains 'respir' is assigned to the Respiratory group
    regardless of its specimen_type labels."""
    frames = []
    for path in ([paths] if isinstance(paths, str) else paths):
        d = pd.read_csv(path, low_memory=False)
        forced = "Respiratory" if "respir" in Path(path).name.lower() else None
        d["group"] = forced if forced else d["specimen_type"].map(lambda x: OBS_TO_GROUP.get(norm(x)))
        miss = d[d["group"].isna()]["specimen_type"].value_counts()
        if len(miss):
            print(f"  WARNING {Path(path).name}: unmapped specimen_type labels dropped: {dict(miss.head(8))}")
        frames.append(d.dropna(subset=["group"]))
    d = pd.concat(frames, ignore_index=True)
    d["tat_h"] = pd.to_numeric(d["TAT_Hours"], errors="coerce")
    d = d.dropna(subset=["tat_h"])
    if "arrival_datetime" in d.columns:
        t = pd.to_datetime(d["arrival_datetime"], errors="coerce")
        d["hour"] = t.dt.hour
        d["shift"] = np.where(t.notna(), shift_of_hour(t.dt.hour.fillna(0).astype(int)), None)
    print("  LIS rows per group: " + ", ".join(f"{g}={n}" for g, n in d["group"].value_counts().items()))
    return d


# ----------------------------------------------------------------------------
# tables
# ----------------------------------------------------------------------------
def rep_percentiles(sim, q, by="group"):
    return sim.groupby([by, "rep"])["tat_h"].quantile(q).rename("v").reset_index()


def validation_table(sim, obs25, obs24, n_days):
    rows = []
    r50, r95 = rep_percentiles(sim, 0.5), rep_percentiles(sim, 0.95)
    for g in GROUPS:
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
            ks = stats.ks_2samp(rng.choice(ss, min(len(ss), 20000), replace=False),
                                rng.choice(x, min(len(x), 20000), replace=False)).statistic
            row[f"ks_D_vs{lab}"] = ks
            if lab == "2025":
                row["obs_per_day"] = len(x) / 365.0
        rows.append(row)
    t = pd.DataFrame(rows)
    t.to_csv(TAB / "table2_validation.csv", index=False, float_format="%.2f")
    return t


def utilization_table(st):
    rows = []
    for b, lab in BENCH_LABELS.items():
        ci, cc = f"Res_{b}_in_use", f"Res_{b}_capacity"
        if ci not in st or cc not in st:
            continue
        d = st[st[cc] > 0]
        for sh in SHIFTS:
            x = d[d["shift"] == sh]
            if len(x):
                u = 100 * x[ci] / x[cc]
                rows.append(dict(bench=lab, shift=sh, mean_staff=x[cc].mean(), mean_util_pct=u.mean(),
                                 p95_util_pct=np.percentile(u, 95),
                                 pct_time_saturated=100 * (x[ci] >= x[cc]).mean()))
    t = pd.DataFrame(rows)
    t.to_csv(TAB / "table3_utilization_by_shift.csv", index=False, float_format="%.1f")
    return t


# ----------------------------------------------------------------------------
# figures
# ----------------------------------------------------------------------------
def fig_validation_dumbbell(tab):
    order = list(tab.sort_values("obs2025_p50" if "obs2025_p50" in tab else "sim_p50")["group"])
    for stat, ttl in (("p50", "Median TAT (h)"), ("p95", "95th percentile TAT (h)")):
        fig, ax = plt.subplots(figsize=(3.6, 0.3 * len(order) + 1.4))
        fig.subplots_adjust(left=0.33, right=0.97, bottom=0.17, top=0.84)
        for k, g in enumerate(order):
            r = tab[tab.group == g].iloc[0]
            if f"obs2025_{stat}" in r and pd.notna(r.get(f"obs2025_{stat}")):
                ax.plot([r[f"sim_{stat}"], r[f"obs2025_{stat}"]], [k, k], color=GRID, linewidth=2.2, zorder=1)
                ax.scatter(r[f"obs2025_{stat}"], k, marker="D", s=26, color=OBS_C, zorder=4)
            if f"obs2024_{stat}" in r and pd.notna(r.get(f"obs2024_{stat}")):
                ax.scatter(r[f"obs2024_{stat}"], k, marker="D", s=26, facecolor="white", edgecolor=OBS24_C,
                           linewidth=1.0, zorder=3)
            ax.errorbar(r[f"sim_{stat}"], k, xerr=r[f"sim_{stat}_ci"] if pd.notna(r[f"sim_{stat}_ci"]) else 0, fmt="o",
                        markersize=4.6, color=SIM_C, ecolor=SIM_C, elinewidth=1, markeredgecolor="white",
                        markeredgewidth=0.6, zorder=5)
        ax.set_yticks(range(len(order)))
        ax.set_yticklabels(order)
        ax.set_ylim(-0.6, len(order) - 0.4)
        ax.set_xlim(left=0)
        ax.grid(axis="y", visible=False)
        ax.set_xlabel(ttl)
        ax.set_ylabel("Specimen type")
        h = [Line2D([0], [0], marker="o", color="w", markerfacecolor=SIM_C, markersize=5, label="Simulated (mean, 95% CI)"),
             Line2D([0], [0], marker="D", color="w", markerfacecolor=OBS_C, markersize=5, label="LIS 2025")]
        if "obs2024_p50" in tab:
            h.append(Line2D([0], [0], marker="D", color="w", markerfacecolor="white", markeredgecolor=OBS24_C,
                            markersize=5, label="LIS 2024"))
        top_legend(ax, h, ncol=2)
        save_both(fig, f"01{'a' if stat == 'p50' else 'b'}_validation_{stat}")


def fig_agreement(tab):
    fig, ax = plt.subplots(figsize=(3.5, 3.5))
    fig.subplots_adjust(left=0.16, right=0.97, bottom=0.15, top=0.88)
    lo, hi = 20, 500
    xs = np.array([lo, hi])
    ax.plot(xs, xs, color=INK, linewidth=0.8)
    ax.fill_between(xs, xs * 0.8, xs * 1.2, color=GRID, alpha=0.6, lw=0, zorder=0)
    txt = []
    for stat, filled, mk in (("p50", True, "o"), ("p95", False, "s")):
        c = f"obs2025_{stat}"
        if c not in tab:
            continue
        d = tab.dropna(subset=[c])
        ax.scatter(d[c], d[f"sim_{stat}"], s=26, marker=mk, color=SIM_C if filled else "white",
                   edgecolor=SIM_C, linewidth=1.1, zorder=3)
        mape = (100 * (d[f"sim_{stat}"] - d[c]).abs() / d[c]).mean()
        r2 = np.corrcoef(np.log(d[c]), np.log(d[f"sim_{stat}"]))[0, 1] ** 2
        txt.append(f"{stat.upper()}: MAPE {mape:.0f}%, R² {r2:.2f}")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal")
    ax.text(0.04, 0.96, "\n".join(txt), transform=ax.transAxes, va="top", fontsize=7, color=INK2)
    ax.set_xlabel("Observed TAT, LIS 2025 (h, log scale)")
    ax.set_ylabel("Simulated TAT (h, log scale)")
    h = [Line2D([0], [0], marker="o", color="w", markerfacecolor=SIM_C, markersize=5, label="Median"),
         Line2D([0], [0], marker="s", color="w", markerfacecolor="white", markeredgecolor=SIM_C, markersize=5,
                label="95th percentile"),
         Line2D([0], [0], color=GRID, linewidth=6, label="±20%")]
    top_legend(ax, h, ncol=3)
    save_both(fig, "02_agreement_obs_vs_sim")


def fig_ecdf_grid(sim, obs25, obs24):
    groups = [g for g in GROUPS if g in set(sim["group"])]
    ncol = 3
    nrow = int(np.ceil(len(groups) / ncol))
    fig, axs = plt.subplots(nrow, ncol, figsize=(7.2, 1.75 * nrow + 0.5), squeeze=False)
    fig.subplots_adjust(left=0.08, right=0.99, bottom=0.10, top=0.93, hspace=0.62, wspace=0.28)
    for i, g in enumerate(groups):
        ax = axs[i // ncol][i % ncol]
        s = np.sort(sim[sim.group == g]["tat_h"].values)
        ax.step(s, np.arange(1, len(s) + 1) / len(s), where="post", color=SIM_C, linewidth=1.4)
        for o, c, ls in ((obs25, OBS_C, "--"), (obs24, OBS24_C, ":")):
            if o is not None and g in set(o["group"]):
                v = np.sort(o[o.group == g]["tat_h"].values)
                ax.step(v, np.arange(1, len(v) + 1) / len(v), where="post", color=c, linewidth=1.2, linestyle=ls)
        ax.set_xscale("log")
        ax.set_ylim(0, 1.02)
        ax.set_title(g, fontsize=7.5, fontweight="bold", loc="left")
        if obs25 is not None and g in set(obs25["group"]):
            x = obs25[obs25.group == g]["tat_h"].values
            rng = np.random.default_rng(0)
            ks = stats.ks_2samp(rng.choice(s, min(len(s), 20000), replace=False),
                                rng.choice(x, min(len(x), 20000), replace=False)).statistic
            ax.text(0.97, 0.06, f"D = {ks:.2f}", transform=ax.transAxes, ha="right", fontsize=6.5, color=INK2)
        if i // ncol == nrow - 1 or i + ncol >= len(groups):
            ax.set_xlabel("TAT (h, log scale)")
        if i % ncol == 0:
            ax.set_ylabel("Cumulative proportion")
    for j in range(len(groups), nrow * ncol):
        axs[j // ncol][j % ncol].axis("off")
    h = [Line2D([0], [0], color=SIM_C, linewidth=1.4, label="Simulated"),
         Line2D([0], [0], color=OBS_C, linewidth=1.2, linestyle="--", label="LIS 2025")]
    if obs24 is not None:
        h.append(Line2D([0], [0], color=OBS24_C, linewidth=1.2, linestyle=":", label="LIS 2024"))
    fig.legend(handles=h, loc="upper center", ncol=len(h), frameon=False, bbox_to_anchor=(0.5, 1.0))
    save_both(fig, "03_ecdf_by_specimen_type")


def fig_arrival_profile(sim, obs25, n_days):
    if obs25 is None or "hour" not in obs25:
        raise RuntimeError("observed file has no arrival_datetime")
    hs = sim.groupby("hour").size().reindex(range(24), fill_value=0)
    ho = obs25.dropna(subset=["hour"]).groupby("hour").size().reindex(range(24), fill_value=0)
    fig, ax = plt.subplots(figsize=(3.5, 2.6))
    fig.subplots_adjust(left=0.15, right=0.98, bottom=0.17, top=0.88)
    ax.plot(range(24), 100 * hs / hs.sum(), color=SIM_C, linewidth=1.6, label="Simulated")
    ax.plot(range(24), 100 * ho / ho.sum(), color=OBS_C, linewidth=1.4, linestyle="--", label="LIS 2025")
    for a, b in ((23, 24), (0, 7)):
        ax.axvspan(a - 0.5, b - 0.5, color="#f0efec", zorder=0, lw=0)
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlim(-0.5, 23.5)
    ax.set_ylim(bottom=0)
    ax.grid(axis="x", visible=False)
    ax.set_xlabel("Hour of arrival")
    ax.set_ylabel("Share of arrivals (%)")
    top_legend(ax, ncol=2)
    save_both(fig, "04_arrival_profile")


def fig_utilization_heatmap(st):
    benches = [b for b in BENCH_LABELS if f"Res_{b}_in_use" in st and f"Res_{b}_capacity" in st]
    M = np.full((len(benches), 24), np.nan)
    for i, b in enumerate(benches):
        d = st[st[f"Res_{b}_capacity"] > 0]
        u = (100 * d[f"Res_{b}_in_use"] / d[f"Res_{b}_capacity"]).groupby(d["hod"]).mean()
        M[i, u.index.values] = u.values
    cmap = SEQ.copy()
    cmap.set_bad("#f0efec")
    fig = plt.figure(figsize=(5.0, 0.3 * len(benches) + 1.1))
    ax = fig.add_axes([0.30, 0.17, 0.55, 0.72])
    cax = fig.add_axes([0.88, 0.17, 0.025, 0.72])
    im = ax.imshow(np.ma.masked_invalid(M), cmap=cmap, vmin=0, vmax=100, aspect="auto")
    ax.grid(False)
    ax.set_xticks(range(0, 24, 3))
    ax.set_yticks(range(len(benches)))
    ax.set_yticklabels([BENCH_LABELS[b] for b in benches])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    cb = fig.colorbar(im, cax=cax)
    cb.outline.set_visible(False)
    cb.ax.tick_params(length=2, labelsize=7)
    cb.set_label("Utilisation (%)")
    cb.ax.grid(False)
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Bench")
    save_both(fig, "05_utilization_heatmap")


def fig_queues(st):
    cols = [c for c in QUEUE_LABELS if c in st]
    m = st.groupby(["rep", "hod"])[cols].mean().reset_index()
    top = sorted(cols, key=lambda c: -m.groupby("hod")[c].mean().max())[:5]
    fig, ax = plt.subplots(figsize=(3.6, 2.8))
    fig.subplots_adjust(left=0.16, right=0.98, bottom=0.17, top=0.80)
    for k, c in enumerate(top):
        g = m.groupby("hod")[c]
        mu, sd = g.mean(), g.std().fillna(0)
        ax.plot(mu.index, mu.values, color=SPEC_FALLBACK[k % 8], linewidth=1.6, label=QUEUE_LABELS[c])
        ax.fill_between(mu.index, mu - 1.96 * sd, mu + 1.96 * sd, color=SPEC_FALLBACK[k % 8], alpha=0.15, lw=0)
    for a, b in ((23, 24), (0, 7)):
        ax.axvspan(a - 0.5, b - 0.5, color="#f0efec", zorder=0, lw=0)
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlim(-0.5, 23.5)
    ax.set_ylim(bottom=0)
    ax.grid(axis="x", visible=False)
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Specimens waiting (mean)")
    top_legend(ax, ncol=2)
    save_both(fig, "06_queue_by_hour")


def fig_shift_p95(sim, obs25):
    groups = [g for g in GROUPS if g in set(sim["group"])]
    r = sim.groupby(["group", "shift", "rep"])["tat_h"].quantile(0.95).reset_index()
    fig, ax = plt.subplots(figsize=(3.7, 0.42 * len(groups) + 1.2))
    fig.subplots_adjust(left=0.30, right=0.97, bottom=0.15, top=0.86)
    step = 0.7 / 3
    for k, g in enumerate(groups):
        for j, sh in enumerate(SHIFTS):
            y = k - 0.35 + step * (j + 0.5)
            mu, ci = tci(r[(r.group == g) & (r["shift"] == sh)]["tat_h"])
            if np.isfinite(mu):
                ax.errorbar(mu, y, xerr=0 if not np.isfinite(ci) else ci, fmt="o", markersize=3.8, color=SHIFT_COLORS[sh],
                            ecolor=SHIFT_COLORS[sh], elinewidth=0.9, markeredgecolor="white", markeredgewidth=0.4)
            if obs25 is not None and "shift" in obs25:
                x = obs25[(obs25.group == g) & (obs25["shift"] == sh)]["tat_h"].values
                if len(x) > 20:
                    ax.scatter(np.percentile(x, 95), y, marker="D", s=12, facecolor="white", edgecolor=SHIFT_COLORS[sh],
                               linewidth=0.9, zorder=4)
    ax.set_yticks(range(len(groups)))
    ax.set_yticklabels(groups)
    ax.set_ylim(-0.6, len(groups) - 0.4)
    ax.invert_yaxis()
    ax.set_xlim(left=0)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("95th percentile TAT (h)")
    ax.set_ylabel("Specimen type")
    h = [Line2D([0], [0], marker="o", color="w", markerfacecolor=SHIFT_COLORS[s], markersize=5, label=s) for s in SHIFTS]
    h += [Line2D([0], [0], marker="o", color="w", markerfacecolor=MUTED, markersize=5, label="Simulated"),
          Line2D([0], [0], marker="D", color="w", markerfacecolor="white", markeredgecolor=MUTED, markersize=5,
                 label="LIS 2025")]
    top_legend(ax, h, ncol=3)
    save_both(fig, "07_p95_by_arrival_shift")


def fig_bcx_monthly(m24, m25):
    a, b = pd.read_csv(m24), pd.read_csv(m25)
    mon = {calendar.month_abbr[i]: i for i in range(1, 13)}
    for name, col, ylab in (("08a_bcx_monthly_p50", "obs_p50", "Median TAT (h)"), ("08b_bcx_monthly_p95", "obs_p95", "95th percentile TAT (h)"),
                            ("08c_bcx_monthly_volume", "n_samples", "Blood cultures per month")):
        fig, ax = plt.subplots(figsize=(3.5, 2.7))
        fig.subplots_adjust(left=0.16, right=0.98, bottom=0.17, top=0.88)
        x0 = SHORTAGE_START.month - 0.5 + (SHORTAGE_START.day - 1) / 30
        x1 = SHORTAGE_END.month - 0.5 + (SHORTAGE_END.day - 1) / 31
        ax.axvspan(x0, x1, color=YEAR_COLORS[2024], alpha=0.12, lw=0, zorder=0)
        for y, d in ((2024, a), (2025, b)):
            d = d[d["specimen_type"].map(norm) == "bloodculture"].copy()
            d["m"] = d["month"].map(lambda v: mon.get(str(v)[:3], v)).astype(int)
            d = d.sort_values("m")
            ax.plot(d["m"], d[col], color=YEAR_COLORS[y], linewidth=1.8, marker="o", markersize=4, markeredgecolor="white",
                    markeredgewidth=0.8)
        ax.set_xticks(range(1, 13))
        ax.set_xticklabels([calendar.month_abbr[i] for i in range(1, 13)], rotation=45, ha="right")
        ax.set_xlim(0.5, 12.5)
        ax.set_ylim(bottom=0)
        ax.grid(axis="x", visible=False)
        ax.set_xlabel("Month")
        ax.set_ylabel(ylab)
        h = [Line2D([0], [0], color=YEAR_COLORS[y], marker="o", markersize=4, label=str(y)) for y in (2024, 2025)]
        h.append(plt.Rectangle((0, 0), 1, 1, facecolor=YEAR_COLORS[2024], alpha=0.25, label="Bottle shortage"))
        top_legend(ax, h, ncol=3)
        save_both(fig, name)


def scenario_frames(specs):
    out = []
    for name, folder in specs:
        s, _, _ = load_sim(folder)
        r = s.groupby(["group", "rep"])["tat_h"].agg(p50=lambda x: np.percentile(x, 50), p95=lambda x: np.percentile(x, 95),
                                                      n="size").reset_index()
        r["scenario"] = name
        out.append(r)
    return pd.concat(out, ignore_index=True)


def fig_scenarios(scn):
    base = scn[scn.scenario == BASELINE_SCENARIO]
    if base.empty:
        raise RuntimeError(f"no scenario named '{BASELINE_SCENARIO}'")
    allrows = []
    for metric, xlabel, stem in (("p95", "Δ 95th percentile TAT vs baseline (h)", "09a_scenarios_delta_p95"),
                                 ("p50", "Δ median TAT vs baseline (h)", "09b_scenarios_delta_p50")):
        m = scn[scn.scenario != BASELINE_SCENARIO].merge(base[["group", "rep", metric]].rename(columns={metric: "b"}),
                                                          on=["group", "rep"])
        m["delta"] = m[metric] - m["b"]
        g = m.groupby(["scenario", "group"])["delta"]
        s = pd.DataFrame({"mean": g.mean(), "se": g.sem(), "n": g.count()}).reset_index()
        s["ci"] = stats.t.ppf(0.975, (s["n"] - 1).clip(lower=1)) * s["se"]
        s["metric"] = metric
        allrows.append(s)
        scens = list(dict.fromkeys(m["scenario"]))
        groups = [g_ for g_ in GROUPS if g_ in set(s["group"])]
        colors = {g_: SPEC_FALLBACK[i % 8] for i, g_ in enumerate(groups)}
        fig, ax = plt.subplots(figsize=(3.9, 0.7 * len(scens) + 1.6))
        fig.subplots_adjust(left=0.34, right=0.95, bottom=0.17, top=0.74)
        step = 0.8 / max(len(groups), 1)
        for i, sc in enumerate(scens):
            for j, g_ in enumerate(groups):
                r = s[(s.scenario == sc) & (s.group == g_)]
                if r.empty:
                    continue
                y = i - 0.4 + step * (j + 0.5)
                ax.errorbar(r["mean"].iloc[0], y, xerr=r["ci"].iloc[0], fmt="o", markersize=3.4, color=colors[g_],
                            ecolor=colors[g_], elinewidth=0.9, markeredgecolor="white", markeredgewidth=0.4)
        ax.axvline(0, color=INK, linewidth=0.8)
        ax.set_yticks(range(len(scens)))
        ax.set_yticklabels([textwrap.fill(x.replace("_", " "), 18) for x in scens])
        ax.set_ylim(-0.6, len(scens) - 0.4)
        ax.invert_yaxis()
        ax.grid(axis="y", visible=False)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Scenario")
        h = [Line2D([0], [0], marker="o", color="w", markerfacecolor=colors[g_], markersize=5, label=g_) for g_ in groups]
        top_legend(ax, h, ncol=3)
        save_both(fig, stem)
    pd.concat(allrows).to_csv(TAB / "table4_scenarios.csv", index=False, float_format="%.3f")


# ----------------------------------------------------------------------------
def main():
    global OUT, TAB
    ap = argparse.ArgumentParser()
    ap.add_argument("--mc-dir", required=True)
    ap.add_argument("--obs-2025", nargs="+", help="one or more LIS 2025 csv files (add Respiratory_NonCF_2025.csv Respiratory_CF_2025.csv here)")
    ap.add_argument("--obs-2024", nargs="+")
    ap.add_argument("--obs-month-2024")
    ap.add_argument("--obs-month-2025")
    ap.add_argument("--scenario", action="append", default=[], help="NAME=<mc folder> (repeat); 'baseline' is the reference")
    ap.add_argument("--out", default="manuscript_png")
    ap.add_argument("--tables", default="manuscript_tables")
    a = ap.parse_args()
    OUT, TAB = Path(a.out), Path(a.tables)
    OUT.mkdir(parents=True, exist_ok=True)
    TAB.mkdir(parents=True, exist_ok=True)

    sim, rt, n_days = load_sim(a.mc_dir)
    st = load_state(a.mc_dir, rt)
    obs25 = load_obs(a.obs_2025) if a.obs_2025 else None
    obs24 = load_obs(a.obs_2024) if a.obs_2024 else None
    print(f"sim: {len(sim):,} in-window specimens, {sim.rep.nunique()} replications, {n_days:.0f} measured days")

    print("Tables")
    tab = validation_table(sim, obs25, obs24, n_days)
    utilization_table(st)

    print("Figures")
    if obs25 is not None:
        run("validation dumbbell", fig_validation_dumbbell, tab)
        run("agreement", fig_agreement, tab)
        run("arrival profile", fig_arrival_profile, sim, obs25, n_days)
    run("ecdf grid", fig_ecdf_grid, sim, obs25, obs24)
    run("utilisation heat-map", fig_utilization_heatmap, st)
    run("queues", fig_queues, st)
    run("p95 by shift", fig_shift_p95, sim, obs25)
    if a.obs_month_2024 and a.obs_month_2025:
        run("bcx monthly", fig_bcx_monthly, a.obs_month_2024, a.obs_month_2025)
    if a.scenario:
        specs = [tuple(s.split("=", 1)) for s in a.scenario]
        run("scenarios", lambda: fig_scenarios(scenario_frames(specs)))
    print(f"\nDone. PNGs in {OUT}/  tables in {TAB}/")


if __name__ == "__main__":
    main()
