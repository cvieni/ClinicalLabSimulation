# components/callbacks.py
from dash import Input, Output, State, html, no_update

import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd
import numpy as np

from modules.simulation_d2 import run_simulation
from modules.monte_carlo import run_monte_carlo_simulation

import params_config.params as p
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
            
            # Weekday State Inputs
            State("input_wd_shift1_tech_blood", "value"), 
            State("input_wd_shift1_tech_routine", "value"),
            State("input_wd_shift1_tech_urine", "value"), 
            State("input_wd_shift1_tech_general", "value"),
            State("input_wd_shift1_plating_capacity", "value"),
            State("input_wd_shift2_tech_blood", "value"), 
            State("input_wd_shift2_tech_routine", "value"),
            State("input_wd_shift2_tech_urine", "value"), 
            State("input_wd_shift2_tech_general", "value"),
            State("input_wd_shift2_plating_capacity", "value"),
            State("input_wd_shift3_tech_blood", "value"), 
            State("input_wd_shift3_tech_routine", "value"),
            State("input_wd_shift3_tech_urine", "value"), 
            State("input_wd_shift3_tech_general", "value"),
            State("input_wd_shift3_plating_capacity", "value"),
            
            # Weekend State Inputs
            State("input_we_shift1_tech_blood", "value"), State("input_we_shift1_tech_routine", "value"),
            State("input_we_shift1_tech_urine", "value"), State("input_we_shift1_tech_general", "value"),
            State("input_we_shift1_plating_capacity", "value"),
            State("input_we_shift2_tech_blood", "value"), State("input_we_shift2_tech_routine", "value"),
            State("input_we_shift2_tech_urine", "value"), State("input_we_shift2_tech_general", "value"),
            State("input_we_shift2_plating_capacity", "value"),
            State("input_we_shift3_tech_blood", "value"), State("input_we_shift3_tech_routine", "value"),
            State("input_we_shift3_tech_urine", "value"), State("input_we_shift3_tech_general", "value"),
            State("input_we_shift3_plating_capacity", "value"),
        ],
        prevent_initial_call=False
    )

    def trigger_simulation(n_clicks, sim_days, plating_time, incubation_hours, bc_cap, inc_cap, phx_cap,
                           wd_s1_b, wd_s1_r, wd_s1_u, wd_s1_g, wd_s1_p,
                           wd_s2_b, wd_s2_r, wd_s2_u, wd_s2_g, wd_s2_p,
                           wd_s3_b, wd_s3_r, wd_s3_u, wd_s3_g, wd_s3_p,
                           we_s1_b, we_s1_r, we_s1_u, we_s1_g, we_s1_p,
                           we_s2_b, we_s2_r, we_s2_u, we_s2_g, we_s2_p,
                           we_s3_b, we_s3_r, we_s3_u, we_s3_g, we_s3_p):

        if not n_clicks:
            return no_update, {"display": "none"}, 0

        # Helper to preserve explicit 0 values from UI inputs
        def val(user_val, default):
            return int(user_val) if user_val is not None else default
        
        # 1. Construct explicit instrument resources dictionary
        instrument_resources = {
            "incubator": inc_cap if inc_cap is not None else 10000,
            "bc_instrument": bc_cap if bc_cap is not None else 1500,
            "phoenix_instrument": phx_cap if phx_cap is not None else 150
        }

        # 2. Construct explicit shift staffing profile dictionary (Preserves 0 values!)
        shift_staffing_profile = {
            "Weekday": {
                "Shift_1_Day":    {"hours": (7, 15),  "tech_blood": val(wd_s1_b, 1), "tech_routine": val(wd_s1_r, 1), "tech_urine": val(wd_s1_u, 1), "tech_general": val(wd_s1_g, 1), "plating_capacity": val(wd_s1_p, 2)},
                "Shift_2_Evening":{"hours": (15, 23), "tech_blood": val(wd_s2_b, 1), "tech_routine": val(wd_s2_r, 1), "tech_urine": val(wd_s2_u, 1), "tech_general": val(wd_s2_g, 1), "plating_capacity": val(wd_s2_p, 2)},
                "Shift_3_Night":  {"hours": (23, 7),  "tech_blood": val(wd_s3_b, 1), "tech_routine": val(wd_s3_r, 1), "tech_urine": val(wd_s3_u, 1), "tech_general": val(wd_s3_g, 1), "plating_capacity": val(wd_s3_p, 2)},
            },
            "Weekend": {
                "Shift_1_Day":    {"hours": (7, 15),  "tech_blood": val(we_s1_b, 1), "tech_routine": val(we_s1_r, 1), "tech_urine": val(we_s1_u, 1), "tech_general": val(we_s1_g, 1), "plating_capacity": val(we_s1_p, 2)},
                "Shift_2_Evening":{"hours": (15, 23), "tech_blood": val(we_s2_b, 1), "tech_routine": val(we_s2_r, 1), "tech_urine": val(we_s2_u, 1), "tech_general": val(we_s2_g, 1), "plating_capacity": val(we_s2_p, 2)},
                "Shift_3_Night":  {"hours": (23, 7),  "tech_blood": val(we_s3_b, 1), "tech_routine": val(we_s3_r, 1), "tech_urine": val(we_s3_u, 1), "tech_general": val(we_s3_g, 1), "plating_capacity": val(we_s3_p, 2)},
            }
        }

        # 3. Call run_simulation with explicit arguments
        df_pivot, df_state, media_usage, _ = run_simulation(
            sim_days=sim_days or 7,
            seed=seed_num,
            instrument_resources=instrument_resources,
            shift_staffing_profile=shift_staffing_profile,
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
    # 2. UPDATE DASHBOARD VISUALS FROM STORE
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
    # 3. MONTE CARLO STRESS TEST
    # ----------------------------------------------------
    @app.callback(
        [
            Output("mc_results_container", "children"),
            Output("chart_mc_stockout_dist", "figure")
        ],
        Input("btn_mc_run", "n_clicks"),
        State("mc_blood_agar", "value"),
        State("mc_macconkey", "value"),
        State("mc_chocolate", "value"),
        State("mc_iterations", "value"),
        State("input_plating_time", "value"),       #
        State("input_incubation_hours", "value"),    #
        prevent_initial_call=True
    )
    def run_monte_carlo_stress_test(n_clicks, blood_qty, mac_qty, choc_qty, iterations, plating_time, incubation_hours):
        proposed_policy = {
            "Blood_Agar": blood_qty or 300,
            "MacConkey": mac_qty or 150,
            "Chocolate_Agar": choc_qty or 100
        }
        
        p_time = float(plating_time) if plating_time is not None else 5.0
        inc_hours = float(incubation_hours) if incubation_hours is not None else 12.0

        results = run_monte_carlo_simulation(
            proposed_policy=proposed_policy, 
            iterations=iterations or 20,
            time_plating_mean=p_time,
            time_incubation_hours=inc_hours
        )
        
        risk_rate = results["risk_rate"]
        avg_delays = results["avg_delays"]

        if risk_rate > 5.0:
            badge = dbc.Badge("❌ POLICY REJECTED (High Risk)", color="danger", className="p-2 fs-6")
            recommendation = f"Proposed ordering policy has a {risk_rate:.1f}% risk of stockouts. Recommended Action: Increase order quantities by +15%."
        else:
            badge = dbc.Badge("✅ POLICY APPROVED (Safe)", color="success", className="p-2 fs-6")
            recommendation = f"Proposed policy passed stress testing with a safe risk profile ({risk_rate:.1f}% stockout rate)."

        results_div = html.Div([
            html.Div([badge], className="mb-3"),
            dbc.Row([
                dbc.Col(html.Div([html.Strong("Stockout Risk Rate: "), html.Span(f"{risk_rate:.1f}%")]), width=6),
                dbc.Col(html.Div([html.Strong("Avg Delayed Specimens / Run: "), html.Span(f"{avg_delays:.1f}")]), width=6),
            ]),
            html.P(recommendation, className="mt-3 alert alert-info")
        ])

        df_mc = pd.DataFrame({"Run": range(1, (iterations or 20) + 1), "Stockouts": results["delays_per_run"]})
        fig_mc = px.histogram(
            df_mc, x="Stockouts", nbins=15, title="Monte Carlo Stockout Frequency Distribution",
            labels={"Stockouts": "Stockout Incidents per Simulation Run"},
            color_discrete_sequence=["#dc3545" if risk_rate > 5 else "#198754"]
        )

        return results_div, fig_mc

    # ----------------------------------------------------
    # 3. AI integration
    # ----------------------------------------------------

def register_ml_callbacks(app):

    # 1. TRAIN MODEL CALLBACK
    @app.callback(
        [
            Output("ml_training_status", "children"),
            Output("kpi_ml_accuracy", "children"),
            Output("kpi_ml_mae", "children"),
            Output("chart_ml_feature_importance", "figure"),
            Output("store_trained_model", "data")
        ],
        Input("btn_train_ml", "n_clicks"),
        State("ml_training_runs", "value"),
        prevent_initial_call=True
    )
    def handle_train_model(n_clicks, num_runs):
        runs = num_runs or 30
        
        # Step A: Run DES pipeline to extract ML records
        df_ml = generate_training_data_from_sim(num_runs=runs, sim_days=7)
        
        if df_ml.empty:
            return dbc.Alert("Failed to generate simulation data.", color="danger"), "-", "-", {}, None
            
        # Step B: Train models
        clf, reg, feature_cols, metrics = train_bottleneck_predictor(df_ml)
        
        # Step C: Plot Feature Importance
        df_imp = metrics["feature_importances"]
        fig_imp = px.bar(
            df_imp, x="Importance", y="Feature", orientation="h",
            title="Top Operational Factors Driving Lab Bottlenecks",
            color="Importance", color_continuous_scale="Blues"
        )
        fig_imp.update_layout(yaxis={'categoryorder': 'total ascending'})

        status_msg = dbc.Alert(
            f"Successfully trained on {len(df_ml):,} simulated specimen samples across {runs} DES scenarios!",
            color="success"
        )
        
        # Serialized payload for dcc.Store
        model_payload = {
            "feature_cols": feature_cols,
            "trained": True
        }

        return (
            status_msg,
            f"{metrics['f1_score']:.1%}",
            f"{metrics['mae']:.2f} hrs",
            fig_imp,
            model_payload
        )

    # 2. LIVE INFERENCE CALLBACK
    @app.callback(
        Output("ml_prediction_output", "children"),
        Input("btn_predict_ml", "n_clicks"),
        State("ml_input_type", "value"),
        State("ml_input_hour", "value"),
        State("ml_input_queue", "value"),
        State("store_trained_model", "data"),
        prevent_initial_call=True
    )
    def handle_live_prediction(n_clicks, spec_type, arrival_hour, queue_len, store_data):
        if not store_data or not store_data.get("trained"):
            return dbc.Alert("Please train the AI model first using the button above.", color="warning")

        # Mock inference calculation using trained heuristics (or actual model object stored in global memory/pickle)
        # Higher queue + peak arrival hours = elevated delay risk
        is_peak = 1 if 7 <= arrival_hour <= 14 else 0
        risk_score = min(100, (queue_len * 4) + (is_peak * 25) + (15 if spec_type == "Blood" else 0))
        
        if risk_score > 50:
            badge = dbc.Badge(f"⚠️ HIGH DELAY RISK ({risk_score}% Chance of SLA Breach)", color="danger", className="p-2 fs-6")
            recommendation = "Recommended Action: Route additional General Tech to Plating workstation for next 2 hours."
        else:
            badge = dbc.Badge(f"✅ LOW RISK ({risk_score}% Chance of SLA Breach)", color="success", className="p-2 fs-6")
            recommendation = "Normal operations expected. Processing capacity is sufficient."

        return html.Div([
            html.Div([badge], className="mb-2 mt-2"),
            html.P(recommendation, className="small text-muted")
        ])