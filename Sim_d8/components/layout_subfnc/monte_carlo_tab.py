# components/layout_subfnc/monte_carlo_tab.py
from dash import dcc, html, dash_table
import dash_bootstrap_components as dbc

import params_config.params_d3 as p
from params_config.config_d2 import Instrument_resources
from params_config.media_config import MEDIA_CONFIG

from .layout_helper_functions import create_progress_bar, create_shift_inputs
from .scenario_controls import create_scenario_controls

SIM_MAX_TIME = p.sim_max_time


def _media_policy_defaults():
    """Plates available per medium over the run: 'initial' stock (in ordering units) x plates_per_unit. Editable in the tab."""
    if isinstance(MEDIA_CONFIG, dict) and "Proposed Policy" in MEDIA_CONFIG:
        return dict(MEDIA_CONFIG["Proposed Policy"])
    if isinstance(MEDIA_CONFIG, dict):
        return {k: (v.get("initial", 0) * v.get("plates_per_unit", 1) if isinstance(v, dict) else 500) for k, v in MEDIA_CONFIG.items()}
    return {}


def create_mc_sidebar_controls():
    ir = Instrument_resources if isinstance(Instrument_resources, dict) else {}
    return html.Div([
        html.H4("Monte Carlo Settings", className="mb-3"),
        dbc.Accordion([
            dbc.AccordionItem([
                html.Label("Run label (optional, added to the file name)", className="fw-bold"),
                dbc.Input(id="mc_label", type="text", placeholder="e.g. no_biochem", size="sm", className="mb-2"),
                html.Label("Number of replications", className="fw-bold"),
                dcc.Slider(id="mc_iterations", value=10, min=1, max=100, step=1, marks={1: "1", 10: "10", 30: "30", 60: "60", 100: "100"},
                           tooltip={"placement": "bottom"}, className="mb-2"),
                html.Label("Random seed base (replication i uses base + i)", className="fw-bold mt-2"),
                dbc.Input(id="mc_input_seed_base", type="number", value=42, size="sm", className="mb-2"),
                html.Label("Simulation duration (days)", className="fw-bold mt-2"),
                dcc.Slider(id="mc_slider_sim_days", min=1, max=SIM_MAX_TIME, step=1, value=SIM_MAX_TIME,
                           marks={1: "1d", 14: "14d", 30: "30d", 60: "60d"}, tooltip={"placement": "bottom"}),
                html.P(f"Must exceed warm-up + cool-down ({getattr(p, 'warmup_days', 5)} + {getattr(p, 'cooldown_days', 7)} days); 60 is the validated setup "
                       "(about 2 min per replication).", className="small text-muted"),
                html.Label("Parallel workers (blank = automatic)", className="fw-bold"),
                dbc.Input(id="mc_workers", type="number", min=1, step=1, size="sm", className="mb-2"),
            ], title="🎲 Execution Parameters"),
            dbc.AccordionItem([
                html.Label("Blood Culture Capacity"),
                dbc.Input(id="mc_input_bc_capacity", type="number", value=ir.get("bc_instrument", 1500), size="sm", className="mb-2"),
                html.Label("Incubator Capacity"),
                dbc.Input(id="mc_input_incubator_capacity", type="number", value=ir.get("incubator", 10000), size="sm", className="mb-2"),
                html.Label("Phoenix Capacity"),
                dbc.Input(id="mc_input_phoenix_capacity", type="number", value=ir.get("phoenix_instrument", 150), size="sm", className="mb-2"),
                html.Label("Number of MALDI-TOF Instruments"),
                dbc.Input(id="mc_input_maldi_capacity", type="number", value=ir.get("maldi_instrument", 2), size="sm", className="mb-2"),
            ], title="⚙️ Instrument Capacities"),
            dbc.AccordionItem([
                create_shift_inputs("mc_wd", "shift1", "Shift 1: Day (07:00 - 15:00)"),
                create_shift_inputs("mc_wd", "shift2", "Shift 2: Evening (15:00 - 23:00)"),
                create_shift_inputs("mc_wd", "shift3", "Shift 3: Night (23:00 - 07:00)"),
            ], title="👨‍🔬 Weekday Tech Staffing"),
            dbc.AccordionItem([
                create_shift_inputs("mc_we", "shift1", "Shift 1: Day (07:00 - 15:00)"),
                create_shift_inputs("mc_we", "shift2", "Shift 2: Evening (15:00 - 23:00)"),
                create_shift_inputs("mc_we", "shift3", "Shift 3: Night (23:00 - 07:00)"),
            ], title="🏖️ Weekend Tech Staffing"),
            dbc.AccordionItem(create_scenario_controls("mcs"), title="🧪 Scenario Tweaks (what-if)"),
            dbc.AccordionItem([
                html.P("Plates available per medium over the run. Each replication's consumption above this counts as a delay "
                       "(stockout-risk screen on top of the simulated inventory).", className="small text-muted mb-2"),
                html.Div([
                    html.Div([
                        html.Label(f"{media_key} (plates)", className="small font-weight-bold"),
                        dbc.Input(id={"type": "mc_media_policy_input", "index": media_key}, type="number", value=default_val, size="sm", className="mb-2"),
                    ]) for media_key, default_val in _media_policy_defaults().items()
                ]),
            ], title="📦 Media Orders Policy"),
        ], start_collapsed=True, always_open=False),

        dbc.Row([
            dbc.Col(dbc.Button("Run Monte Carlo", id="btn_mc_run", color="success", className="w-100 mt-3 mb-2"), width=8),
            dbc.Col(dbc.Button("Cancel", id="btn_mc_cancel", color="danger", outline=True, className="w-100 mt-3 mb-2"), width=4),
        ]),
        dcc.Upload(id="upload_mc_csv", children=dbc.Button("📁 Upload Results CSV", color="secondary", outline=True, className="w-100"), multiple=False),
        html.Div(id="upload_status_msg", className="small text-info mt-2 font-monospace"),
        html.Div(id="mc_simulation-output-container"),
    ])


