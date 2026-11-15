import json

import pandas as pd
import dash
from dash import Input, Output, State, no_update, ALL

from modules.simulation_d4 import run_simulation
import params_config.params_d3 as p
from params_config.staffing_config import SHIFT_STAFFING_PROFILE
from components.GraphingFunctions_d2 import (
    Graphing_WorkloadQueues,
    Graphing_TechUtilization,
    Graphing_SampleVolumes,
    Graphing_SampleQueue,
    Graphing_TAT,
    Graphing_WaitTime,
    Graphing_MediaUsage,
    Graphing_review_milestones_scatter,
    Graphing_active_vs_backlog_plot,
)
from components.scenario_overrides import SCENARIO_FIELDS, SCENARIO_KEYS, assemble_profile, build_overrides

# Mapping keys to expected dict structure in run_simulation
DAY_MAP = {"wd": "Weekday", "we": "Weekend"}
SHIFT_MAP = {
    "shift1": ("Shift_1_Day", (7, 15)),
    "shift2": ("Shift_2_Evening", (15, 23)),
    "shift3": ("Shift_3_Night", (23, 7)),
}
_SC_STATES = [State(cid, "value") for cid, _ in SCENARIO_FIELDS]
_BASE_PLATING = (getattr(p, "min_plating_time", None), getattr(p, "avg_plating_time", None), getattr(p, "max_plating_time", None))
_BASE_PLATING = _BASE_PLATING if all(v is not None for v in _BASE_PLATING) else None


def _overrides_from_values(sc_vals):
    return build_overrides(**dict(zip(SCENARIO_KEYS, sc_vals)), base_plating=_BASE_PLATING)


def _count_event(df, needles):
    cols = [c for c in df.columns if any(n.lower() in str(c).lower() for n in needles)]
    return int(df[cols].notna().any(axis=1).sum()) if cols else 0


