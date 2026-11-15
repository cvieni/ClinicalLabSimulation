# components/callbacks_subfnc/monte_carlo_callbacks.py
import base64
import io
import json
from pathlib import Path

import dash_bootstrap_components as dbc
import pandas as pd
from dash import ALL, Input, Output, State, html, no_update, ctx

from components.monte_carlo_graphing_fnc import (
    build_delay_incidents_figure, build_consumables_figure, build_parameter_distribution_figures, build_specimen_tat_figure,
)
from components.mc_runner import MC_FIELDS, run_from_ui

_STAFF_VAL = State({"type": "staff-input", "day_type": ALL, "shift": ALL, "field": ALL}, "value")
_STAFF_ID = State({"type": "staff-input", "day_type": ALL, "shift": ALL, "field": ALL}, "id")
_MEDIA_VAL = State({"type": "mc_media_policy_input", "index": ALL}, "value")
_MEDIA_ID = State({"type": "mc_media_policy_input", "index": ALL}, "id")


def _policy(values, ids):
    return {i["index"]: (v if v is not None else 0) for i, v in zip(ids or [], values or [])}


def _card(title, lines, color="light", title_class="text-secondary"):
    return dbc.Card(dbc.CardBody([html.H5(title, className=title_class), *[html.P(l, className="small text-secondary font-monospace mb-0") for l in lines]]),
                    color=color, className="mb-3")


def _risk_title(df):
    total = len(df)
    risk = ((df["total_delays"] > 0).sum() / total * 100.0) if total and "total_delays" in df.columns else 0.0
    return f"Stockout risk: {risk:.1f}%", ("text-danger" if risk > 15 else "text-success")


def _settings_lines(csv_path):
    f = Path(csv_path).with_suffix(".json")
    if not f.exists():
        return []
    try:
        s = json.loads(f.read_text())
    except Exception:
        return []
    ov = ", ".join(s.get("parameter_overrides", {}) or []) or "none (baseline model)"
    return [f"{s.get('iterations')} replications x {s.get('sim_days'):g} days, seed base {s.get('seed_base')}", f"overrides: {ov}"]


