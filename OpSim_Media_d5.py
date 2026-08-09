# app.py
import dash
from dash import dcc, html, Input, Output, State, dash_table
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd
import numpy as np

from modules.simulation_d1 import run_simulation
from modules.config import MEDIA_CONFIG

sim_max_time = 31

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

app.layout = dbc.Container([
    html.H2("🧪 Microbiology Lab Operational Simulator & AI Bounding Engine", className="mt-3 mb-3 text-primary"),
    html.P("Simulate lab workflows, identify bottlenecks, and stress-test proposed media ordering policies against stockout risks."),
    
    dbc.Tabs([
        # ------------------ TAB 1: OPERATIONAL SIMULATION ------------------
        dcc.Tab(label="📊 Operational Dashboard", children=[
            dbc.Row([
                # Sidebar Controls
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(html.H5("⚙️ Simulation Controls")),
                        dbc.CardBody([
                            html.Label("Duration (Days):"),
                            dcc.Slider(id="sim_days", min=1, max=sim_max_time, step=1, value=3, marks={i: str(i) for i in range(1, sim_max_time, 2)}),
                            
                            html.Label("Random Seed:", className="mt-2"),
                            dbc.Input(id="seed", type="number", value=42),
                            
                            html.Hr(),
                            html.H6("Workstation Capacities"),
                            html.Label("Plating Benches:"),
                            dcc.Slider(id="cap_plating", min=1, max=10, step=1, value=2),
                            
                            html.Label("Lab Technicians:", className="mt-2"),
                            dcc.Slider(id="cap_techs", min=1, max=10, step=1, value=3),
                            
                            html.Label("Incubator Capacity:", className="mt-2"),
                            dcc.Slider(id="cap_incubators", min=1000, max=10000, step=10, value=5000),
                            
                            html.Hr(),
                            html.H6("Processing Times"),
                            html.Label("Mean Plating Time (mins):"),
                            dcc.Slider(id="time_plating", min=0.5, max=20, step=0.5, value=3),
                            
                            html.Label("Mean Incubation (hours):", className="mt-2"),
                            dcc.Slider(id="time_incubation", min=12, max=48, step=2, value=24),
                            
                            dbc.Button("🚀 Run Simulation", id="btn_run", color="primary", className="w-100 mt-4")
                        ])
                    ], className="shadow-sm mt-3")
                ], width=3),
                
                # Main Plots & Metrics
                dbc.Col([
                    dbc.Row([
                        dbc.Col(dbc.Card([dbc.CardBody([html.H6("Total Specimens"), html.H3(id="kpi_total", children="-")])], color="light")),
                        dbc.Col(dbc.Card([dbc.CardBody([html.H6("Avg TAT"), html.H3(id="kpi_tat", children="-")])], color="light")),
                        dbc.Col(dbc.Card([dbc.CardBody([html.H6("Avg Wait Mins"), html.H3(id="kpi_wait", children="-")])], color="light")),
                        dbc.Col(dbc.Card([dbc.CardBody([html.H6("Completion Rate"), html.H3(id="kpi_completion", children="-")])], color="light")),
                    ], className="mb-4 mt-3"),
                    
                    dcc.Tabs([
                        dcc.Tab(label="📈 Workload & Queues", children=[dcc.Graph(id="chart_scatter_timeline")]),
                        dcc.Tab(label="📊 Turnaround Times", children=[dcc.Graph(id="chart_tat")]),
                        dcc.Tab(label="⏳ Queue Distribution", children=[dcc.Graph(id="chart_wait")]),
                        dcc.Tab(label="📦 Consumables Usage", children=[dcc.Graph(id="chart_media")]),
                    ]),
                    
                    html.H5("🔍 Specimen Timestamps Log", className="mt-4"),
                    dash_table.DataTable(
                        id="table_specimens",
                        page_size=8,
                        style_table={'overflowX': 'auto'},
                        style_cell={'textAlign': 'left', 'padding': '8px'},
                        style_header={'backgroundColor': '#f8f9fa', 'fontWeight': 'bold'}
                    )
                ], width=9)
            ])
        ]),
        
        # ------------------ TAB 2: MONTE CARLO STRESS TEST ------------------
        dcc.Tab(label="🛡️ AI Order Bounding & Stress Test", children=[
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(html.H5("🎯 Proposed AI Media Order Policy")),
                        dbc.CardBody([
                            html.P("Input proposed order quantities to test them against stochastic surge conditions."),
                            
                            html.Label("Blood Agar Order Qty:"),
                            dbc.Input(id="mc_blood_agar", type="number", value=300),
                            
                            html.Label("MacConkey Order Qty:", className="mt-2"),
                            dbc.Input(id="mc_macconkey", type="number", value=150),
                            
                            html.Label("Chocolate Agar Order Qty:", className="mt-2"),
                            dbc.Input(id="mc_chocolate", type="number", value=100),
                            
                            html.Hr(),
                            html.Label("Monte Carlo Iterations:"),
                            dcc.Slider(id="mc_iterations", min=10, max=100, step=10, value=20, marks={i: str(i) for i in range(10, 101, 20)}),
                            
                            dbc.Button("🛡️ Run Monte Carlo Stress Test", id="btn_mc_run", color="danger", className="w-100 mt-4")
                        ])
                    ], className="shadow-sm mt-3")
                ], width=4),
                
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(html.H5("📊 Stress Test Risk Assessment")),
                        dbc.CardBody([
                            html.Div(id="mc_results_container", children=[
                                html.P("Click 'Run Monte Carlo Stress Test' to evaluate order risk profile.", className="text-muted")
                            ])
                        ])
                    ], className="shadow-sm mt-3"),
                    
                    dcc.Graph(id="chart_mc_stockout_dist", className="mt-3")
                ], width=8)
            ])
        ])
    ]),
    
    dcc.Store(id="store_sim_data")
], fluid=True)


