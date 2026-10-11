# components/layouts.py

import dash
from dash import dcc, html, dash_table
import dash_bootstrap_components as dbc

import params_config.params_d2 as p
from params_config.config_d2 import SHIFT_STAFFING_PROFILE, Instrument_resources

from components.GraphingFunctions_d2 import Graphing_SampleQueue

SIM_MAX_TIME = p.sim_max_time

# ===============================================
# Helper Functions
# ===============================================
# Helper function to get default staffing value cleanly from config
def get_default_tech(day_type, shift_key, tech_key, default=1):
    """
    Looks up values from SHIFT_STAFFING_PROFILE dynamically.
    Maps simplified shift keys ('shift1', 'shift2', 'shift3') to config dict keys.
    """
    shift_map = {
        "shift1": "Shift_1_Day",
        "shift2": "Shift_2_Evening",
        "shift3": "Shift_3_Night"
    }
    config_shift_name = shift_map.get(shift_key, shift_key)
    config_day_name = "Weekday" if day_type == "wd" else "Weekend"

    try:
        return SHIFT_STAFFING_PROFILE[config_day_name][config_shift_name].get(tech_key, default)
    except KeyError:
        return default


def create_shift_inputs(day_type, shift_key, shift_label):
    """Helper to build consistent shift input cards pre-populated with config defaults."""
    
    # Read dynamic defaults from SHIFT_STAFFING_PROFILE
    val_a = get_default_tech(day_type, shift_key, "tech_accession", default=1)
    val_plt = get_default_tech(day_type, shift_key, "tech_plating", default=1)
    val_b = get_default_tech(day_type, shift_key, "tech_blood", default=1)
    val_r = get_default_tech(day_type, shift_key, "tech_routine", default=1)
    val_u = get_default_tech(day_type, shift_key, "tech_urine", default=1)
    val_n = get_default_tech(day_type, shift_key, "tech_new", default=1)
    val_p = get_default_tech(day_type, shift_key, "plating_capacity", default=2)

    return dbc.Card(
        dbc.CardBody([
            html.H6(shift_label, className="card-subtitle mb-2 text-primary"),
            dbc.Row([
                dbc.Col([
                    html.Label("Accessioning Techs", style={"fontSize": "11px"}),
                    dbc.Input(id=f"input_{day_type}_{shift_key}_tech_accession", type="number", value=val_a, min=0, size="sm"),
                ], width=3),
                dbc.Col([
                    html.Label("Plating Techs", style={"fontSize": "11px"}),
                    dbc.Input(id=f"input_{day_type}_{shift_key}_tech_plating", type="number", value=val_plt, min=0, size="sm"),
                ], width=3),
                dbc.Col([
                    html.Label("Blood Techs", style={"fontSize": "11px"}),
                    dbc.Input(id=f"input_{day_type}_{shift_key}_tech_blood", type="number", value=val_b, min=0, size="sm"),
                ], width=3),
                dbc.Col([
                    html.Label("Routine Techs", style={"fontSize": "11px"}),
                    dbc.Input(id=f"input_{day_type}_{shift_key}_tech_routine", type="number", value=val_r, min=0, size="sm"),
                ], width=3),
                dbc.Col([
                    html.Label("Urine Techs", style={"fontSize": "11px"}),
                    dbc.Input(id=f"input_{day_type}_{shift_key}_tech_urine", type="number", value=val_u, min=0, size="sm"),
                ], width=3),
                dbc.Col([
                    html.Label("News Bench", style={"fontSize": "11px"}),
                    dbc.Input(id=f"input_{day_type}_{shift_key}_tech_new", type="number", value=val_n, min=0, size="sm"),
                ], width=3),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([
                    html.Label("Plating Capacity", style={"fontSize": "11px"}),
                    dbc.Input(id=f"input_{day_type}_{shift_key}_plating_capacity", type="number", value=val_p, min=1, size="sm"),
                ], width=6),
            ])
        ]),
        className="mb-2 shadow-sm"
    )