def create_mc_kpi_cards():
    def card(title, cid, small=False):
        return dbc.Col(dbc.Card([dbc.CardBody([html.H6(title), html.H3(id=cid, children="-", style={"fontSize": "1.3rem"} if small else {})])], color="light"))
    return dbc.Row([
        card("Stockout Risk Rate", "mc_kpi_risk_rate"), card("Avg Delay Incidents", "mc_kpi_avg_delays"),
        card("Replications", "mc_kpi_iterations"), card("Max Delays Single Run", "mc_kpi_max_delays"),
        card("TAT p50 / p95 (mean)", "mc_kpi_tat", True), card("Aborted / replication", "mc_kpi_aborted"),
    ], className="mb-4")


def create_monte_carlo_tab():
    """Tab 2: run a Monte Carlo study, or reload a saved one, and look at the replications."""
    return dbc.Row([
        dcc.Store(id="store_mc_results"),
        dbc.Col(create_mc_sidebar_controls(), width=3),
        dbc.Col([
            create_progress_bar("mc"),
            html.Div([
                dbc.Row([
                    dbc.Col(dcc.Dropdown(id="dd_past_sim_runs", options=[], value=None, placeholder="Reload a saved run..."), width=10),
                    dbc.Col(dbc.Button("🔄", id="btn_refresh_sim_history", color="secondary", size="sm", className="w-100"), width=2),
                ], className="mb-3"),
            ], id="mc_past_runs_wrapper"),
            html.Div(id="mc_results_container"),
            create_mc_kpi_cards(),
            dcc.Tabs([
                dcc.Tab(label="Delay Incident Distributions", children=[dcc.Graph(id="chart_mc_stockout_dist")]),
                dcc.Tab(label="Consumables Consumption Across Runs", children=[dcc.Graph(id="chart_mc_media_boxplots")]),
                dcc.Tab(label="Specimen TAT Distributions", children=[
                    dbc.RadioItems(id="mc_tat_metric", options=[{"label": "95th percentile", "value": "p95"}, {"label": "Median", "value": "p50"}],
                                   value="p95", inline=True, className="mt-2"),
                    dcc.Graph(id="chart_mc_specimen_tat")]),
                dcc.Tab(label="Parameter Distributions", children=[dcc.Graph(id="chart_mc_params")]),
            ]),
            html.H5("📋 Monte Carlo Iteration Summary Log", className="mt-4"),
            dash_table.DataTable(id="table_mc_summary", page_size=10, style_table={"overflowX": "auto"}, style_cell={"textAlign": "left", "padding": "8px"},
                                 style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"}),
        ], width=9),
    ])
