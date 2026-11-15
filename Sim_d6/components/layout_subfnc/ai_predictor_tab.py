"""AI tab: media-shortage forecast and response recommender (modules/ml_pipeline.py). The model is trained on Monte Carlo
simulator runs; this tab only loads / trains from runs already on disk, forecasts and recommends. Generating the runs is
a long job: use  python run_ml_pipeline.py gen ...  (command shown below)."""
from dash import dcc, html, dash_table
import dash_bootstrap_components as dbc

from modules.ml_pipeline import VOLUME_GRID, DEFAULT_MEDIA
from params_config.media_config import MEDIA_CONFIG

_S = {"fontSize": "11px"}


def _num(id_, value, **kw):
    return dbc.Input(id=id_, type="number", value=value, size="sm", className="mb-2", **kw)


def create_ai_sidebar():
    media = list(MEDIA_CONFIG) if isinstance(MEDIA_CONFIG, dict) else DEFAULT_MEDIA
    return html.Div([
        html.H4("Shortage AI", className="mb-3"),
        dbc.Accordion([
            dbc.AccordionItem([
                html.Label("Model folder", style=_S),
                dbc.Input(id="ml_out_dir", value="ml_out", size="sm", className="mb-2"),
                dbc.Checkbox(id="ml_mock", label="Data were made with --mock (test only)", value=False, className="mb-2"),
                dbc.Row([
                    dbc.Col(dbc.Button("Load model", id="btn_load_ml", color="info", size="sm", className="w-100"), width=6),
                    dbc.Col(dbc.Button("Train from runs", id="btn_train_ml", color="primary", size="sm", className="w-100"), width=6),
                ], className="mb-2"),
                html.P("Training data come from the simulator and take hours to generate. Run this in a terminal first:", className="small text-muted mb-1"),
                html.Pre("python run_ml_pipeline.py gen --n 200 --reps 2 --out-dir ml_out", style={"fontSize": "10px", "background": "#f8f9fa", "padding": "6px"}),
            ], title="1. Model"),
            dbc.AccordionItem([
                html.Label("Medium disrupted", style=_S),
                dcc.Dropdown(id="ml_media", options=[{"label": m, "value": m} for m in media], value=media[0], clearable=False, className="mb-2"),
                dbc.Row([
                    dbc.Col([html.Label("Start day", style=_S), _num("ml_start", 20, min=15, max=30)], width=4),
                    dbc.Col([html.Label("Duration (d)", style=_S), _num("ml_duration", 10, min=3, max=21)], width=4),
                    dbc.Col([html.Label("Severity", style=_S), _num("ml_severity", 0.8, min=0.3, max=1, step=0.05)], width=4),
                ]),
                html.Label("Volume multiplier", style=_S),
                dcc.Dropdown(id="ml_volume", options=[{"label": f"x{v}", "value": v} for v in VOLUME_GRID], value=1.0, clearable=False, className="mb-2"),
                html.P("Ranges are those the model was trained on.", className="small text-muted"),
            ], title="2. Disruption scenario"),
            dbc.AccordionItem([
                html.Label("Max p95 TAT increase per specimen group (%)", style=_S),
                _num("ml_tol", 10, min=0),
                html.Label("Max specimens aborted for media (per 60-day run)", style=_S),
                _num("ml_abort_cap", 5, min=0),
                html.Label("Safety margin (model sd)", style=_S),
                _num("ml_margin", 1.0, min=0, step=0.25),
                html.Label("Groups left unconstrained (e.g. low volume)", style=_S),
                dcc.Dropdown(id="ml_exclude", options=[], value=[], multi=True, className="mb-2"),
            ], title="3. Limits"),
        ], start_collapsed=False, always_open=True),
        dbc.Row([
            dbc.Col(dbc.Button("Forecast impact", id="btn_forecast", color="warning", className="w-100 mt-3"), width=6),
            dbc.Col(dbc.Button("Recommend response", id="btn_recommend", color="success", className="w-100 mt-3"), width=6),
        ]),
    ])


def create_ai_predictor_tab():
    return dbc.Row([
        dbc.Col(create_ai_sidebar(), width=3),
        dbc.Col([
            html.Div(id="ml_training_status", className="mb-2"),
            dbc.Row([
                dbc.Col(dbc.Card([dbc.CardBody([html.H6("Training points"), html.H3(id="kpi_ml_n", children="-")])], color="light")),
                dbc.Col(dbc.Card([dbc.CardBody([html.H6("Median CV R²"), html.H3(id="kpi_ml_r2", children="-")])], color="light")),
                dbc.Col(dbc.Card([dbc.CardBody([html.H6("Reliable outcomes"), html.H3(id="kpi_ml_reliable", children="-")])], color="light")),
            ], className="mb-3"),
            dcc.Tabs([
                dcc.Tab(label="Forecast (no response)", children=[
                    html.Div(id="ml_forecast_text", className="mt-2"),
                    dcc.Graph(id="chart_ml_forecast"),
                    dash_table.DataTable(id="table_ml_forecast", page_size=12, style_cell={"textAlign": "left", "padding": "6px"},
                                         style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"}),
                ]),
                dcc.Tab(label="Recommended responses", children=[
                    html.Div(id="ml_rec_text", className="mt-2"),
                    dash_table.DataTable(
                        id="table_ml_rec", row_selectable="single", selected_rows=[], page_size=8, style_table={"overflowX": "auto"},
                        style_cell={"textAlign": "left", "padding": "6px", "whiteSpace": "normal", "height": "auto", "maxWidth": "520px"},
                        style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"}),
                    html.Div(id="ml_rec_detail", className="mt-3"),
                ]),
                dcc.Tab(label="Model quality", children=[
                    dcc.Graph(id="chart_ml_cv"),
                    dash_table.DataTable(id="table_ml_cv", page_size=15, style_cell={"textAlign": "left", "padding": "6px"},
                                         style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"}),
                ]),
            ]),
        ], width=9),
    ])