def create_sidebar_controls():
    """Builds the accordion control sidebar initialized from config parameters."""
    
    # Read dynamic defaults from INSTRUMENT_CONFIG (or fallback)
    bc_default = Instrument_resources.get("bc_instrument", 1500) if isinstance(Instrument_resources, dict) else 1500
    inc_default = Instrument_resources.get("incubator", 10000) if isinstance(Instrument_resources, dict) else 10000
    phx_default = Instrument_resources.get("phoenix_instrument", 150) if isinstance(Instrument_resources, dict) else 150
    maldi_default = Instrument_resources.get("maldi_instrument", 2) if isinstance(Instrument_resources, dict) else 2

    return html.Div([
        html.H4("Simulation Settings", className="mb-3"),
        dbc.Accordion([
            # GROUP 1: General & Instruments
            dbc.AccordionItem([
                html.Label("Simulation Duration (Days)"),
                dcc.Slider(
                    id="slider_sim_days",
                    min=1, max=SIM_MAX_TIME,
                    step=1, value=7,
                    marks={1: "1d", 7: "7d", 14: "14d", 21: "21d", 31: "31d"}
                ),
                html.Hr(),

                # GROUP 2: Process Timing Inputs
                html.Label("Avg Plating Time (Minutes)"),
                dcc.Slider(
                    id="input_plating_time",
                    min=1, max=10,
                    step=1, value=5,
                    marks={1: "1m", 3: "3m", 5: "5m", 10: "10m"}
                ),

                html.Label("Incubation Duration (Hours)", className="mt-2"),
                dcc.Slider(
                    id="input_incubation_hours",
                    min=6, max=24,
                    step=1, value=12,
                    marks={6: "6h", 12: "12h", 18: "18h", 24: "24h"}
                ),
                html.Hr(),

                # GROUP 3: Instrument Capacities bound to INSTRUMENT_CONFIG defaults
                html.Label("Blood Culture Capacity"),
                dbc.Input(id="input_bc_capacity", type="number", value=bc_default, size="sm", className="mb-2"),
                html.Label("Incubator Capacity"),
                dbc.Input(id="input_incubator_capacity", type="number", value=inc_default, size="sm", className="mb-2"),
                html.Label("Phoenix Capacity"),
                dbc.Input(id="input_phoenix_capacity", type="number", value=phx_default, size="sm", className="mb-2"),
                html.Label("Number of MALDI-TOF Instruments"),
                dbc.Input(id="input_maldi_capacity", type="number", value=maldi_default, size="sm", className="mb-2"),
            ], title="⚙️ General & Instrument Capacities"),

            # GROUP 2: Weekday Staffing
            dbc.AccordionItem([
                create_shift_inputs("wd", "shift1", "Shift 1: Day (07:00 - 15:00)"),
                create_shift_inputs("wd", "shift2", "Shift 2: Evening (15:00 - 23:00)"),
                create_shift_inputs("wd", "shift3", "Shift 3: Night (23:00 - 07:00)"),
            ], title="👨‍🔬 Weekday Tech Staffing"),

            # GROUP 3: Weekend Staffing
            dbc.AccordionItem([
                create_shift_inputs("we", "shift1", "Shift 1: Day (07:00 - 15:00)"),
                create_shift_inputs("we", "shift2", "Shift 2: Evening (15:00 - 23:00)"),
                create_shift_inputs("we", "shift3", "Shift 3: Night (23:00 - 07:00)"),
            ], title="🏖️ Weekend Tech Staffing"),
        ], start_collapsed=True, always_open=False),

        dbc.Button("🚀 Run Simulation", id="btn_run_sim", color="primary", className="w-100 mt-3"),
        html.Div(id="simulation-output-container")
    ])