# =============================================================================
# CALLBACKS: TAB 1 SIMULATION
# =============================================================================
@app.callback(
    Output("store_sim_data", "data"),
    Input("btn_run", "n_clicks"),
    State("sim_days", "value"),
    State("seed", "value"),
    State("cap_plating", "value"),
    State("cap_techs", "value"),
    State("cap_incubators", "value"),
    State("time_plating", "value"),
    State("time_incubation", "value"),
    prevent_initial_call=True
)
def trigger_simulation(n_clicks, days, seed, plating, techs, incubators, time_plating, time_incubation):
    df_pivot, df_state, media_usage, _ = run_simulation(
        sim_days=days,
        seed=seed,
        cap_plating=plating,
        cap_techs=techs,
        cap_incubators=incubators,
        time_plating_mean=time_plating,
        time_incubation_hours=time_incubation
    )
    
    return {
        "df_pivot": df_pivot.to_dict("records") if not df_pivot.empty else [],
        "df_state": df_state.to_dict("records") if not df_state.empty else [],
        "media_usage": media_usage
    }


@app.callback(
    [
        Output("kpi_total", "children"),
        Output("kpi_tat", "children"),
        Output("kpi_wait", "children"),
        Output("kpi_completion", "children"),
        Output("chart_scatter_timeline", "figure"),
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
        return "-", "-", "-", "-", empty_fig, empty_fig, empty_fig, empty_fig, [], []

    df_pivot = pd.DataFrame(data["df_pivot"])
    df_state = pd.DataFrame(data.get("df_state", []))
    media_usage = data.get("media_usage", {})

    completed_df = df_pivot.dropna(subset=["Total_TAT_Hours"]) if "Total_TAT_Hours" in df_pivot.columns else pd.DataFrame()

    total_specs = len(df_pivot["Specimen_ID"].unique())
    avg_tat = f"{completed_df['Total_TAT_Hours'].mean():.1f} hrs" if not completed_df.empty else "N/A"
    avg_wait = f"{completed_df['Wait_For_Plating_Mins'].mean():.1f} mins" if not completed_df.empty else "N/A"
    completion_rate = f"{(len(completed_df)/total_specs)*100:.1f}%" if total_specs > 0 else "0%"

    if not df_state.empty:
        # -------------------------------------------------------------
        # CONVERT HOURS TO DAYS
        # -------------------------------------------------------------
        df_state["Day"] = df_state["Hour"] / 24.0
        df_state["Marker_Size"] = df_state["Plating_Queue_Length"].apply(lambda x: max(x, 1) * 3)
        
        fig_scatter = px.scatter(
            df_state,
            x="Day", 
            y="Active_Specimens_In_Lab",
            size="Marker_Size",
            color="Plating_Queue_Length",
            labels={
                "Day": "Simulation Time (Days)",  # <-- Label updated
                "Active_Specimens_In_Lab": "Active Specimens", 
                "Plating_Queue_Length": "Plating Queue"
            },
            title="Workload & Plating Bottlenecks Over Time"
        )
        fig_scatter.update_traces(mode="lines+markers")
        # -------------------------------------------------------------
        # ADD BOUNDED BOXES / HIGHLIGHT BANDS FOR WEEKENDS
        # -------------------------------------------------------------
        max_days = int(np.ceil(df_state["Day"].max()))
        
        for d in range(0, max_days + 7, 7):
            weekend_start = d + 5  # Saturday 00:00
            weekend_end = d + 7    # Sunday 23:59 / Monday 00:00
            
            # Only add rectangles within the bounds of the simulation timeline
            if weekend_start <= max_days:
                fig_scatter.add_vrect(
                    x0=weekend_start,
                    x1=min(weekend_end, max_days),
                    fillcolor="rgba(108, 117, 125, 0.15)",  # Subtle translucent gray
                    layer="below",
                    line_width=1,
                    line_color="rgba(108, 117, 125, 0.3)",
                    line_dash="dot",
                    annotation_text="Weekend",
                    annotation_position="top left",
                    annotation_font_size=10,
                    annotation_font_color="#6c757d"
                )
                
    else:
        fig_scatter = empty_fig

    fig_tat = px.box(completed_df, x="Type", y="Total_TAT_Hours", color="Type", points="all", title="Turnaround Time (TAT) Distribution") if not completed_df.empty else empty_fig
    fig_wait = px.histogram(completed_df, x="Wait_For_Plating_Mins", color="Type", nbins=30, title="Plating Queue Waiting Time") if not completed_df.empty else empty_fig

    if media_usage:
        media_df = pd.DataFrame(list(media_usage.items()), columns=["Media Type", "Plates Consumed"])
        fig_media = px.bar(media_df, x="Media Type", y="Plates Consumed", color="Media Type", title="Consumables Usage")
    else:
        fig_media = empty_fig

    columns = [{"name": i, "id": i} for i in df_pivot.columns]

    return total_specs, avg_tat, avg_wait, completion_rate, fig_scatter, fig_tat, fig_wait, fig_media, df_pivot.to_dict("records"), columns


# =============================================================================
# CALLBACKS: TAB 2 MONTE CARLO STRESS TEST
# =============================================================================
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
    prevent_initial_call=True
)
def run_monte_carlo_stress_test(n_clicks, blood_qty, mac_qty, choc_qty, iterations):
    proposed_policy = {
        "Blood_Agar": blood_qty or 300,
        "MacConkey": mac_qty or 150,
        "Chocolate_Agar": choc_qty or 100
    }
    
    stockout_delays_per_run = []
    
    for i in range(iterations):
        # Override MEDIA_CONFIG with proposed policy quantities
        test_cfg = MEDIA_CONFIG.copy()
        for media, qty in proposed_policy.items():
            if media in test_cfg:
                test_cfg[media]["order_qty"] = qty

        df_pivot, _, _, _ = run_simulation(
            sim_days=5,
            seed=5000 + i,
            cap_plating=2,
            cap_techs=3,
            cap_incubators=150,
            time_plating_mean=12,
            time_incubation_hours=24
        )

        if "Stockout Delay Started" in df_pivot.columns:
            delays = df_pivot["Stockout Delay Started"].notna().sum()
        else:
            delays = 0
            
        stockout_delays_per_run.append(delays)

    runs_with_stockouts = sum(1 for d in stockout_delays_per_run if d > 0)
    risk_rate = (runs_with_stockouts / iterations) * 100
    avg_delays = np.mean(stockout_delays_per_run)

    # Policy Recommendation Logic
    if risk_rate > 5.0:
        badge = dbc.Badge("❌ POLICY REJECTED (High Risk)", color="danger", className="p-2 fs-6")
        recommendation = f"Proposed ordering policy has a {risk_rate:.1f}% risk of stockouts. Recommended Action: Increase order quantities by +15%."
    else:
        badge = dbc.Badge("✅ POLICY APPROVED (Safe)", color="success", className="p-2 fs-6")
        recommendation = f"Proposed policy passed stress testing with a safe risk profile ({risk_rate:.1f}% stockout rate)."

    results_div = html.Div([
        mb_header := html.Div([badge], className="mb-3"),
        dbc.Row([
            dbc.Col(html.Div([html.Strong("Stockout Risk Rate: "), html.Span(f"{risk_rate:.1f}%")]), width=6),
            dbc.Col(html.Div([html.Strong("Avg Delayed Specimens / Run: "), html.Span(f"{avg_delays:.1f}")]), width=6),
        ]),
        html.P(recommendation, className="mt-3 alert alert-info")
    ])

    # Plot Distribution
    df_mc = pd.DataFrame({"Run": range(1, iterations + 1), "Stockouts": stockout_delays_per_run})
    fig_mc = px.histogram(
        df_mc,
        x="Stockouts",
        nbins=15,
        title="Monte Carlo Stockout Frequency Distribution",
        labels={"Stockouts": "Stockout Incidents per 5-Day Simulation"},
        color_discrete_sequence=["#dc3545" if risk_rate > 5 else "#198754"]
    )

    return results_div, fig_mc


if __name__ == "__main__":
    app.run(debug=True, port=8050)