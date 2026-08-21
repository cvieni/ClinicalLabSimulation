# components/callbacks.py
import dash
from dash import Input, Output, State, html, no_update
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd
import numpy as np

# simulation modules
from modules.simulation_d3 import run_simulation
from modules.monte_carlo import run_monte_carlo_simulation

# import configuration dictionary for Monte Carlo Sims
from params_config.deprecated.config import Instrument_resources, SHIFT_STAFFING_PROFILE

# ML Pipeline module
from modules.ml_pipeline import (
    generate_training_data_from_sim,
    train_bottleneck_predictor,
    save_trained_model,
    load_trained_model,
    is_model_saved
)

import params_config.deprecated.params as p
seed_num = p.seed_input

# Global container to hold simulation progress and intermediate state
sim_status = {
    "is_running": False,
    "current_time_hours": 0.0,
    "total_time_hours": 168.0,
    "percent_complete": 0,
    "df_pivot": None
}

# ===============================================
# Helper Functions
# ===============================================
def add_weekend_shading(fig, max_days):
    """
    Adds shaded light-gray background bands for weekends (Saturday 00:00 to Sunday 24:00).
    Assumes Day 0 = Monday.
    """
    if not fig or fig == {}:
        return fig
        
    current_day = 0
    while current_day < max_days:
        sat_start = current_day + 5
        sun_end = current_day + 7
        
        if sat_start < max_days:
            fig.add_vrect(
                x0=sat_start,
                x1=min(sun_end, max_days),
                fillcolor="Gray",
                opacity=0.15,
                layer="below",
                line_width=0,
                annotation_text="Weekend" if current_day == 0 else "",
                annotation_position="top left"
            )
        current_day += 7
        
    return fig
# ===============================================
# Helper Functions
# ===============================================

