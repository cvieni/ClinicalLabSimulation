import pandas as pd
import dash
from dash import Input, Output, State, no_update

from modules.simulation_d3 import run_simulation
import params_config.params_d2 as p
from components.GraphingFunctions_d2 import (
    Graphing_WorkloadQueues,
    Graphing_TechUtilization,
    Graphing_SampleVolumes,
    Graphing_SampleQueue,
    Graphing_TAT,
    Graphing_WaitTime,
    Graphing_MediaUsage,
    Graphing_review_milestones_scatter,
)

seed_num = p.seed_input

# Mapping keys to expected dict structure in run_simulation
DAY_MAP = {"wd": "Weekday", "we": "Weekend"}
SHIFT_MAP = {
    "shift1": ("Shift_1_Day", (7, 15)),
    "shift2": ("Shift_2_Evening", (15, 23)),
    "shift3": ("Shift_3_Night", (23, 7)),
}


def register_sim_callbacks(app, log_output):

    # 1. TRIGGER SIMULATION & STORE RESULTS
    @app.callback(
        Output("store_sim_data", "data"),
        Input("btn_run_sim", "n_clicks"),
        [
            # --- General Simulation Settings (7) ---
            State("slider_sim_days", "value"),
            State("input_plating_time", "value"),
            State("input_incubation_hours", "value"),
            State("input_bc_capacity", "value"),
            State("input_incubator_capacity", "value"),
            State("input_phoenix_capacity", "value"),
            State("input_maldi_capacity", "value"),

            # --- Weekday Shift 1 (8) ---
            State("input_wd_shift1_tech_accession", "value"),
            State("input_wd_shift1_tech_plating", "value"),
            State("input_wd_shift1_tech_blood", "value"),
            State("input_wd_shift1_tech_routine", "value"),
            State("input_wd_shift1_tech_urine", "value"),
            State("input_wd_shift1_tech_new", "value"),
            State("input_wd_shift1_tech_float", "value"), 
            State("input_wd_shift1_plating_capacity", "value"),

            # --- Weekday Shift 2 (8) ---
            State("input_wd_shift2_tech_accession", "value"),
            State("input_wd_shift2_tech_plating", "value"),
            State("input_wd_shift2_tech_blood", "value"),
            State("input_wd_shift2_tech_routine", "value"),
            State("input_wd_shift2_tech_urine", "value"),
            State("input_wd_shift2_tech_new", "value"),
            State("input_wd_shift2_tech_float", "value"),
            State("input_wd_shift2_plating_capacity", "value"),

            # --- Weekday Shift 3 (8) ---
            State("input_wd_shift3_tech_accession", "value"),
            State("input_wd_shift3_tech_plating", "value"),
            State("input_wd_shift3_tech_blood", "value"),
            State("input_wd_shift3_tech_routine", "value"),
            State("input_wd_shift3_tech_urine", "value"),
            State("input_wd_shift3_tech_new", "value"),
            State("input_wd_shift3_tech_float", "value"),
            State("input_wd_shift3_plating_capacity", "value"),

            # --- Weekend Shift 1 (8) ---
            State("input_we_shift1_tech_accession", "value"),
            State("input_we_shift1_tech_plating", "value"),
            State("input_we_shift1_tech_blood", "value"),
            State("input_we_shift1_tech_routine", "value"),
            State("input_we_shift1_tech_urine", "value"),
            State("input_we_shift1_tech_new", "value"),
            State("input_we_shift1_tech_float", "value"),
            State("input_we_shift1_plating_capacity", "value"),

            # --- Weekend Shift 2 (8) ---
            State("input_we_shift2_tech_accession", "value"),
            State("input_we_shift2_tech_plating", "value"),
            State("input_we_shift2_tech_blood", "value"),
            State("input_we_shift2_tech_routine", "value"),
            State("input_we_shift2_tech_urine", "value"),
            State("input_we_shift2_tech_new", "value"),
            State("input_we_shift2_tech_float", "value"),
            State("input_we_shift2_plating_capacity", "value"),

            # --- Weekend Shift 3 (8) ---
            State("input_we_shift3_tech_accession", "value"),
            State("input_we_shift3_tech_plating", "value"),
            State("input_we_shift3_tech_blood", "value"),
            State("input_we_shift3_tech_routine", "value"),
            State("input_we_shift3_tech_urine", "value"),
            State("input_we_shift3_tech_new", "value"),
            State("input_we_shift3_tech_float", "value"),
            State("input_we_shift3_plating_capacity", "value"),
        ],
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
        wd_s1_a, wd_s1_plt, wd_s1_b, wd_s1_r, wd_s1_u, wd_s1_n, wd_s1_f, wd_s1_p,
        # --- Weekday Shift 2 (16-23) ---
        wd_s2_a, wd_s2_plt, wd_s2_b, wd_s2_r, wd_s2_u, wd_s2_n, wd_s2_f, wd_s2_p,
        # --- Weekday Shift 3 (24-31) ---
        wd_s3_a, wd_s3_plt, wd_s3_b, wd_s3_r, wd_s3_u, wd_s3_n, wd_s3_f, wd_s3_p,
        # --- Weekend Shift 1 (32-39) ---
        we_s1_a, we_s1_plt, we_s1_b, we_s1_r, we_s1_u, we_s1_n, we_s1_f, we_s1_p,
        # --- Weekend Shift 2 (40-47) ---
        we_s2_a, we_s2_plt, we_s2_b, we_s2_r, we_s2_u, we_s2_n, we_s2_f, we_s2_p,
        # --- Weekend Shift 3 (48-55) ---
        we_s3_a, we_s3_plt, we_s3_b, we_s3_r, we_s3_u, we_s3_n, we_s3_f, we_s3_p,
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

        shift_staffing_profile = {
            "Weekday": {
                "Shift_1_Day": {"hours": (7, 15), "tech_accession": val(wd_s1_a, 4), "tech_plating": val(wd_s1_plt, 4), "tech_blood": val(wd_s1_b, 1), "tech_routine": val(wd_s1_r, 1), 
                                "tech_urine": val(wd_s1_u, 1), "tech_new": val(wd_s1_n, 1),  "tech_float": val(wd_s1_f, 2),
                                 "plating_capacity": val(wd_s1_p, 2)},
                "Shift_2_Evening": {"hours": (15, 23), "tech_accession": val(wd_s2_a, 4), "tech_plating": val(wd_s2_plt, 4), "tech_blood": val(wd_s2_b, 1), "tech_routine": val(wd_s2_r, 1),
                                "tech_urine": val(wd_s2_u, 1), "tech_new": val(wd_s2_n, 1), "tech_float": val(wd_s2_f, 1),
                                "plating_capacity": val(wd_s2_p, 2)},
                "Shift_3_Night": {"hours": (23, 7), "tech_accession": val(wd_s3_a, 4), "tech_plating": val(wd_s3_plt, 4), "tech_blood": val(wd_s3_b, 1), "tech_routine": val(wd_s3_r, 1),
                                "tech_urine": val(wd_s3_u, 1), "tech_new": val(wd_s3_n, 1),  "tech_float": val(wd_s3_f, 1),
                                "plating_capacity": val(wd_s3_p, 2)},
            },
            "Weekend": {
                "Shift_1_Day": {"hours": (7, 15), "tech_accession": val(we_s1_a, 4), "tech_plating": val(we_s1_plt, 4), "tech_blood": val(we_s1_b, 1), "tech_routine": val(we_s1_r, 1),
                                "tech_urine": val(we_s1_u, 1), "tech_new": val(we_s1_n, 1), "tech_float": val(we_s1_f, 2),
                                "plating_capacity": val(we_s1_p, 2)},
                "Shift_2_Evening": {"hours": (15, 23), "tech_accession": val(we_s2_a, 4), "tech_plating": val(we_s2_plt, 4), "tech_blood": val(we_s2_b, 1), "tech_routine": val(we_s2_r, 1),
                                "tech_urine": val(we_s2_u, 1), "tech_new": val(we_s2_n, 1), "tech_float": val(we_s2_f, 1),
                                "plating_capacity": val(we_s2_p, 2)},
                "Shift_3_Night": {"hours": (23, 7), "tech_accession": val(we_s3_a, 4), "tech_plating": val(we_s3_plt, 4), "tech_blood": val(we_s3_b, 1), "tech_routine": val(we_s3_r, 1), 
                                "tech_urine": val(we_s3_u, 1), "tech_new": val(we_s3_n, 1), "tech_float": val(we_s3_f, 1),
                                "plating_capacity": val(we_s3_p, 2)},
            },
        }

        # df_pivot, df_state, media_usage, _ = run_simulation(
        #     sim_days=sim_days or 7,
        #     seed=seed_num,
        #     instrument_resources=instrument_resources,
        #     shift_staffing_profile=shift_staffing_profile,
        #     # time_plating_mean=float(plating_time if plating_time is not None else 5),
        #     # time_incubation_hours=float(incubation_hours if incubation_hours is not None else 12),
        #     set_progress=set_progress,
        #     save_plots=True,
        # )
        df_pivot, df_state, media_usage, df_ai_features, stochastic_stats = run_simulation(
            sim_days=sim_days,
            seed=seed_num,
            instrument_resources=instrument_resources,
            shift_staffing_profile=shift_staffing_profile,
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
                empty_fig, empty_fig, empty_fig, empty_fig,
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
        fig_wait = Graphing_WaitTime(completed_df)
        fig_media = Graphing_MediaUsage(media_usage)
        fig_review = Graphing_review_milestones_scatter(data)

        columns = [{"name": i, "id": i} for i in df_pivot.columns]

        return (
            total_specs, avg_tat, avg_wait, completion_rate,
            fig_scatter, fig_volume, fig_tech, fig_sample_queue,
            fig_tat, fig_wait, fig_media, fig_review,
            df_pivot.to_dict("records"), columns,
        )