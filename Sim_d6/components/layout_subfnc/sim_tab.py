from dash import dcc, html, dash_table
import dash_bootstrap_components as dbc

import params_config.params_d3 as p
from params_config.config_d2 import Instrument_resources

# from components.layout_subfnc.layout_helper_functions import create_progress_bar, create_shift_inputs
from .layout_helper_functions import create_progress_bar, create_shift_inputs
from .scenario_controls import create_scenario_controls

SIM_MAX_TIME = p.sim_max_time

def create_sidebar_controls():
    """Builds the accordion control sidebar initialized from config parameters."""
    bc_default = Instrument_resources.get("bc_instrument", 1500) if isinstance(Instrument_resources, dict) else 1500
    inc_default = Instrument_resources.get("incubator", 10000) if isinstance(Instrument_resources, dict) else 10000
    phx_default = Instrument_resources.get("phoenix_instrument", 150) if isinstance(Instrument_resources, dict) else 150
    maldi_default = Instrument_resources.get("maldi_instrument", 2) if isinstance(Instrument_resources, dict) else 2

    return html.Div([
        html.H4("Simulation Settings", className="mb-3"),
        dbc.Accordion([
            dbc.AccordionItem([
                html.Label("Simulation Duration (Days)"),
                dcc.Slider(id="slider_sim_days", min=1, max=SIM_MAX_TIME, step=1, value=7, marks={1: "1d", 7: "7d", 14: "14d", 30: "30d", 60: "60d"}),
                html.Hr(),
                html.Label("Random seed"),
                dbc.Input(id="input_seed", type="number", value=p.seed_input, size="sm", className="mb-2"),
                html.Hr(),
                html.Label("Blood Culture Capacity"),
                dbc.Input(id="input_bc_capacity", type="number", value=bc_default, size="sm", className="mb-2"),
                html.Label("Incubator Capacity"),
                dbc.Input(id="input_incubator_capacity", type="number", value=inc_default, size="sm", className="mb-2"),
                html.Label("Phoenix Capacity"),
                dbc.Input(id="input_phoenix_capacity", type="number", value=phx_default, size="sm", className="mb-2"),
                html.Label("Number of MALDI-TOF Instruments"),
                dbc.Input(id="input_maldi_capacity", type="number", value=maldi_default, size="sm", className="mb-2"),
            ], title="⚙️ General & Instrument Capacities"),

            dbc.AccordionItem([
                create_shift_inputs("wd", "shift1", "Shift 1: Day (07:00 - 15:00)"),
                create_shift_inputs("wd", "shift2", "Shift 2: Evening (15:00 - 23:00)"),
                create_shift_inputs("wd", "shift3", "Shift 3: Night (23:00 - 07:00)"),
            ], title="👨‍🔬 Weekday Tech Staffing"),

            dbc.AccordionItem([
                create_shift_inputs("we", "shift1", "Shift 1: Day (07:00 - 15:00)"),
                create_shift_inputs("we", "shift2", "Shift 2: Evening (15:00 - 23:00)"),
                create_shift_inputs("we", "shift3", "Shift 3: Night (23:00 - 07:00)"),
            ], title="🏖️ Weekend Tech Staffing"),

            dbc.AccordionItem(create_scenario_controls(), title="🧪 Scenario Tweaks (what-if)"),
        ], start_collapsed=True, always_open=False),

        dbc.Button("🚀 Run Simulation", id="btn_run_sim", color="primary", className="w-100 mt-3"),
        html.Div(id="simulation-output-container")
    ])


def create_kpi_cards():
    """Builds top-level KPI summary cards for Tab 1."""
    return dbc.Row([
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("Total Specimens"), html.H3(id="kpi_total", children="-")])], color="light")),
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("TAT p50 / p95"), html.H3(id="kpi_tat", children="-", style={"fontSize": "1.3rem"})])], color="light")),
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("Avg Wait Mins"), html.H3(id="kpi_wait", children="-")])], color="light")),
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("Completion Rate"), html.H3(id="kpi_completion", children="-")])], color="light")),
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("Stockout-delayed"), html.H3(id="kpi_stockouts", children="-")])], color="light")),
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("Aborted (media)"), html.H3(id="kpi_aborted", children="-")])], color="light")),
    ], className="mb-2")


def create_operational_tab():
    """Builds Content for Tab 1: Operational Dashboard."""
    return dbc.Row([
        dbc.Col(create_sidebar_controls(), width=3),
        dbc.Col([
            create_progress_bar("sim"),
            create_kpi_cards(),
            html.Div(id="shortage_stats_box", className="small text-muted mb-3"),
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
                dcc.Tab(label="🚨 Active vs. Backlog", children=[dcc.Graph(id="active-backlog-graph")],),
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