def register_monte_carlo_callbacks(app, output_directory):
    out_dir = Path(output_directory)
    out_dir.mkdir(parents=True, exist_ok=True)

    # live preview of the scenario overrides that will be sent to the replications
    from components.scenario_overrides import build_overrides
    from components.mc_runner import MC_KEYS, _BASE_PLATING

    @app.callback(Output("mcs_preview", "children"), [Input(cid, "value") for cid, _ in MC_FIELDS])
    def preview_mc_overrides(*vals):
        ov, warn = build_overrides(**dict(zip(MC_KEYS, vals)), base_plating=_BASE_PLATING)
        txt = json.dumps({k: (json.loads(v) if isinstance(v, str) and v[:1] in "{[" else v) for k, v in ov.items()}, indent=1) if ov else "(none: baseline model)"
        return txt + ("\n\n! " + "\n! ".join(warn) if warn else "")

    # 1. history dropdown
    @app.callback(Output("dd_past_sim_runs", "options"),
                  [Input("btn_refresh_sim_history", "n_clicks"), Input("store_mc_results", "data")])
    def update_history_dropdown(_refresh, _store):
        files = sorted(out_dir.glob("sim_*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
        return [{"label": f.name, "value": str(f)} for f in files]

    # 2. upload a results CSV
    @app.callback([Output("store_mc_results", "data", allow_duplicate=True), Output("upload_status_msg", "children")],
                  Input("upload_mc_csv", "contents"), State("upload_mc_csv", "filename"), prevent_initial_call=True)
    def handle_csv_upload(contents, filename):
        if contents is None:
            return no_update, no_update
        try:
            df = pd.read_csv(io.StringIO(base64.b64decode(contents.split(",")[1]).decode("utf-8")))
            return df.to_dict("records"), f"Loaded '{filename}' ({len(df)} replications)."
        except Exception as e:
            return no_update, f"Error loading CSV: {e}"

    # 3. reload a saved run
    @app.callback([Output("store_mc_results", "data", allow_duplicate=True), Output("mc_results_container", "children", allow_duplicate=True)],
                  Input("dd_past_sim_runs", "value"), prevent_initial_call=True)
    def load_saved_run(path):
        if not path or not Path(path).exists():
            return no_update, no_update
        df = pd.read_csv(path)
        title, cls = _risk_title(df)
        return df.to_dict("records"), _card(title, [f"Loaded: {Path(path).name} ({len(df)} replications)", *_settings_lines(path)], title_class=cls)

    # 4. RUN a Monte Carlo study (background process; the replications run in their own worker pool)
    @app.callback(
        [Output("store_mc_results", "data"), Output("mc_results_container", "children")],
        Input("btn_mc_run", "n_clicks"),
        [State("mc_iterations", "value"), State("mc_slider_sim_days", "value"), State("mc_input_seed_base", "value"), State("mc_workers", "value"),
         State("mc_label", "value"), State("mc_input_bc_capacity", "value"), State("mc_input_incubator_capacity", "value"),
         State("mc_input_phoenix_capacity", "value"), State("mc_input_maldi_capacity", "value"), _STAFF_VAL, _STAFF_ID, _MEDIA_VAL, _MEDIA_ID,
         *[State(cid, "value") for cid, _ in MC_FIELDS]],
        background=True,
        progress=[Output("mc_progress_bar", "value"), Output("mc_progress_bar", "label"), Output("mc_progress_text", "children")],
        progress_default=(0, "0%", "Ready to start simulation..."),
        running=[(Output("btn_mc_run", "disabled"), True, False)],
        cancel=[Input("btn_mc_cancel", "n_clicks")],
        prevent_initial_call=True,
    )
    def run_monte_carlo(set_progress, n_clicks, iterations, sim_days, seed_base, workers, label, bc, inc, phx, maldi,
                        staff_values, staff_ids, media_values, media_ids, *sc_vals):
        if not n_clicks:
            return no_update, no_update
        set_progress((0, "0%", f"Starting {iterations} replications..."))
        try:
            res = run_from_ui(iterations, sim_days, seed_base, workers, label, bc, inc, phx, maldi, staff_values, staff_ids, media_values, media_ids,
                              sc_vals, out_dir, set_progress)
        except ValueError as e:
            return no_update, dbc.Alert(str(e), color="warning")
        except Exception as e:
            return no_update, dbc.Alert(f"Monte Carlo run failed: {type(e).__name__}: {e}", color="danger")
        df = res["df"]
        if df is None or df.empty:
            return no_update, dbc.Alert("Monte Carlo run returned no data.", color="warning")
        title, cls = _risk_title(df)
        lines = [f"Saved: {res['csv_path'].name} (+ .json with the settings)", *_settings_lines(res["csv_path"]), *[f"! {w}" for w in res["warnings"]]]
        set_progress((100, "100%", "Monte Carlo complete."))
        return df.to_dict("records"), _card(title, lines, title_class=cls)

    # 5. draw everything from the stored replications
    @app.callback(
        [Output("chart_mc_stockout_dist", "figure"), Output("chart_mc_media_boxplots", "figure"), Output("chart_mc_specimen_tat", "figure"),
         Output("chart_mc_params", "figure"), Output("table_mc_summary", "data"), Output("table_mc_summary", "columns"),
         Output("mc_kpi_risk_rate", "children"), Output("mc_kpi_avg_delays", "children"), Output("mc_kpi_iterations", "children"),
         Output("mc_kpi_max_delays", "children"), Output("mc_kpi_tat", "children"), Output("mc_kpi_aborted", "children")],
        [Input("store_mc_results", "data"), Input("mc_tat_metric", "value")],
        [_MEDIA_VAL, _MEDIA_ID],
    )
    def render_results(store, metric, media_values, media_ids):
        if not store:
            return ({}, {}, {}, {}, [], [], "-", "-", "-", "-", "-", "-")
        df = pd.DataFrame(store)
        n = len(df)
        td = df["total_delays"] if "total_delays" in df.columns else pd.Series([0] * n)
        risk = f"{(td > 0).sum() / n * 100:.1f}%" if n else "-"
        tat = (f"{df['tat_overall_p50'].mean():.0f} / {df['tat_overall_p95'].mean():.0f} h"
               if {"tat_overall_p50", "tat_overall_p95"} <= set(df.columns) else "N/A")
        ab = f"{df['n_aborted'].mean():.1f}" if "n_aborted" in df.columns else "N/A"
        return (build_delay_incidents_figure(df), build_consumables_figure(df, _policy(media_values, media_ids)), build_specimen_tat_figure(df, metric),
                build_parameter_distribution_figures(df), df.to_dict("records"), [{"name": c, "id": c} for c in df.columns],
                risk, f"{td.mean():.1f}", n, f"{td.max():.0f}", tat, ab)
