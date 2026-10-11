import pandas as pd
import dash
from dash import Input, Output, State, no_update, ALL

from modules.simulation_d3 import run_simulation
import params_config.params_d3 as p
from components.GraphingFunctions_d2 import (
    Graphing_WorkloadQueues,
    Graphing_TechUtilization,
    Graphing_SampleVolumes,
    Graphing_SampleQueue,
    Graphing_TAT,
    Graphing_WaitTime,
    Graphing_MediaUsage,
    Graphing_review_milestones_scatter,
    Graphing_active_vs_backlog_plot
)

import json
from params_config.staffing_config import SHIFT_STAFFING_PROFILE
print("=== DEBUG: Shift Staffing Profile sent to SimPy ===")
print(json.dumps(SHIFT_STAFFING_PROFILE, indent=2))

seed_num = p.seed_input

# Mapping keys to expected dict structure in run_simulation
DAY_MAP = {"wd": "Weekday", "we": "Weekend"}
MC_DAY_MAP = {"mc_wd": "Weekday", "mc_we": "Weekend"}

SHIFT_MAP = {
    "shift1": ("Shift_1_Day", (7, 15)),
    "shift2": ("Shift_2_Evening", (15, 23)),
    "shift3": ("Shift_3_Night", (23, 7)),
}