def register_sim_callbacks(app, log_output, init_conditions_json=None):

    # 0. live preview of the overrides the scenario controls will apply
    @app.callback(Output("sc_preview", "children"), [Input(cid, "value") for cid, _ in SCENARIO_FIELDS])
    def preview_overrides(*sc_vals):
        ov, warn = _overrides_from_values(sc_vals)
        txt = json.dumps({k: (json.loads(v) if isinstance(v, str) and v[:1] in "{[" else v) for k, v in ov.items()}, indent=1) if ov else "(none: baseline model)"
        return txt + ("\n\n! " + "\n! ".join(warn) if warn else "")

    # 1. TRIGGER SIMULATION & STORE RESULTS
    @app.callback(
        Output("store_sim_data", "data"),
        Input("btn_run_sim", "n_clicks"),
        State("slider_sim_days", "value"),
        State("input_seed", "value"),
        State("input_bc_capacity", "value"),
        State("input_incubator_capacity", "value"),
        State("input_phoenix_capacity", "value"),
        State("input_maldi_capacity", "value"),
        State({"type": "staff-input", "day_type": ALL, "shift": ALL, "field": ALL}, "value"),
        State({"type": "staff-input", "day_type": ALL, "shift": ALL, "field": ALL}, "id"),
        *_SC_STATES,
        progress=[
            Output("sim_progress_bar", "value"),
            Output("sim_progress_bar", "label"),
            Output("sim_progress_text", "children"),
        ],
        progress_default=(0, "0%", "Ready to start simulation"),
        running=[
            (Output("btn_run_sim", "disabled"), True, False),
            (Output("sim_progress_container", "style"), {"display": "block"}, {"display": "block"}),
        ],
        background=True,
        prevent_initial_call=True,
    )
    def trigger_simulation(set_progress, n_clicks, sim_days, seed, bc_cap, inc_cap, phx_cap, maldi_cap,
                           staff_values, staff_ids, *sc_vals):
        if not n_clicks:
            return no_update
        set_progress((5, "5%", "Initializing simulation parameters..."))

        instrument_resources = {
            "incubator": inc_cap if inc_cap is not None else 10000,
            "bc_instrument": bc_cap if bc_cap is not None else 1500,
            "phoenix_instrument": phx_cap if phx_cap is not None else 150,
            "maldi_instrument": maldi_cap if maldi_cap is not None else 2,
        }
        shift_staffing_profile = assemble_profile(SHIFT_STAFFING_PROFILE, staff_values, staff_ids, DAY_MAP, SHIFT_MAP)
        overrides, warnings = _overrides_from_values(sc_vals)

        df_pivot, df_state, media_usage, df_ai_features, stochastic_stats = run_simulation(
            sim_days=sim_days,
            seed=int(seed) if seed is not None else p.seed_input,
            instrument_resources=instrument_resources,
            shift_staffing_profile=shift_staffing_profile,
            initial_conditions_json=init_conditions_json,
            parameter_overrides=overrides or None,
            set_progress=set_progress,
            save_plots=False,
            log_filename=log_output,
        )

        try:                                  # shortage-policy statistics live in this process after the run
            from modules import shortage_policy
            shortage_stats = json.loads(json.dumps(dict(shortage_policy.LAST_STATS), default=float))
        except Exception:
            shortage_stats = {}

        set_progress((100, "100%", "Simulation Complete!"))
        return {
            "df_pivot": df_pivot.to_dict("records"),
            "df_state": df_state.to_dict("records"),
            "media_usage": media_usage,
            "overrides": overrides,
            "warnings": warnings,
            "shortage_stats": shortage_stats,
        }

    # 2. UPDATE TAB 1 DASHBOARD VISUALS FROM STORE
    @app.callback(
        [
            Output("kpi_total", "children"),
            Output("kpi_tat", "children"),
            Output("kpi_wait", "children"),
            Output("kpi_completion", "children"),
            Output("kpi_stockouts", "children"),
            Output("kpi_aborted", "children"),
            Output("shortage_stats_box", "children"),
            Output("chart_scatter_timeline", "figure"),
            Output("chart_sample_volumes_line", "figure"),
            Output("chart_tech_utilization", "figure"),
            Output("chart_queue_diagnostic", "figure"),
            Output("chart_tat", "figure"),
            Output("active-backlog-graph", "figure"),
            Output("chart_wait", "figure"),
            Output("chart_media", "figure"),
            Output("chart_review_milestones", "figure"),
            Output("table_specimens", "data"),
            Output("table_specimens", "columns"),
        ],
        Input("store_sim_data", "data"),
    )
    def update_dashboard(data):
        empty_fig = {}
        if not data or "df_pivot" not in data or len(data["df_pivot"]) == 0:
            return ("-", "-", "-", "-", "-", "-", "", *([empty_fig] * 9), [], [])

        df_pivot = pd.DataFrame(data["df_pivot"])
        df_state = pd.DataFrame(data.get("df_state", []))
        media_usage = data.get("media_usage", {})
        completed_df = df_pivot.dropna(subset=["Total_TAT_Hours"]) if "Total_TAT_Hours" in df_pivot.columns else pd.DataFrame()

        total_specs = len(df_pivot["Specimen_ID"].unique()) if "Specimen_ID" in df_pivot.columns else len(df_pivot)
        if not completed_df.empty:
            tat = completed_df["Total_TAT_Hours"]
            kpi_tat = f"{tat.quantile(.5):.0f} / {tat.quantile(.95):.0f} h"
        else:
            kpi_tat = "N/A"
        avg_wait = f"{completed_df['Wait_For_Plating_Mins'].mean():.1f} mins" if not completed_df.empty and "Wait_For_Plating_Mins" in completed_df else "N/A"
        completion_rate = f"{(len(completed_df) / total_specs) * 100:.1f}%" if total_specs > 0 else "0%"
        n_stockout = _count_event(df_pivot, ["Stockout Delay Started"])
        n_aborted = _count_event(df_pivot, ["Media Allocation Failed", "ABORTED"])

        ss = data.get("shortage_stats") or {}
        notes = list(data.get("warnings") or [])
        if ss:
            mc = ss.get("min_cover_days") or {}
            low = ", ".join(f"{m}: {v:.1f} d" for m, v in sorted(mc.items(), key=lambda kv: kv[1])[:3])
            notes.insert(0, f"Supply disruption: {ss.get('held_units', 0):,.0f} plates held back | emergency orders {ss.get('n_emergency_orders', 0):.0f} "
                            f"({ss.get('emergency_units', 0):,.0f} plates, extra cost {ss.get('emergency_cost', 0):,.0f}) | optional media spared {ss.get('n_spared', 0):,.0f}"
                            + (f" | lowest cover: {low}" if low else ""))
        stats_text = " | ".join(notes)

        fig_sample_queue = Graphing_SampleQueue(df_state.iloc[[-1]] if not df_state.empty else pd.DataFrame())
        columns = [{"name": i, "id": i} for i in df_pivot.columns]
        return (
            total_specs, kpi_tat, avg_wait, completion_rate, n_stockout, n_aborted, stats_text,
            Graphing_WorkloadQueues(df_state), Graphing_SampleVolumes(df_pivot), Graphing_TechUtilization(df_state), fig_sample_queue,
            Graphing_TAT(completed_df), Graphing_active_vs_backlog_plot(df_state), Graphing_WaitTime(completed_df),
            Graphing_MediaUsage(media_usage), Graphing_review_milestones_scatter(data),
            df_pivot.to_dict("records"), columns,
        )
