# components/callbacks_subfnc/results_callbacks.py
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dash_table, dcc, html, no_update

from components import results_loader as rl

_MEMO = {}   # id -> (signature, data)  (unpickling a big cache file once per session is enough)
PALETTE = px.colors.qualitative.Safe


def _get(src, recompute=False):
    sig = rl._signature(src)
    hit = _MEMO.get(src["id"])
    if hit and hit[0] == sig and not recompute:
        return hit[1]
    data = rl.load_source(src, use_cache=not recompute)
    _MEMO[src["id"]] = (sig, data)
    return data


def _empty(msg):
    fig = go.Figure()
    fig.update_layout(template="plotly_white", annotations=[dict(text=msg, showarrow=False, font=dict(size=14), x=0.5, y=0.5, xref="paper", yref="paper")],
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def _table(df, page_size=15):
    if df is None or df.empty:
        return html.P("Nothing to show.", className="text-muted")
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].round(2)
    return dash_table.DataTable(data=df.to_dict("records"), columns=[{"name": str(c), "id": str(c)} for c in df.columns], page_size=page_size,
                                sort_action="native", style_table={"overflowX": "auto"}, style_cell={"fontSize": "12px", "padding": "4px 8px", "textAlign": "left"},
                                style_header={"fontWeight": "bold"})