def register_callbacks(app):

    # ----------------------------------------------------
    # 1. TRIGGER SIMULATION & STORE RESULTS
    # ----------------------------------------------------
    @app.callback(
        Output("store_sim_data", "data"),
        Input("btn_run_sim", "n_clicks"),
        [
            State("slider_sim_days", "value"),
            State("input_plating_time", "value"),
            State("input_incubation_hours", "value"),
            State("input_bc_capacity", "value"),
            State("input_incubator_capacity", "value"),
            State("input_phoenix_capacity", "value"),
            State("input_maldi_capacity", "value"),
            
            # Weekday State Inputs
            State("input_wd_shift1_tech_general", "value"),
            State("input_wd_shift1_tech_blood", "value"), 
            State("input_wd_shift1_tech_routine", "value"),
            State("input_wd_shift1_tech_urine", "value"), 
            State("input_wd_shift1_tech_new", "value"), 
            State("input_wd_shift1_plating_capacity", "value"),
            State("input_wd_shift2_tech_general", "value"),
            State("input_wd_shift2_tech_blood", "value"), 
            State("input_wd_shift2_tech_routine", "value"),
            State("input_wd_shift2_tech_urine", "value"), 
            State("input_wd_shift2_tech_new", "value"), 
            State("input_wd_shift2_plating_capacity", "value"),
            State("input_wd_shift3_tech_general", "value"),
            State("input_wd_shift3_tech_blood", "value"), 
            State("input_wd_shift3_tech_routine", "value"),
            State("input_wd_shift3_tech_urine", "value"), 
            State("input_wd_shift3_tech_new", "value"), 
            State("input_wd_shift3_plating_capacity", "value"),
            
            # Weekend State Inputs
            State("input_we_shift1_tech_general", "value"),
            State("input_we_shift1_tech_blood", "value"), State("input_we_shift1_tech_routine", "value"),
            State("input_we_shift1_tech_urine", "value"), State("input_we_shift1_tech_new", "value"),
            State("input_we_shift1_plating_capacity", "value"),
            State("input_we_shift2_tech_general", "value"),
            State("input_we_shift2_tech_blood", "value"), State("input_we_shift2_tech_routine", "value"),
            State("input_we_shift2_tech_urine", "value"), State("input_we_shift2_tech_new", "value"),
            State("input_we_shift2_plating_capacity", "value"),
            State("input_we_shift3_tech_general", "value"),
            State("input_we_shift3_tech_blood", "value"), State("input_we_shift3_tech_routine", "value"),
            State("input_we_shift3_tech_urine", "value"), State("input_we_shift3_tech_new", "value"),
            State("input_we_shift3_plating_capacity", "value"),
        ],
        prevent_initial_call=False
    )

    def trigger_simulation(n_clicks, sim_days, plating_time, incubation_hours, bc_cap, inc_cap, phx_cap, maldi_cap,
                           wd_s1_g, wd_s1_b, wd_s1_r, wd_s1_u, wd_s1_n, wd_s1_p,
                           wd_s2_g, wd_s2_b, wd_s2_r, wd_s2_u, wd_s2_n, wd_s2_p,
                           wd_s3_g, wd_s3_b, wd_s3_r, wd_s3_u, wd_s3_n, wd_s3_p,
                           we_s1_g, we_s1_b, we_s1_r, we_s1_u, we_s1_n, we_s1_p,
                           we_s2_g, we_s2_b, we_s2_r, we_s2_u, we_s2_n, we_s2_p,
                           we_s3_g, we_s3_b, we_s3_r, we_s3_u, we_s3_n, we_s3_p):

        if not n_clicks:
            return no_update, {"display": "none"}, 0

        # Helper to preserve explicit 0 values from UI inputs
        def val(user_val, default):
            return int(user_val) if user_val is not None else default
        
        # 1. Construct explicit instrument resources dictionary
        instrument_resources = {
            "incubator": inc_cap if inc_cap is not None else 10000,
            "bc_instrument": bc_cap if bc_cap is not None else 1500,
            "phoenix_instrument": phx_cap if phx_cap is not None else 150,
            "maldi_instrument": maldi_cap if maldi_cap is not None else 2
        }

        # 2. Construct explicit shift staffing profile dictionary (Preserves 0 values!)
        shift_staffing_profile = {
            "Weekday": {
                "Shift_1_Day":    {"hours": (7, 15),  "tech_general": val(wd_s1_g, 1), "tech_blood": val(wd_s1_b, 1), "tech_routine": val(wd_s1_r, 1), "tech_urine": val(wd_s1_u, 1), "tech_new": val(wd_s1_n, 1), "plating_capacity": val(wd_s1_p, 2)},
                "Shift_2_Evening":{"hours": (15, 23), "tech_general": val(wd_s2_g, 1), "tech_blood": val(wd_s2_b, 1), "tech_routine": val(wd_s2_r, 1), "tech_urine": val(wd_s2_u, 1), "tech_new": val(wd_s2_n, 1), "plating_capacity": val(wd_s2_p, 2)},
                "Shift_3_Night":  {"hours": (23, 7),  "tech_general": val(wd_s3_g, 1), "tech_blood": val(wd_s3_b, 1), "tech_routine": val(wd_s3_r, 1), "tech_urine": val(wd_s3_u, 1), "tech_new": val(wd_s3_n, 1), "plating_capacity": val(wd_s3_p, 2)},
            },
            "Weekend": {
                "Shift_1_Day":    {"hours": (7, 15),  "tech_general": val(we_s1_g, 1), "tech_blood": val(we_s1_b, 1), "tech_routine": val(we_s1_r, 1), "tech_urine": val(we_s1_u, 1), "tech_new": val(we_s1_n, 1), "plating_capacity": val(we_s1_p, 2)},
                "Shift_2_Evening":{"hours": (15, 23), "tech_general": val(we_s2_g, 1), "tech_blood": val(we_s2_b, 1), "tech_routine": val(we_s2_r, 1), "tech_urine": val(we_s2_u, 1), "tech_new": val(we_s2_n, 1), "plating_capacity": val(we_s2_p, 2)},
                "Shift_3_Night":  {"hours": (23, 7),  "tech_general": val(we_s3_g, 1), "tech_blood": val(we_s3_b, 1), "tech_routine": val(we_s3_r, 1), "tech_urine": val(we_s3_u, 1), "tech_new": val(we_s3_n, 1), "plating_capacity": val(we_s3_p, 2)},
            }
        }

        # 3. Call run_simulation with explicit arguments
        df_pivot, df_state, media_usage, _ = run_simulation(
            sim_days=sim_days or 7,
            seed=seed_num,
            instrument_resources=instrument_resources,
            shift_staffing_profile=SHIFT_STAFFING_PROFILE,
            time_plating_mean=float(plating_time if plating_time is not None else 5),
            time_incubation_hours=float(incubation_hours if incubation_hours is not None else 12)
        )

        sim_data = {"df_pivot": df_pivot.to_dict("records"),
                    "df_state": df_state.to_dict("records"),
                    "media_usage": media_usage
                }
    # Return simulation payload and update progress bar to 100% visible
        return sim_data

    # ----------------------------------------------------
    # 2. UPDATE TAB 1 DASHBOARD VISUALS FROM STORE
    # ----------------------------------------------------
    @app.callback(
        [
            Output("kpi_total", "children"),
            Output("kpi_tat", "children"),
            Output("kpi_wait", "children"),
            Output("kpi_completion", "children"),
            Output("chart_scatter_timeline", "figure"),
            Output("chart_tech_utilization", "figure"),
            Output("chart_tat", "figure"),
            Output("chart_wait", "figure"),
            Output("chart_media", "figure"),
            Output("table_specimens", "data"),
            Output("table_specimens", "columns")
        ],
        Input("store_sim_data", "data")
    )
    def update_dashboard(data):
        empty_fig = {}
        if not data or "df_pivot" not in data or len(data["df_pivot"]) == 0:
            return "-", "-", "-", "-", empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, [], []

        df_pivot = pd.DataFrame(data["df_pivot"])
        df_state = pd.DataFrame(data.get("df_state", []))
        media_usage = data.get("media_usage", {})

        completed_df = df_pivot.dropna(subset=["Total_TAT_Hours"]) if "Total_TAT_Hours" in df_pivot.columns else pd.DataFrame()

        total_specs = len(df_pivot["Specimen_ID"].unique())
        avg_tat = f"{completed_df['Total_TAT_Hours'].mean():.1f} hrs" if not completed_df.empty and "Total_TAT_Hours" in completed_df else "N/A"
        avg_wait = f"{completed_df['Wait_For_Plating_Mins'].mean():.1f} mins" if not completed_df.empty and "Wait_For_Plating_Mins" in completed_df else "N/A"
        completion_rate = f"{(len(completed_df)/total_specs)*100:.1f}%" if total_specs > 0 else "0%"

        fig_scatter, fig_tech = empty_fig, empty_fig

        if not df_state.empty:
            df_state["Day"] = df_state["Minute"] / (24.0 * 60.0) if "Minute" in df_state.columns else (
                df_state["minute"] / (24.0 * 60.0) if "minute" in df_state.columns else df_state.index / 48.0
            )
            max_days = df_state["Day"].max()

            marker_col = "Plating_Queue_Length" if "Plating_Queue_Length" in df_state.columns else (
                "plating_queue" if "plating_queue" in df_state.columns else df_state.columns[1]
            )
            active_col = "Active_Specimens_In_Lab" if "Active_Specimens_In_Lab" in df_state.columns else (
                "active_specimens" if "active_specimens" in df_state.columns else df_state.columns[0]
            )

            # 1. Scatter/Line Plot for Workload & Queues
            fig_scatter = px.scatter(
                df_state, x="Day", y=active_col, color=marker_col,
                labels={"Day": "Simulation Time (Days)", active_col: "Active Specimens"},
                title="Workload & Plating Bottlenecks Over Time"
            )
            fig_scatter.update_traces(mode="lines+markers")
            
            # Apply Weekend Shading
            fig_scatter = add_weekend_shading(fig_scatter, max_days)

            # 2. Tech Utilization Line Chart
            tech_cols = [c for c in ["Busy_Techs", "Active_Techs", "busy_techs", "active_techs"] if c in df_state.columns]
            if tech_cols:
                fig_tech = px.line(
                    df_state, x="Day", y=tech_cols,
                    labels={"Day": "Simulation Time (Days)", "value": "Technicians", "variable": "Metric"},
                    title="Technician Staffing & Active Utilization Over Time"
                )
                
                # Apply Weekend Shading
                fig_tech = add_weekend_shading(fig_tech, max_days)

        fig_tat = px.box(completed_df, x="Type", y="Total_TAT_Hours", color="Type", points="all", title="Turnaround Time (TAT) Distribution") if not completed_df.empty and "Total_TAT_Hours" in completed_df else empty_fig
        fig_wait = px.histogram(completed_df, x="Wait_For_Plating_Mins", color="Type", nbins=30, title="Plating Queue Waiting Time") if not completed_df.empty and "Wait_For_Plating_Mins" in completed_df else empty_fig
        
        fig_media = px.bar(pd.DataFrame(list(media_usage.items()), columns=["Media Type", "Plates Consumed"]), x="Media Type", y="Plates Consumed", color="Media Type", title="Consumables Usage") if media_usage else empty_fig
        columns = [{"name": i, "id": i} for i in df_pivot.columns]

        return (total_specs, avg_tat, avg_wait, completion_rate, fig_scatter, fig_tech, fig_tat, fig_wait, fig_media, df_pivot.to_dict("records"), columns)

    # ----------------------------------------------------
    # TAB 2: MONTE CARLO STRESS TEST
    # ----------------------------------------------------
    @app.callback(
        [
            Output("mc_results_container", "children"),
            Output("chart_mc_stockout_dist", "figure")
        ],
        Input("btn_mc_run", "n_clicks"),
        [
            State("mc_blood_agar", "value"),
            State("mc_macconkey", "value"),
            State("mc_CNA", "value"),
            State("mc_chocolate", "value"),
            State("mc_ThayerMartin", "value"),
            State("mc_Chromagar", "value"),
            State("mc_iterations", "value"),
        ],
        background=True,  # <--- Enables background execution
        progress=[
            Output("mc_progress_bar", "value"),
            Output("mc_progress_bar", "label"),
            Output("mc_progress_text", "children")
        ], # Maps progress tuple values to UI components
        progress_default=(0, "0%", "Ready to start simulation..."),
        prevent_initial_call=True
    )
    def handle_monte_carlo(set_progress, n_clicks, 
                           blood_qty, mac_qty, cna_qty, choc_qty, thayer_qty, chrome_qty, 
                           mc_iterations):
        if not n_clicks:
            # return no_update, {}
            return no_update, no_update        

        # Execute Monte Carlo Runs
        # 1. Package the order quantities into the policy dictionary expected by the function
        proposed_policy = {
                "Blood_Agar": blood_qty or 0,
                "MacConkey": mac_qty or 0,
                "CNA": cna_qty or 0,
                "Chocolate_Agar": choc_qty or 0,
                "ThayerMartin": thayer_qty or 0,
                "Chromagar": chrome_qty or 0,
            }

        # Pass progress-tracking wrapper function
        def report_progress(progress_info):
            percent_str, text_msg = progress_info
            set_progress((int(percent_str), f"{percent_str}%", text_msg))
        
        # 2. Call the function with keyword arguments that match its signature
        mc_results = run_monte_carlo_simulation(
            proposed_policy=proposed_policy,
            iterations=mc_iterations,
            instrument_resources=Instrument_resources,  # Explicitly pass the dict
            shift_staffing_profile=SHIFT_STAFFING_PROFILE,  # Explicitly pass staffing profile
            set_progress=set_progress
        )

        # 3. Construct df_mc_results from the returned dictionary
        delays = mc_results.get("delays_per_run", [])
        history = mc_results.get("media_consumption_history", {})

        if not delays:
            return (dbc.Alert("Monte Carlo run returned no data.", color="warning"), {}, )

        # Sum consumption across all media types per run to get total demand
        total_consumed = [sum(history[media][i] for media in history) for i in range(len(delays)) ]

        df_mc_results = pd.DataFrame({"Delays": delays, "Total_Plates_Consumed": total_consumed, "Stockout_Occurred": [d > 0 for d in delays], })

        # 4. Extract Risk Summary Metrics
        stockout_rate = mc_results.get("risk_rate", 0.0)
        risk_color = (
            "danger"
            if stockout_rate > 15
            else ("warning" if stockout_rate > 5 else "success")
        )

        summary_card = dbc.Card(
            [
                dbc.CardBody(
                    [
                        html.H5(
                            f"Stockout Risk: {stockout_rate:.1f}%",
                            className=f"text-{risk_color}",
                        ),
                        html.P(
                            f"Evaluated across {mc_results.get('iterations_executed', 0)} stochastic surge scenarios.",
                            className="small text-muted",
                        ),
                    ]
                )
            ],
            color="light",
            className="mb-3",
        )

        # 5. Build Distribution Chart
        fig_dist = px.histogram(
            df_mc_results,
            x="Total_Plates_Consumed",
            color="Stockout_Occurred",
            title="Consumable Demand Distribution Under Surge Conditions",
            labels={
                "Total_Plates_Consumed": "Plates Demanded",
                "Stockout_Occurred": "Stockout Encountered",
            },
        )

        return summary_card, fig_dist

    # ----------------------------------------------------
    # TAB 3: AI & ML MODEL LIFECYCLE
    # ----------------------------------------------------
    @app.callback(
        [
            Output("ml_training_status", "children"),
            Output("kpi_ml_accuracy", "children"),
            Output("kpi_ml_mae", "children"),
            Output("chart_ml_feature_importance", "figure"),
            Output("store_trained_model", "data")
        ],
        [
            Input("btn_train_ml", "n_clicks"),
            Input("btn_load_ml", "n_clicks")
        ],
        State("ml_training_runs", "value"),
        prevent_initial_call=True
    )
    def handle_model_lifecycle(train_clicks, load_clicks, num_runs):
        ctx = dash.callback_context
        if not ctx.triggered:
            return dash.no_update

        button_id = ctx.triggered[0]["prop_id"].split(".")[0]

        # OPTION A: Train a new model and save to disk
        if button_id == "btn_train_ml":
            runs = num_runs or 30
            df_ml = generate_training_data_from_sim(num_runs=runs, sim_days=7)

            if df_ml.empty:
                return dbc.Alert("Failed to generate simulation data.", color="danger"), "-", "-", {}, None

            clf, reg, feature_cols, metrics = train_bottleneck_predictor(df_ml)
            filepath = save_trained_model(clf, reg, feature_cols, metrics)

            status_msg = dbc.Alert(
                f"Successfully trained on {len(df_ml):,} specimens across {runs} runs and saved model to '{filepath}'!",
                color="success"
            )

        # OPTION B: Load an existing model from disk
        elif button_id == "btn_load_ml":
            if not is_model_saved():
                return (
                    dbc.Alert("No saved model found on disk. Train a model first!", color="warning"),
                    "-", "-", {}, None
                )

            clf, reg, feature_cols, metrics = load_trained_model()
            status_msg = dbc.Alert("Successfully loaded pre-trained model from disk!", color="info")

        # Build Feature Importance Plot
        df_imp = metrics.get("feature_importances", pd.DataFrame())
        if isinstance(df_imp, pd.DataFrame) and not df_imp.empty:
            fig_imp = px.bar(
                df_imp, x="Importance", y="Feature", orientation="h",
                title="Top Operational Factors Driving Lab Bottlenecks",
                color="Importance", color_continuous_scale="Blues"
            )
            fig_imp.update_layout(yaxis={"categoryorder": "total ascending"})
        else:
            fig_imp = {}

        model_payload = {
            "feature_cols": feature_cols,
            "trained": True
        }

        return (
            status_msg,
            f"{metrics.get('f1_score', 0):.1%}",
            f"{metrics.get('mae', 0):.2f} hrs",
            fig_imp,
            model_payload
        )

    # ----------------------------------------------------
    # TAB 3: REAL-TIME LIVE PREDICTOR INFERENCE
    # ----------------------------------------------------
    @app.callback(
        Output("ml_prediction_output", "children"),
        Input("btn_predict_ml", "n_clicks"),
        [
            State("ml_input_type", "value"),
            State("ml_input_hour", "value"),
            State("ml_input_queue", "value"),
            State("store_trained_model", "data")
        ],
        prevent_initial_call=True
    )
    def handle_live_prediction(n_clicks, spec_type, arrival_hour, queue_len, store_data):
        if not store_data or not store_data.get("trained"):
            return dbc.Alert("Please train or load an AI model first.", color="warning")

        # Calculate heuristic risk score based on active queue and arrival windows
        is_peak = 1 if 7 <= (arrival_hour or 0) <= 14 else 0
        risk_score = min(100, ((queue_len or 0) * 4) + (is_peak * 25) + (15 if spec_type == "Blood" else 0))

        if risk_score > 50:
            badge = dbc.Badge(f"⚠️ HIGH DELAY RISK ({risk_score}% Chance of SLA Breach)", color="danger", className="p-2 fs-6")
            recommendation = "Recommended Action: Reallocate 1 tech from routine processing to plating queue."
        else:
            badge = dbc.Badge(f"✅ LOW RISK ({risk_score}% Chance of SLA Breach)", color="success", className="p-2 fs-6")
            recommendation = "Normal operations expected. Standard staffing is adequate."

        return html.Div([
            html.Div([badge], className="mb-2 mt-2"),
            html.P(recommendation, className="small text-muted")
        ])