from dash import dcc, html, dash_table
import dash_bootstrap_components as dbc

# Import simulation parameters
import params_config.params_d3 as p

# Import default dictionary parameters
from params_config.config_d2 import Instrument_resources
from params_config.media_config import MEDIA_CONFIG
from params_config.staffing_config import SHIFT_STAFFING_PROFILE

from .layout_helper_functions import create_progress_bar, create_shift_inputs

SIM_MAX_TIME = p.sim_max_time


def create_mc_sidebar_controls():
    """Builds the accordion sidebar for Monte Carlo settings matching Single-Run style."""
    bc_default = Instrument_resources.get("bc_instrument", 1500) if isinstance(Instrument_resources, dict) else 1500
    inc_default = Instrument_resources.get("incubator", 10000) if isinstance(Instrument_resources, dict) else 10000
    phx_default = Instrument_resources.get("phoenix_instrument", 150) if isinstance(Instrument_resources, dict) else 150
    maldi_default = Instrument_resources.get("maldi_instrument", 2) if isinstance(Instrument_resources, dict) else 2

    # Robust extraction for Proposed Media Policy
    if isinstance(MEDIA_CONFIG, dict) and "Proposed Policy" in MEDIA_CONFIG:
        proposed_policy = MEDIA_CONFIG["Proposed Policy"]
    elif isinstance(MEDIA_CONFIG, dict):
        proposed_policy = {
            k: v.get("initial_stock", 500) if isinstance(v, dict) else 500 
            for k, v in MEDIA_CONFIG.items()
        }
    else:
        proposed_policy = {"BAP": 500, "CHOC": 500, "MAC": 500, "CNA": 500, "CAMPY": 200}

    return html.Div([
        html.H4("Monte Carlo Settings", className="mb-3"),
        
        dbc.Accordion([
            # Section 1: Monte Carlo Specific Parameters
            dbc.AccordionItem([
                html.Label("Number of Iterations (Runs)", className="fw-bold"),
                dcc.Slider(
                    id="mc_iterations", value=10, min=1, max=100, step=1, 
                    marks={1: "1", 25: "25", 50: "50", 75: "75", 100: "100"}, className="mb-2"
                ),
                html.Label("Random Seed Base", className="fw-bold mt-2"),
                dbc.Input(id="mc_input_seed_base", type="number", value=42, size="sm", className="mb-2"),
                
                html.Label("Simulation Duration (Days)", className="fw-bold mt-2"),
                dcc.Slider(
                    id="mc_slider_sim_days", 
                    min=1, max=SIM_MAX_TIME,
                    step=1, value=7, marks={1: "1d", 7: "7d", 14: "14d", 21: "21d", 31: "31d"}
                ),
            ], title="🎲 Execution Parameters"),

            # Section 2: Instrument Capacities
            dbc.AccordionItem([
                html.Label("Blood Culture Capacity"),
                dbc.Input(id="mc_input_bc_capacity", type="number", value=bc_default, size="sm", className="mb-2"),
                
                html.Label("Incubator Capacity"),
                dbc.Input(id="mc_input_incubator_capacity", type="number", value=inc_default, size="sm", className="mb-2"),
                
                html.Label("Phoenix Capacity"),
                dbc.Input(id="mc_input_phoenix_capacity", type="number", value=phx_default, size="sm", className="mb-2"),
                
                html.Label("Number of MALDI-TOF Instruments"),
                dbc.Input(id="mc_input_maldi_capacity", type="number", value=maldi_default, size="sm", className="mb-2"),
            ], title="⚙️ Instrument Capacities"),

            # Section 3: Weekday Staffing Profile
            dbc.AccordionItem([
                create_shift_inputs("mc_wd", "shift1", "Shift 1: Day (07:00 - 15:00)"),
                create_shift_inputs("mc_wd", "shift2", "Shift 2: Evening (15:00 - 23:00)"),
                create_shift_inputs("mc_wd", "shift3", "Shift 3: Night (23:00 - 07:00)"),
            ], title="👨‍🔬 Weekday Tech Staffing"),

            # Section 4: Weekend Staffing Profile
            dbc.AccordionItem([
                create_shift_inputs("mc_we", "shift1", "Shift 1: Day (07:00 - 15:00)"),
                create_shift_inputs("mc_we", "shift2", "Shift 2: Evening (15:00 - 23:00)"),
                create_shift_inputs("mc_we", "shift3", "Shift 3: Night (23:00 - 07:00)"),
            ], title="🏖️ Weekend Tech Staffing"),

            # Section 5: Specific Consumables / Media Orders Policy
            dbc.AccordionItem([
                html.P("Configure stock limits per consumable across iterations:", className="small text-muted mb-2"),
                html.Div([
                    html.Div([
                        html.Label(f"{media_key} Limit", className="small font-weight-bold"),
                        dbc.Input(
                            id={"type": "mc_media_policy_input", "index": media_key},
                            type="number",
                            value=default_val,
                            size="sm",
                            className="mb-2"
                        )
                    ]) for media_key, default_val in proposed_policy.items()
                ])
            ], title="📦 Media Orders Policy"),

        ], start_collapsed=True, always_open=False),

        dbc.Button("Run Monte Carlo Simulation", id="btn_mc_run", color="success", className="w-100 mt-3 mb-2"),
        
        # Fixed File Upload Component Integration
        dcc.Upload(
            id="upload_mc_csv",
            children=dbc.Button("📁 Upload Results CSV", color="secondary", outline=True, className="w-100"),
            multiple=False
        ),
        
        # Target Container for CSV Upload Feedback Messages
        html.Div(id="upload_status_msg", className="small text-info mt-2 font-monospace"),
        html.Div(id="mc_simulation-output-container")
    ])


