# components/layout_subfnc/results_explorer_tab.py
from dash import dcc, html, dash_table
import dash_bootstrap_components as dbc


def create_results_explorer_tab():
    controls = dbc.Card(dbc.CardBody([
        html.H5("Results Explorer"),
        html.P("Compare finished runs: Monte Carlo tab files (sim_*.csv) and scenario folders (scn_*/ with run_table.csv).", className="small text-muted"),
        html.Label("Folders to scan (one per line)", className="fw-bold"),
        dbc.Textarea(id="rx_roots", rows=3, size="sm", className="mb-2", style={"fontFamily": "monospace", "fontSize": "12px"}),
        dbc.Button("Scan folders", id="rx_scan", color="secondary", size="sm", className="mb-3"),
        html.Label("Results to compare", className="fw-bold"),
        dcc.Dropdown(id="rx_sources", multi=True, placeholder="Scan, then pick one or more", className="mb-2"),
        html.Label("Baseline for the change figures", className="fw-bold"),
        dcc.Dropdown(id="rx_baseline", clearable=False, className="mb-2"),
        dbc.Button("Load / refresh", id="rx_load", color="primary", className="mb-2 w-100"),
        dbc.Checkbox(id="rx_recompute", label="Ignore cache (re-read replication files)", value=False, className="small mb-3"),
        html.Hr(),
        html.Label("TAT statistic", className="fw-bold"),
        dbc.RadioItems(id="rx_metric", options=[{"label": "95th percentile", "value": "p95"}, {"label": "Median", "value": "p50"}], value="p95", inline=True, className="mb-2"),
        html.Label("Change shown as", className="fw-bold"),
        dbc.RadioItems(id="rx_mode", options=[{"label": "% vs baseline", "value": "pct"}, {"label": "hours vs baseline", "value": "abs"}], value="pct", inline=True, className="mb-2"),
        html.Label("Specimen types", className="fw-bold"),
        dcc.Dropdown(id="rx_types", multi=True, placeholder="All types", className="mb-3"),
        dbc.Button("Download comparison CSV", id="rx_dl_btn", color="success", outline=True, size="sm", className="w-100"),
        dcc.Download(id="rx_download"),
    ]), className="mb-3")

    body = dbc.Tabs([
        dbc.Tab(label="Overview", tab_id="rx_t1", children=[
            html.Div(id="rx_status", className="small text-muted my-2"),
            html.Div(id="rx_overview")]),
        dbc.Tab(label="TAT by type", tab_id="rx_t2", children=[dcc.Graph(id="rx_fig_tat", style={"height": "520px"})]),
        dbc.Tab(label="Change vs baseline", tab_id="rx_t3", children=[
            html.P("Mean change across replications with 95% CI. Replications share seeds, so the change is paired (common random numbers). "
                   "Filled markers = the CI excludes zero.", className="small text-muted mt-2"),
            dcc.Graph(id="rx_fig_delta", style={"height": "560px"}),
            html.Div(id="rx_delta_table")]),
        dbc.Tab(label="Distributions", tab_id="rx_t4", children=[
            dbc.Row([dbc.Col([html.Label("Specimen type", className="fw-bold mt-2"), dcc.Dropdown(id="rx_ecdf_type", clearable=False)], md=4)]),
            dcc.Graph(id="rx_fig_ecdf", style={"height": "480px"}),
            html.P("Needs scenario folders (individual TATs). Monte Carlo tab files only keep per-replication percentiles.", className="small text-muted")]),
        dbc.Tab(label="Utilization", tab_id="rx_t5", children=[
            html.P("Mean bench utilization, scenario minus baseline, percentage points (scenario folders with state files).", className="small text-muted mt-2"),
            html.Div(id="rx_util")]),
        dbc.Tab(label="Settings", tab_id="rx_t6", children=[
            html.P("Overrides each result was run with.", className="small text-muted mt-2"), html.Div(id="rx_settings")]),
    ], active_tab="rx_t1")

    return dbc.Container([
        dcc.Interval(id="rx_init", interval=200, max_intervals=1),
        dcc.Store(id="rx_meta"),
        dbc.Row([dbc.Col(controls, md=3), dbc.Col(body, md=9)], className="mt-3"),
    ], fluid=True)