def register_results_callbacks(app, output_directory, extra_roots=()):
    out_dir = Path(output_directory)

    def default_roots():
        cands = [out_dir, Path.cwd() / "results_experiments", out_dir.parent / "results_experiments", *map(Path, extra_roots)]
        seen, res = set(), []
        for c in cands:
            k = str(c.resolve()) if c.exists() else str(c)
            if k not in seen:
                seen.add(k)
                res.append(str(c))
        return "\n".join(res)

    @app.callback(Output("rx_roots", "value"), Input("rx_init", "n_intervals"))
    def _init(_):
        return default_roots()

    @app.callback(Output("rx_meta", "data"), Output("rx_sources", "options"), Output("rx_sources", "value"),
                  Input("rx_scan", "n_clicks"), Input("rx_roots", "value"), State("rx_sources", "value"))
    def scan(_, roots, current):
        paths = [r.strip() for r in (roots or "").splitlines() if r.strip()]
        found = rl.discover(paths)
        meta = {s["id"]: s for s in found}
        opts = [{"label": rl.option_label(s), "value": s["id"]} for s in found]
        keep = [c for c in (current or []) if c in meta]
        return meta, opts, keep

    @app.callback(Output("rx_baseline", "options"), Output("rx_baseline", "value"),
                  Input("rx_sources", "value"), State("rx_meta", "data"), State("rx_baseline", "value"))
    def baseline_options(sel, meta, cur):
        sel = sel or []
        opts = [{"label": meta[i]["label"], "value": i} for i in sel if meta and i in meta]
        if cur in sel:
            return opts, cur
        pick = next((i for i in sel if meta[i]["label"].lower() == "baseline"), sel[0] if sel else None)
        return opts, pick

    def _datasets(sel, meta, recompute=False, labels=True):
        out, used = {}, {}
        for i in sel or []:
            s = meta[i]
            lab = s["label"]
            if lab in used:                       # same label in two folders: disambiguate
                lab = f"{lab} ({Path(s['path']).parent.name})"
            used[lab] = i
            out[lab] = _get(s, recompute)
        return out, used

    @app.callback(Output("rx_types", "options"), Output("rx_ecdf_type", "options"), Output("rx_ecdf_type", "value"), Output("rx_status", "children"),
                  Input("rx_load", "n_clicks"), State("rx_sources", "value"), State("rx_meta", "data"), State("rx_recompute", "value"), State("rx_ecdf_type", "value"),
                  prevent_initial_call=True)
    def load(_, sel, meta, recompute, cur_ecdf):
        if not sel:
            return [], [], None, "Pick at least one result and press Load."
        try:
            ds, _ = _datasets(sel, meta, bool(recompute))
        except Exception as e:
            return [], [], None, dbc.Alert(f"Could not read a result: {type(e).__name__}: {e}", color="danger")
        types = sorted({t for d in ds.values() for t in d["summary"].get("type", [])})
        opts = [{"label": t, "value": t} for t in types]
        notes = []
        for lab, d in ds.items():
            notes.append(f"{lab}: {d['summary']['rep'].nunique() if not d['summary'].empty else 0} reps, {len(types)} types"
                         + ("" if len(d["util"]) else ", no utilization"))
        return opts, opts, (cur_ecdf if cur_ecdf in types else (types[0] if types else None)), "Loaded: " + " | ".join(notes)

    def _ctx(sel, meta, base):
        if not sel or not meta:
            return None, None
        ds, used = _datasets(sel, meta)
        id2lab = {v: k for k, v in used.items()}
        b = id2lab.get(base) or next(iter(ds))
        return ds, b

    @app.callback(Output("rx_overview", "children"), Output("rx_fig_tat", "figure"), Output("rx_fig_delta", "figure"), Output("rx_delta_table", "children"),
                  Output("rx_util", "children"), Output("rx_settings", "children"),
                  Input("rx_status", "children"), Input("rx_metric", "value"), Input("rx_mode", "value"), Input("rx_types", "value"), Input("rx_baseline", "value"),
                  State("rx_sources", "value"), State("rx_meta", "data"), prevent_initial_call=True)
    def render(_status, metric, mode, types, base, sel, meta):
        ds, b = _ctx(sel, meta, base)
        if not ds:
            e = _empty("Pick results and press Load")
            return html.P("No results loaded."), e, e, None, None, None
        types = types or None
        name = "Median" if metric == "p50" else "95th percentile"
        # ---- overview
        overview = _table(rl.run_metric_table(ds))
        # ---- TAT by type
        t = rl.tat_table(ds, metric, types)
        if t.empty:
            fig_tat = _empty(f"No {name} TAT per type in the selected results")
        else:
            fig_tat = go.Figure()
            for k, (lab, g) in enumerate(t.groupby("source", sort=False)):
                fig_tat.add_bar(x=g["type"], y=g["mean"], name=lab, error_y=dict(type="data", array=g["ci"].fillna(0), visible=True),
                                marker_color=PALETTE[k % len(PALETTE)])
            fig_tat.update_layout(barmode="group", template="plotly_white", title=f"{name} TAT by specimen type (mean across replications, 95% CI)",
                                  yaxis_title="Hours", legend=dict(orientation="h", y=1.1), margin=dict(l=50, r=20, t=80, b=80))
        # ---- delta
        dl = rl.paired_delta(ds, b, metric, types, pct=(mode == "pct"))
        unit = "%" if mode == "pct" else " h"
        if dl.empty:
            fig_d, dtab = _empty("Select a baseline and at least one other result"), None
        else:
            order = dl.groupby("type")["delta"].apply(lambda s: s.abs().max()).sort_values().index.tolist()
            fig_d = go.Figure()
            for k, (lab, g) in enumerate(dl.groupby("source", sort=False)):
                g = g.set_index("type").reindex(order).reset_index()
                fig_d.add_trace(go.Scatter(y=g["type"], x=g["delta"], mode="markers", name=lab, error_x=dict(type="data", array=g["ci"].fillna(0), visible=True),
                                           marker=dict(size=10, color=PALETTE[(k + 1) % len(PALETTE)], symbol=["circle" if s else "circle-open" for s in g["significant"]],
                                                       line=dict(width=1.5, color=PALETTE[(k + 1) % len(PALETTE)])),
                                           hovertemplate="%{y}: %{x:.1f}" + unit + "<extra>" + lab + "</extra>"))
            fig_d.add_vline(x=0, line_color="gray", line_dash="dash")
            fig_d.update_layout(template="plotly_white", title=f"Change in {name} TAT vs '{b}'", xaxis_title=f"Change ({'%' if mode == 'pct' else 'hours'})",
                                height=max(420, 40 * len(order) + 160), legend=dict(orientation="h", y=1.08), margin=dict(l=130, r=20, t=90, b=50))
            dtab = _table(dl.rename(columns={"delta": f"delta{unit}", "ci": "ci95"}), 20)
        # ---- utilization
        ud = rl.util_delta(ds, b)
        if not ud:
            util = html.P("No state files in the selected scenario folders (or baseline has none).", className="text-muted")
        else:
            labs = list(ud)
            fig_u = make_subplots(rows=1, cols=len(labs), subplot_titles=labs, shared_yaxes=True, horizontal_spacing=0.04)
            zmax = max(1.0, max(float(np.nanmax(np.abs(v.to_numpy()))) for v in ud.values()))
            for j, lab in enumerate(labs, 1):
                m = ud[lab]
                fig_u.add_trace(go.Heatmap(z=m.to_numpy(), x=list(m.columns), y=list(m.index), zmin=-zmax, zmax=zmax, colorscale="RdBu_r",
                                           text=np.round(m.to_numpy(), 1), texttemplate="%{text}", showscale=(j == len(labs)),
                                           colorbar=dict(title="pp") if j == len(labs) else None), row=1, col=j)
            fig_u.update_layout(template="plotly_white", height=460, margin=dict(l=170, r=20, t=60, b=40))
            fig_u.update_yaxes(autorange="reversed")
            util = dcc.Graph(figure=fig_u)
        # ---- settings
        sd = rl.settings_diff(ds, b)
        settings = _table(sd, 25) if not sd.empty else html.P("These results carry no recorded overrides (baseline model).", className="text-muted")
        return overview, fig_tat, fig_d, dtab, util, settings

    @app.callback(Output("rx_fig_ecdf", "figure"), Input("rx_ecdf_type", "value"), Input("rx_status", "children"), Input("rx_baseline", "value"),
                  State("rx_sources", "value"), State("rx_meta", "data"), prevent_initial_call=True)
    def ecdf(typ, _s, base, sel, meta):
        ds, b = _ctx(sel, meta, base)
        if not ds or not typ:
            return _empty("Pick results, press Load, then choose a specimen type")
        fig, n = go.Figure(), 0
        for k, (lab, d) in enumerate(ds.items()):
            x = d["sample"]
            x = np.sort(x.loc[x["type"] == typ, "tat_h"].to_numpy(float)) if len(x) else np.array([])
            if len(x):
                n += 1
                fig.add_scatter(x=x, y=np.arange(1, len(x) + 1) / len(x), mode="lines", name=lab, line=dict(color=PALETTE[k % len(PALETTE)], width=2, shape="hv"))
        if not n:
            return _empty("No individual TATs for this type (Monte Carlo tab files only store percentiles)")
        fig.update_layout(template="plotly_white", title=f"Cumulative distribution of total TAT: {typ} (sample of completed specimens)",
                          xaxis_title="Total TAT (hours)", yaxis_title="Fraction completed", legend=dict(orientation="h", y=1.1))
        return fig

    @app.callback(Output("rx_download", "data"), Input("rx_dl_btn", "n_clicks"),
                  State("rx_sources", "value"), State("rx_meta", "data"), State("rx_baseline", "value"), State("rx_mode", "value"), prevent_initial_call=True)
    def download(_, sel, meta, base, mode):
        ds, b = _ctx(sel, meta, base)
        if not ds:
            return no_update
        parts = []
        for metric in ("p50", "p95"):
            t = rl.tat_table(ds, metric).rename(columns={"mean": f"{metric}_mean_h", "ci": f"{metric}_ci95_h"}).drop(columns=["n_reps"], errors="ignore")
            d = rl.paired_delta(ds, b, metric, None, pct=(mode == "pct")).rename(columns={"delta": f"{metric}_delta_{mode}", "ci": f"{metric}_delta_ci95"})
            d = d.drop(columns=["n_reps", "paired"], errors="ignore").rename(columns={"significant": f"{metric}_delta_significant"})
            parts.append(t.merge(d, on=["source", "type"], how="left"))
        out = parts[0].merge(parts[1], on=["source", "type"], how="outer")
        out.insert(2, "baseline", b)
        return dcc.send_data_frame(out.to_csv, "results_comparison.csv", index=False)