def create_mc_kpi_cards():
    """Builds top-level summary cards for Monte Carlo Risk & Delays."""
    return dbc.Row([
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("Stockout Risk Rate"), html.H3(id="mc_kpi_risk_rate", children="-")])], color="light")),
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("Avg Delay Incidents"), html.H3(id="mc_kpi_avg_delays", children="-")])], color="light")),
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("Total Iterations Executed"), html.H3(id="mc_kpi_iterations", children="-")])], color="light")),
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("Max Delays Single Run"), html.H3(id="mc_kpi_max_delays", children="-")])], color="light")),
    ], className="mb-4")


def create_monte_carlo_tab():
    """Builds Content for Tab 2: Monte Carlo Risk Dashboard."""
    return dbc.Row([
        dcc.Store(id="store_mc_results"),

        dbc.Col(create_mc_sidebar_controls(), width=3),
        dbc.Col([
            create_progress_bar("mc"),
            
            # Wrapper for past run selection dropdown
            html.Div([
                dbc.Row([
                    dbc.Col(
                        dcc.Dropdown(
                            id="dd_past_sim_runs",
                            options=[],
                            value=None,
                            placeholder="Select past simulation run..."
                        ), 
                        width=10
                    ),
                    dbc.Col(
                        dbc.Button("🔄", id="btn_refresh_sim_history", color="secondary", size="sm", className="w-100"),
                        width=2
                    )
                ], className="mb-3")
            ], id="mc_past_runs_wrapper", style={"display": "none"}),

            create_mc_kpi_cards(),
            
            # Unified dcc.Tab layout across all graphs
            dcc.Tabs([
                dcc.Tab(label="Delay Incident Distributions", children=[dcc.Graph(id="chart_mc_stockout_dist")]),
                dcc.Tab(label="Consumables Consumption Across Runs", children=[dcc.Graph(id="chart_mc_media_boxplots")]),
                # dcc.Tab(label="Iteration Trend Analysis", children=[dcc.Graph(id="chart_mc_delays_trend")]),
                dcc.Tab(label="Specimen TAT Distributions", children=[dcc.Graph(id="chart_mc_specimen_tat")]),
                dcc.Tab(label="Parameter Distributions", children=[dcc.Graph(id="chart_mc_params")]),
            ]),
            
            html.Div(id="mc_results_container"),
            
            html.H5("📋 Monte Carlo Iteration Summary Log", className="mt-4"),
            dash_table.DataTable(
                id="table_mc_summary",
                page_size=10,
                style_table={'overflowX': 'auto'},
                style_cell={'textAlign': 'left', 'padding': '8px'},
                style_header={'backgroundColor': '#f8f9fa', 'fontWeight': 'bold'}
            )
        ], width=9)
    ])