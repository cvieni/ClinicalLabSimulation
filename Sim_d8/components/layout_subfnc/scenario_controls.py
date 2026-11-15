# components/layout_subfnc/scenario_controls.py

"""Scenario tweak controls (Operational tab prefix "sc", Monte Carlo tab prefix "mcs"). Ids must match components/scenario_overrides.scenario_fields(prefix)."""
from dash import dcc, html
import dash_bootstrap_components as dbc

from params_config.media_config import MEDIA_CONFIG

_S = {"fontSize": "11px"}


def _num(id_, value, **kw):
    return dbc.Input(id=id_, type="number", value=value, size="sm", debounce=True, className="mb-2", **kw)


def create_scenario_controls(prefix="sc"):
    media_opts = [{"label": m, "value": m} for m in MEDIA_CONFIG] if isinstance(MEDIA_CONFIG, dict) else []
    return html.Div([
        html.P("Everything here is a what-if applied to this run only. Leave at defaults for the baseline model.", className="small text-muted"),
        html.H6("Workload & supplies", className="text-primary"),
        html.Label("Specimen volume multiplier (x baseline)", style=_S),
        dcc.Slider(id=f"{prefix}_volume_x", min=0.5, max=2.0, step=0.05, value=1.0, marks={0.5: "0.5", 1: "1", 1.5: "1.5", 2: "2"}, tooltip={"placement": "bottom"}),
        html.Label("Media stock / order-size multiplier", style=_S, className="mt-2"),
        dcc.Slider(id=f"{prefix}_media_x", min=0.25, max=3.0, step=0.05, value=1.0, marks={0.25: "0.25", 1: "1", 2: "2", 3: "3"}, tooltip={"placement": "bottom"}),
        html.Label("Resupply lead time (days, blank = model default)", style=_S, className="mt-2"),
        _num(f"{prefix}_lead_days", None, min=0),
        html.Label("Plating time multiplier", style=_S),
        dcc.Slider(id=f"{prefix}_plating_x", min=0.5, max=2.0, step=0.1, value=1.0, marks={0.5: "0.5", 1: "1", 2: "2"}, tooltip={"placement": "bottom"}),
        html.Hr(),
        html.H6("Workflow options", className="text-primary"),
        dbc.Switch(id=f"{prefix}_biochem", label="Bench biochemical tests (spot indole, oxidase, ...)", value=True),
        dbc.Switch(id=f"{prefix}_lit_gram", label="Literature task times for Gram stain (Gerada 2024)", value=False),
        html.Hr(),
        html.H6("Supply disruption", className="text-primary"),
        dbc.Switch(id=f"{prefix}_shortage_on", label="Inject a supply disruption", value=False),
        html.Label("Medium affected", style=_S),
        dcc.Dropdown(id=f"{prefix}_sh_media", options=media_opts, value=(media_opts[0]["value"] if media_opts else None), clearable=False, className="mb-2"),
        dbc.Row([
            dbc.Col([html.Label("Start day", style=_S), _num(f"{prefix}_sh_start", 20, min=1)], width=4),
            dbc.Col([html.Label("Duration (d)", style=_S), _num(f"{prefix}_sh_duration", 10, min=1)], width=4),
            dbc.Col([html.Label("Severity 0-1", style=_S), _num(f"{prefix}_sh_severity", 0.8, min=0, max=1, step=0.05)], width=4),
        ]),
        html.P("Severity = share of each delivery landing in the window that is held back and released late.", className="small text-muted"),
        html.H6("Response to the disruption", className="text-primary"),
        dbc.Switch(id=f"{prefix}_exp_on", label="Expedited emergency orders", value=False),
        dbc.Row([
            dbc.Col([html.Label("Cover < (d)", style=_S), _num(f"{prefix}_exp_trigger", 3, min=0.5)], width=4),
            dbc.Col([html.Label("Lead (d)", style=_S), _num(f"{prefix}_exp_lead", 1, min=0.1)], width=4),
            dbc.Col([html.Label("Qty (d of use)", style=_S), _num(f"{prefix}_exp_qty", 5, min=1)], width=4),
        ]),
        html.Label("Reserve stock for invasive specimen types (days of use, 0 = off)", style=_S),
        dbc.Row([
            dbc.Col(_num(f"{prefix}_res_days", 0, min=0, max=10, step=0.5), width=6),
            dbc.Col([html.Label("when cover < (d)", style=_S), _num(f"{prefix}_res_trigger", 4, min=0.5)], width=6),
        ]),
        dbc.Switch(id=f"{prefix}_spare_on", label="Spare optional media (CNA, Chrome) for listed types", value=False),
        html.Label("...when cover < (d)", style=_S),
        _num(f"{prefix}_spare_trigger", 3, min=0.5),
        html.P("Staffing responses: change the weekday / weekend staffing grids above.", className="small text-muted"),
        html.Hr(),
        html.H6("Advanced", className="text-primary"),
        html.Label("Extra parameter overrides (JSON object)", style=_S),
        dbc.Textarea(id=f"{prefix}_advanced", placeholder='{"batch_size": 8}', size="sm", style={"height": "70px", "fontFamily": "monospace", "fontSize": "11px"}, className="mb-2"),
        html.Label("Overrides that will be applied", style=_S),
        html.Pre(id=f"{prefix}_preview", style={"fontSize": "10px", "maxHeight": "180px", "overflow": "auto", "background": "#f8f9fa", "padding": "6px"}),
    ])