def register_sim_callbacks(app, log_output, init_conditions_json=None):

    # 1. TRIGGER SIMULATION & STORE RESULTS
    @app.callback(
        Output("store_sim_data", "data"),
        Input("btn_run_sim", "n_clicks"),
        # --- General Simulation Settings (7) ---
        State("slider_sim_days", "value"),
        State("input_plating_time", "value"),
        State("input_incubation_hours", "value"),
        State("input_bc_capacity", "value"),
        State("input_incubator_capacity", "value"),
        State("input_phoenix_capacity", "value"),
        State("input_maldi_capacity", "value"),

        # --- Dynamic Pattern-Matching Staffing Inputs ---
        State({"type": "staff-input", "day_type": ALL, "shift": ALL, "field": ALL}, "value"),
        State({"type": "staff-input", "day_type": ALL, "shift": ALL, "field": ALL}, "id"),
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
    def trigger_simulation(
        set_progress,             # Background progress handle
        n_clicks,                 # Input: btn_run_sim

        # --- General Simulation Settings (1-7) ---
        sim_days,          
        plating_time,        
        incubation_hours,         
        bc_cap,                 
        inc_cap,                
        phx_cap,                 
        maldi_cap,                

        # --- Weekday Shift 1 (8-15) ---
        staff_values,
        staff_ids,
    ):

        if not n_clicks:
            return no_update

        set_progress((5, "5%", "Initializing simulation parameters..."))

        def val(user_val, default):
            return int(user_val) if user_val is not None else default

        instrument_resources = {
            "incubator": inc_cap if inc_cap is not None else 10000,
            "bc_instrument": bc_cap if bc_cap is not None else 1500,
            "phoenix_instrument": phx_cap if phx_cap is not None else 150,
            "maldi_instrument": maldi_cap if maldi_cap is not None else 2,
        }

        # 2. Dynamically Assemble `shift_staffing_profile` from Pattern Matching IDs
        shift_staffing_profile = {"Weekday": {}, "Weekend": {}}
        mc_shift_staffing_profile = {"Weekday": {},"Weekend": {}}

        for val, meta in zip(staff_values, staff_ids):
            day_type = meta.get("day_type")
            shift_raw = meta.get("shift")
            field = meta.get("field")
            
            # Skip invalid or unmapped inputs safely
            if not day_type or shift_raw not in SHIFT_MAP:
                continue

            try:
                clean_val = int(val) if val is not None else 0
            except (ValueError, TypeError):
                clean_val = 0

            shift_key, hours = SHIFT_MAP[shift_raw]

            # Route 1: Standard Simulation Profile ('wd', 'we')
            if day_type in DAY_MAP:
                day_group = DAY_MAP[day_type]
                if shift_key not in shift_staffing_profile[day_group]:
                    shift_staffing_profile[day_group][shift_key] = {"hours": list(hours)}
                shift_staffing_profile[day_group][shift_key][field] = clean_val

            # Route 2: Monte Carlo Simulation Profile ('mc_wd', 'mc_we')
            elif day_type in MC_DAY_MAP:
                day_group = MC_DAY_MAP[day_type]
                if shift_key not in mc_shift_staffing_profile[day_group]:
                    mc_shift_staffing_profile[day_group][shift_key] = {"hours": list(hours)}
                mc_shift_staffing_profile[day_group][shift_key][field] = clean_val


        # DEBUG: Print the payload generated right before sending to SimPy
        # print("\n=== DEBUG: Shift Staffing Profile sent to SimPy ===")
        # print(json.dumps(shift_staffing_profile, indent=2))
        # print("===================================================\n")
        
        # 3. Run Simulation
        df_pivot, df_state, media_usage, df_ai_features, stochastic_stats = run_simulation(
            sim_days=sim_days,
            seed=seed_num,
            instrument_resources=instrument_resources,
            shift_staffing_profile=shift_staffing_profile,
            initial_conditions_json=init_conditions_json,
            set_progress=set_progress,
            save_plots=False,
            log_filename = log_output
        )

        set_progress((100, "100%", "Simulation Complete!"))

        return {
            "df_pivot": df_pivot.to_dict("records"),
            "df_state": df_state.to_dict("records"),
            "media_usage": media_usage,
        }
    

    # 2. UPDATE TAB 1 DASHBOARD VISUALS FROM STORE
    @app.callback(
        [
            Output("kpi_total", "children"),
            Output("kpi_tat", "children"),
            Output("kpi_wait", "children"),
            Output("kpi_completion", "children"),
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
            return (
                "-", "-", "-", "-",
                empty_fig, empty_fig, empty_fig, empty_fig, 
                empty_fig, empty_fig, empty_fig, empty_fig, empty_fig,
                [], [],
            )

        df_pivot = pd.DataFrame(data["df_pivot"])
        df_state = pd.DataFrame(data.get("df_state", []))
        media_usage = data.get("media_usage", {})
        completed_df = df_pivot.dropna(subset=["Total_TAT_Hours"]) if "Total_TAT_Hours" in df_pivot.columns else pd.DataFrame()

        total_specs = len(df_pivot["Specimen_ID"].unique()) if "Specimen_ID" in df_pivot.columns else len(df_pivot)
        avg_tat = f"{completed_df['Total_TAT_Hours'].mean():.1f} hrs" if not completed_df.empty and "Total_TAT_Hours" in completed_df else "N/A"
        avg_wait = f"{completed_df['Wait_For_Plating_Mins'].mean():.1f} mins" if not completed_df.empty and "Wait_For_Plating_Mins" in completed_df else "N/A"
        completion_rate = f"{(len(completed_df)/total_specs)*100:.1f}%" if total_specs > 0 else "0%"

        fig_sample_queue = Graphing_SampleQueue(df_state.iloc[[-1]] if not df_state.empty else pd.DataFrame())
        fig_scatter = Graphing_WorkloadQueues(df_state)
        fig_volume = Graphing_SampleVolumes(df_pivot)
        fig_tech = Graphing_TechUtilization(df_state)
        fig_tat = Graphing_TAT(completed_df)
        fig_active_backlog = Graphing_active_vs_backlog_plot(df_state)
        fig_wait = Graphing_WaitTime(completed_df)
        fig_media = Graphing_MediaUsage(media_usage)
        fig_review = Graphing_review_milestones_scatter(data)

        columns = [{"name": i, "id": i} for i in df_pivot.columns]

        return (
            total_specs, avg_tat, avg_wait, completion_rate,
            fig_scatter, fig_volume, fig_tech, fig_sample_queue,
            fig_tat, fig_active_backlog, fig_wait, fig_media, fig_review,
            df_pivot.to_dict("records"), columns,
        )