def get_main_layout():
    """Assembles the primary Dash application layout."""
    return dbc.Container([
        html.H2("🧪 Microbiology Lab Operational Simulator & AI Bounding Engine", className="mt-3 mb-3 text-primary"),
        html.P("Simulate lab workflows, identify bottlenecks, and stress-test proposed media ordering policies against stockout risks."),

        dbc.Tabs([
            # TAB 1: OPERATIONAL DASHBOARD
            dcc.Tab(label="📊 Operational Dashboard", children=[
                dbc.Row([
                    dbc.Col(create_sidebar_controls(), width=3),

                    dbc.Col([
                        # ----------------------------------------------------
                        # PROGRESS BAR CONTAINER (MOVED ABOVE KPI INDEXES)
                        # ----------------------------------------------------
                        html.Div([
                            html.H6("Progress Bar", className="fw-bold mb-2"),
                            dbc.Progress(id="sim_progress_bar", value=0, label="0%", striped=True, animated=True, className="mb-1"),
                            html.P(id="sim_progress_text", className="text-muted small text-center mb-0")
                        ], id="sim_progress_container", className="mt-3 mb-2"),

                        # KPI CARDS ROW
                        dbc.Row([
                            dbc.Col(dbc.Card([dbc.CardBody([html.H6("Total Specimens"), html.H3(id="kpi_total", children="-")])], color="light")),
                            dbc.Col(dbc.Card([dbc.CardBody([html.H6("Avg TAT"), html.H3(id="kpi_tat", children="-")])], color="light")),
                            dbc.Col(dbc.Card([dbc.CardBody([html.H6("Avg Wait Mins"), html.H3(id="kpi_wait", children="-")])], color="light")),
                            dbc.Col(dbc.Card([dbc.CardBody([html.H6("Completion Rate"), html.H3(id="kpi_completion", children="-")])], color="light")),
                        ], className="mb-4"),

                        dcc.Tabs([
                            dcc.Tab(label="📈 Workload & Queues", children=[dcc.Graph(id="chart_scatter_timeline")]),
                            dcc.Tab(label="📈 Sample Volume Trends", children=[dcc.Graph(id="chart_sample_volumes_line")]),
                            dcc.Tab(label="👨‍🔬 Tech Utilization Over Time", children=[
                                dcc.Graph(id="chart_tech_utilization"), 
                                html.Hr(className="my-4"),
                                html.H5("🔥 Resource Bottleneck & Queue Diagnostic", className="mt-3 mb-2 text-secondary"),
                                dcc.Graph(id="chart_queue_diagnostic")
                                ]),
                            dcc.Tab(label="📊 Turnaround Times", children=[dcc.Graph(id="chart_tat")]),
                            dcc.Tab(label="⏳ Queue Distribution", children=[dcc.Graph(id="chart_wait")]),
                            dcc.Tab(label="📦 Consumables Usage", children=[dcc.Graph(id="chart_media")]),
                            dcc.Tab(label="🔬 Review Milestones Scatter", children=[dcc.Graph(id="chart_review_milestones")]),
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

            # TAB 2: MONTE CARLO STRESS TEST
            dcc.Tab(label="🛡️ AI Order Bounding & Monte Carlo Simulation Stress Test", children=[
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
                                html.Label("CNA Order Qty:", className="mt-2"),
                                dbc.Input(id="mc_CNA", type="number", value=100),
                                html.Label("Chocolate Agar Order Qty:", className="mt-2"),
                                dbc.Input(id="mc_chocolate", type="number", value=50),
                                html.Label("ThayerMartin Order Qty:", className="mt-2"),
                                dbc.Input(id="mc_ThayerMartin", type="number", value=50),
                                html.Label("Chromagar Order Qty:", className="mt-2"),
                                dbc.Input(id="mc_Chromagar", type="number", value=50),

                                html.Hr(),
                                html.Label("Monte Carlo Iterations:"),
                                dcc.Slider(
                                    id="mc_iterations",
                                    min=10, max=100,
                                    step=10, value=20,
                                    marks={i: str(i) for i in range(10, 101, 20)}
                                ),
                                dbc.Button("🛡️ Run Monte Carlo Stress Test", id="btn_mc_run", color="danger", className="w-100 mt-4")
                            ])
                        ], className="shadow-sm mt-3")
                    ], width=4),
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader(html.H5("📊 Stress Test Risk Assessment")),
                            dbc.CardBody([
                                # PROGRESS BAR SECTION -------
                                html.Div([
                                    dbc.Progress(id="mc_progress_bar", value=0, label="0%", striped=True, animated=True, className="mb-2"),
                                    html.P(id="mc_progress_text", className="text-muted small text-center")
                                ], className="my-3"),
                                # Results contains ----
                                html.Div(id="mc_results_container", children=[
                                    html.P("Click 'Run Monte Carlo Stress Test' to evaluate order risk profile.", className="text-muted")
                                ])
                            ])
                        ], className="shadow-sm mt-3"),
                        dcc.Graph(id="chart_mc_stockout_dist", className="mt-3")
                    ], width=8)
                ])
            ]),

            # TAB 3: AI & ML BOTTLENECK PREDICTOR
            dcc.Tab(label="🤖 AI Bottleneck Predictor", children=[
                dbc.Row([
                    # Left Column: Controls & Training
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader(html.H5("⚙️ Model Training Pipeline")),
                            dbc.CardBody([
                                html.P("Generate synthetic training data from DES runs and train Random Forest models to predict TAT bottlenecks.", className="text-muted style-sm"),
                                html.Label("Training Runs (DES Scenarios):"),
                                dcc.Slider(
                                    id="ml_training_runs",
                                    min=10, max=100, step=10, value=30,
                                    marks={10: "10", 30: "30", 50: "50", 100: "100"}
                                ),
                                dbc.Row([
                                    dbc.Col(
                                        dbc.Button("🚀 Train & Save Model", id="btn_train_ml", color="dark", className="w-100 mt-3"),
                                        width=6
                                    ),
                                    dbc.Col(
                                        dbc.Button("📂 Load Saved Model", id="btn_load_ml", color="secondary", className="w-100 mt-3"),
                                        width=6
                                    ),
                                ]),
                                html.Div(id="ml_training_status", className="mt-3")
                            ])
                        ], className="shadow-sm mt-3"),

                        # Live Inference Test Card
                        dbc.Card([
                            dbc.CardHeader(html.H5("🔮 Real-Time Specimen Predictor")),
                            dbc.CardBody([
                                html.Label("Specimen Type:"),
                                dbc.Select(
                                    id="ml_input_type",
                                    options=[
                                        {"label": "Blood Culture", "value": "Blood"},
                                        {"label": "Routine Culture", "value": "Routine"},
                                        {"label": "Urine Culture", "value": "Urine"}
                                    ],
                                    value="Blood"
                                ),
                                html.Label("Arrival Hour (0-23):", className="mt-2"),
                                dbc.Input(id="ml_input_hour", type="number", value=9, min=0, max=23),
                                html.Label("Current Plating Queue Length:", className="mt-2"),
                                dbc.Input(id="ml_input_queue", type="number", value=15, min=0),
                                dbc.Button("Predict TAT Bottleneck", id="btn_predict_ml", color="info", className="w-100 mt-3"),
                                html.Div(id="ml_prediction_output", className="mt-3")
                            ])
                        ], className="shadow-sm mt-3")
                    ], width=4),

                    # Right Column: Visualizations & Metrics
                    dbc.Col([
                        dbc.Row([
                            dbc.Col(dbc.Card([dbc.CardBody([html.H6("Model Accuracy (F1)"), html.H3(id="kpi_ml_accuracy", children="-")])], color="light")),
                            dbc.Col(dbc.Card([dbc.CardBody([html.H6("TAT Error (MAE)"), html.H3(id="kpi_ml_mae", children="-")])], color="light")),
                        ], className="mt-3"),
                        
                        dcc.Graph(id="chart_ml_feature_importance", className="mt-3"),
                        dcc.Graph(id="chart_ml_confusion_matrix", className="mt-3")
                    ], width=8)
                ])
            ])
        ]),

        # GLOBAL STORES
        dcc.Store(id="store_sim_data"),
        dcc.Store(id="store_trained_model"),
    ], fluid=True)