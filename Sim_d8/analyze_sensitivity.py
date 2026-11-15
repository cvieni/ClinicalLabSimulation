#!/usr/bin/env python
"""Turn the sensitivity runs into the tornado figure, a parameter x specimen-type heat-map and tables.

    python analyze_sensitivity.py --dir results_experiments/sens --obs observed_lis_month.csv --out sensitivity_out

Primary outcome: % change in TAT (p95 and p50), averaged over specimen types, LOW and HIGH value of each parameter vs baseline.
Changes are paired by replication (same seeds), 95 % CI = t-interval over replications. Types with fewer than --min-n completed
specimens per replication, and --exclude types, are left out of the average (noisy p95).
A parameter whose output is IDENTICAL to baseline in every replication is reported as NO EFFECT: with common random numbers that
means the simulator never read it (a dead parameter), which is a finding in itself.
If --obs is given (Type,P50,P95 from make_observed_from_lis.py) a third panel shows how each assumption moves the mean absolute
error of the simulated median against the LIS (percentage points; positive = worse agreement).
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from components import results_loader as rl
from sensitivity_params import PARAMS

LO_C, HI_C = "#2a78d6", "#eb6834"
EXCLUDE_DEFAULT = ["Wound_Genital", "Tissue_FNA", "Tissue_genital"]


def pivot(summary, metric, types):
    s = summary[summary["type"].isin(types)]
    return s.pivot_table(index="rep", columns="type", values=metric)


def eligible_types(base_summary, min_n, exclude):
    n = base_summary.groupby("type")["n"].mean()
    return sorted(t for t, v in n.items() if v >= min_n and t not in exclude)


def paired_mean_effect(a, b, pct=True):
    """a, b: rep x type tables. Mean over types per replication, then t-CI over replications."""
    common = a.index.intersection(b.index)
    cols = a.columns.intersection(b.columns)
    if len(common) < 2 or len(cols) == 0:
        return np.nan, np.nan, len(common), False
    A, B = a.loc[common, cols], b.loc[common, cols]
    identical = bool(np.allclose(A.to_numpy(), B.to_numpy(), rtol=0, atol=1e-9, equal_nan=True))
    d = ((A - B) / B * 100.0) if pct else (A - B)
    per_rep = d.mean(axis=1)
    m, ci, n = rl.mean_ci(per_rep)
    return m, ci, n, identical


def mae_vs_obs(summary, obs, metric):
    s = summary.groupby("type")[metric].mean()
    col = metric.upper()
    o = obs.drop_duplicates("Type").set_index("Type")[col]
    both = s.index.intersection(o.index)
    if len(both) == 0:
        return np.nan
    return float((100 * (s[both] - o[both]).abs() / o[both]).mean())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="results_experiments/sens")
    ap.add_argument("--baseline-dir", default=None)
    ap.add_argument("--out", default="sensitivity_out")
    ap.add_argument("--obs", default=None)
    ap.add_argument("--min-n", type=float, default=30, help="minimum mean completed specimens per replication for a type to count")
    ap.add_argument("--exclude", nargs="*", default=EXCLUDE_DEFAULT)
    ap.add_argument("--top", type=int, default=15, help="parameters in the main-text tornado (the full one is always written)")
    ap.add_argument("--recompute", action="store_true", help="ignore the per-folder cache")
    a = ap.parse_args()

    root = Path(a.dir)
    base_dir = Path(a.baseline_dir) if a.baseline_dir else root / "_baseline"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    def src(path, label):
        return dict(id="scenario|" + str(path), kind="scenario", label=label, path=str(path))

    base = rl.load_source(src(base_dir, "baseline"), use_cache=not a.recompute)
    types = eligible_types(base["summary"], a.min_n, set(a.exclude))
    print(f"baseline: {base['summary']['rep'].nunique()} replications; {len(types)} types in the averages: {types}")
    obs = pd.read_csv(a.obs) if a.obs else None

    meta = {e["name"]: e for e in PARAMS}
    import json
    rows, rows_type = [], []
    for folder in sorted(root.glob("*__*")):
        if not (folder / "run_table.csv").exists():
            continue
        name, lev = folder.name.rsplit("__", 1)
        d = rl.load_source(src(folder, folder.name), use_cache=not a.recompute)
        ov = json.loads((folder / "scenario_overrides.json").read_text()) if (folder / "scenario_overrides.json").exists() else {}
        rec = dict(param=name, level=lev, value=json.dumps(ov.get(name, ov)), group=meta.get(name, {}).get("group", ""))
        ident = True
        for metric in ("p95", "p50"):
            m, ci, n, same = paired_mean_effect(pivot(d["summary"], metric, types), pivot(base["summary"], metric, types))
            rec.update({f"{metric}_pct": m, f"{metric}_ci": ci, "n_reps": n})
            ident &= same
        # unfinished (right-censored) specimens
        for dd, key in ((d, "unf"), (base, "unf_b")):
            r = dd["runs"]
            rec[key] = 100.0 * r["n_incomplete_in_window"].sum() / max(r["n_in_window"].sum(), 1) if {"n_incomplete_in_window", "n_in_window"} <= set(r.columns) else np.nan
        rec["unfinished_pp"] = rec.pop("unf") - rec.pop("unf_b")
        if obs is not None:
            for metric in ("p50", "p95"):
                rec[f"mae_{metric}_pp"] = mae_vs_obs(d["summary"][d["summary"]["type"].isin(types)], obs, metric) - \
                                          mae_vs_obs(base["summary"][base["summary"]["type"].isin(types)], obs, metric)
        rec["no_effect"] = bool(ident)
        rows.append(rec)
        for metric in ("p50", "p95"):
            dl = rl.paired_delta({"b": base, "s": d}, "b", metric, types, pct=True)
            for _, r in dl.iterrows():
                rows_type.append(dict(param=name, level=lev, type=r["type"], metric=metric, delta_pct=r["delta"], ci=r["ci"]))
    if not rows:
        sys.exit(f"no finished <param>__lo/hi folders under {root}")
    lev = pd.DataFrame(rows)
    lev.to_csv(out / "sensitivity_levels.csv", index=False, float_format="%.3f")
    pd.DataFrame(rows_type).to_csv(out / "sensitivity_by_type.csv", index=False, float_format="%.3f")

    # ---- ranking
    rk = []
    for name, g in lev.groupby("param"):
        eff = g[["p95_pct", "p50_pct"]].abs().max().max()
        row = dict(param=name, group=g["group"].iloc[0], max_abs_p95_pct=g["p95_pct"].abs().max(), max_abs_p50_pct=g["p50_pct"].abs().max(),
                   significant=bool(any((g["p95_pct"].abs() > g["p95_ci"].fillna(0)) | (g["p50_pct"].abs() > g["p50_ci"].fillna(0)))),
                   no_effect=bool(g["no_effect"].all()), levels=", ".join(g["level"]))
        for lv in ("lo", "hi"):
            x = g[g["level"] == lv]
            row[f"{lv}_value"] = x["value"].iloc[0] if len(x) else ""
            row[f"{lv}_p95_pct"] = x["p95_pct"].iloc[0] if len(x) else np.nan
        rk.append(row)
    rk = pd.DataFrame(rk).sort_values("max_abs_p95_pct", ascending=False)
    rk["verdict"] = np.where(rk["no_effect"], "NO EFFECT (identical output: parameter probably unused)",
                             np.where(~rk["significant"], "within replication noise", np.where(rk["max_abs_p95_pct"] >= 5, "influential (>=5 % change)", "small")))
    rk.to_csv(out / "sensitivity_ranking.csv", index=False, float_format="%.3f")
    print("\n", rk[["param", "max_abs_p95_pct", "max_abs_p50_pct", "verdict"]].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    dead = rk[rk["no_effect"]]["param"].tolist()
    if dead:
        print("\nNO EFFECT under identical seeds (check these are really read by the simulator):", ", ".join(dead))

    # ---- tornado
    def tornado(order, fname, title):
        panels = [("p95_pct", "p95_ci", "Change in 95th percentile TAT (%)"), ("p50_pct", "p50_ci", "Change in median TAT (%)")]
        if obs is not None and "mae_p50_pp" in lev:
            panels.append(("mae_p50_pp", None, "Change in median error vs LIS (pp; + = worse)"))
        fig, axes = plt.subplots(1, len(panels), figsize=(4.6 * len(panels) + 3.2, 0.36 * len(order) + 1.8), sharey=True)
        axes = np.atleast_1d(axes)
        y = np.arange(len(order))[::-1]
        labels = []
        for nme in order:
            r = rk[rk["param"] == nme].iloc[0]
            labels.append(f"{nme}  [{r['lo_value'] or '-'} | {r['hi_value'] or '-'}]")
        for ax, (col, cicol, xl) in zip(axes, panels):
            for yy, nme in zip(y, order):
                for lv, c, off in (("lo", LO_C, 0.18), ("hi", HI_C, -0.18)):
                    x = lev[(lev["param"] == nme) & (lev["level"] == lv)]
                    if x.empty or not np.isfinite(x[col].iloc[0]):
                        continue
                    v = x[col].iloc[0]
                    ax.barh(yy + off, v, height=0.32, color=c, alpha=0.9, zorder=2)
                    if cicol and np.isfinite(x[cicol].iloc[0]):
                        ax.errorbar(v, yy + off, xerr=x[cicol].iloc[0], color="k", lw=0.8, capsize=1.5, zorder=3)
            ax.axvline(0, color="0.3", lw=0.8)
            ax.set_xlabel(xl, fontsize=9)
            ax.grid(axis="x", alpha=0.25, zorder=0)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
        axes[0].set_yticks(y)
        axes[0].set_yticklabels(labels, fontsize=8)
        h = [plt.Rectangle((0, 0), 1, 1, color=LO_C), plt.Rectangle((0, 0), 1, 1, color=HI_C)]
        fig.legend(h, ["low value", "high value"], loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 1.0))
        fig.suptitle(title, y=1.02, fontsize=10, fontweight="bold")
        fig.tight_layout()
        fig.savefig(out / fname, dpi=300, bbox_inches="tight")
        plt.close(fig)

    order_all = rk["param"].tolist()
    tornado(order_all[::-1][::-1], "sens_tornado_all.png", "One-at-a-time sensitivity to assumed parameters (mean over specimen types; 95% CI over replications)")
    tornado(order_all[:a.top], f"sens_tornado_top{a.top}.png", f"Top {a.top} assumed parameters by effect on p95 TAT")

    # ---- heat-map: parameter x type, level with the larger effect
    bt = pd.DataFrame(rows_type)
    bt = bt[bt["metric"] == "p95"]
    if not bt.empty:
        pick = []
        for nme in order_all:
            g = lev[lev["param"] == nme]
            if g.empty:
                continue
            lv = g.loc[g["p95_pct"].abs().idxmax(), "level"] if g["p95_pct"].notna().any() else g["level"].iloc[0]
            pick.append((nme, lv))
        M = pd.DataFrame({f"{n} ({l})": bt[(bt["param"] == n) & (bt["level"] == l)].set_index("type")["delta_pct"] for n, l in pick}).T
        M = M.reindex(columns=types)
        zmax = max(5.0, float(np.nanmax(np.abs(M.to_numpy()))))
        fig, ax = plt.subplots(figsize=(0.62 * len(types) + 4.5, 0.3 * len(M) + 1.6))
        im = ax.imshow(M.to_numpy(), aspect="auto", cmap="RdBu_r", vmin=-zmax, vmax=zmax)
        ax.set_xticks(range(len(types)))
        ax.set_xticklabels(types, rotation=45, ha="right", fontsize=8)
        ax.set_yticks(range(len(M)))
        ax.set_yticklabels(M.index, fontsize=7.5)
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                v = M.iat[i, j]
                if np.isfinite(v) and abs(v) >= 1:
                    ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=6.5, color="white" if abs(v) > 0.6 * zmax else "black")
        fig.colorbar(im, ax=ax, label="Change in p95 TAT (%)", shrink=0.7)
        ax.set_title("Effect of each assumption on p95 TAT by specimen type (level with the larger effect)", fontsize=9, fontweight="bold")
        fig.tight_layout()
        fig.savefig(out / "sens_heatmap_p95_by_type.png", dpi=300)
        plt.close(fig)
        M.to_csv(out / "sens_heatmap_p95_by_type.csv", float_format="%.2f")
    print(f"\nwrote tables and figures to {out.resolve()}")


if __name__ == "__main__":
    main()
