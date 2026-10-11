import dash
from dash import dcc, html, dash_table
import dash_bootstrap_components as dbc

import params_config.params_d3 as p

SIM_MAX_TIME = p.sim_max_time

def create_ai_predictor_tab():
    """Builds Content for Tab 3: AI Bottleneck Predictor."""
    return dbc.Row([
        # Left Column: Controls & Inference
        dbc.Col([
            dbc.Card([
                dbc.CardHeader(html.H5("⚙️ Model Training Pipeline")),
                dbc.CardBody([
                    html.P("Generate synthetic training data from DES runs and train Random Forest models to predict TAT bottlenecks.", className="text-muted style-sm"),
                    html.Label("Training Runs (DES Scenarios):"),
                    dcc.Slider(id="ml_training_runs", min=10, max=100, step=10, value=30, marks={10: "10", 30: "30", 50: "50", 100: "100"}),
                    dbc.Row([
                        dbc.Col(dbc.Button("🚀 Train & Save Model", id="btn_train_ml", color="dark", className="w-100 mt-3"), width=6),
                        dbc.Col(dbc.Button("📂 Load Saved Model", id="btn_load_ml", color="secondary", className="w-100 mt-3"), width=6),
                    ]),
                    html.Div(id="ml_training_status", className="mt-3")
                ])
            ], className="shadow-sm mt-3"),

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

        # Right Column: Metrics & Charts
        dbc.Col([
            dbc.Row([
                dbc.Col(dbc.Card([dbc.CardBody([html.H6("Model Accuracy (F1)"), html.H3(id="kpi_ml_accuracy", children="-")])], color="light")),
                dbc.Col(dbc.Card([dbc.CardBody([html.H6("TAT Error (MAE)"), html.H3(id="kpi_ml_mae", children="-")])], color="light")),
            ], className="mt-3"),
            dcc.Graph(id="chart_ml_feature_importance", className="mt-3"),
            dcc.Graph(id="chart_ml_confusion_matrix", className="mt-3")
        ], width=8)
    ])