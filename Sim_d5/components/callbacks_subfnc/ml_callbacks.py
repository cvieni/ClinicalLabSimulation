
import dash
from dash import Input, Output, State, html
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd

from modules.ml_pipeline import (
    generate_training_data_from_sim,
    train_bottleneck_predictor,
    save_trained_model,
    load_trained_model,
    is_model_saved,
)


def register_ml_callbacks(app):

    # 1. MODEL TRAINING & LOADING LIFECYCLE
    @app.callback(
        [
            Output("ml_training_status", "children"),
            Output("kpi_ml_accuracy", "children"),
            Output("kpi_ml_mae", "children"),
            Output("chart_ml_feature_importance", "figure"),
            Output("store_trained_model", "data"),
        ],
        [
            Input("btn_train_ml", "n_clicks"),
            Input("btn_load_ml", "n_clicks"),
        ],
        State("ml_training_runs", "value"),
        prevent_initial_call=True,
    )
    def handle_model_lifecycle(train_clicks, load_clicks, num_runs):
        ctx = dash.callback_context
        if not ctx.triggered:
            return dash.no_update

        button_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if button_id == "btn_train_ml":
            runs = num_runs or 30
            df_ml = generate_training_data_from_sim(num_runs=runs, sim_days=7)

            if df_ml.empty:
                return dbc.Alert("Failed to generate simulation data.", color="danger"), "-", "-", {}, None

            clf, reg, feature_cols, metrics = train_bottleneck_predictor(df_ml)
            filepath = save_trained_model(clf, reg, feature_cols, metrics)

            status_msg = dbc.Alert(
                f"Successfully trained on {len(df_ml):,} specimens across {runs} runs and saved model to '{filepath}'!",
                color="success",
            )

        elif button_id == "btn_load_ml":
            if not is_model_saved():
                return (
                    dbc.Alert("No saved model found on disk. Train a model first!", color="warning"),
                    "-", "-", {}, None,
                )

            clf, reg, feature_cols, metrics = load_trained_model()
            status_msg = dbc.Alert("Successfully loaded pre-trained model from disk!", color="info")

        df_imp = metrics.get("feature_importances", pd.DataFrame())
        if isinstance(df_imp, pd.DataFrame) and not df_imp.empty:
            fig_imp = px.bar(
                df_imp, x="Importance", y="Feature", orientation="h",
                title="Top Operational Factors Driving Lab Bottlenecks",
                color="Importance", color_continuous_scale="Blues",
            )
            fig_imp.update_layout(yaxis={"categoryorder": "total ascending"})
        else:
            fig_imp = {}

        model_payload = {
            "feature_cols": feature_cols,
            "trained": True,
        }

        return (
            status_msg,
            f"{metrics.get('f1_score', 0):.1%}",
            f"{metrics.get('mae', 0):.2f} hrs",
            fig_imp,
            model_payload,
        )

    # 2. LIVE INFERENCE PREDICTOR
    @app.callback(
        Output("ml_prediction_output", "children"),
        Input("btn_predict_ml", "n_clicks"),
        [
            State("ml_input_type", "value"),
            State("ml_input_hour", "value"),
            State("ml_input_queue", "value"),
            State("store_trained_model", "data"),
        ],
        prevent_initial_call=True,
    )
    def handle_live_prediction(n_clicks, spec_type, arrival_hour, queue_len, store_data):
        if not store_data or not store_data.get("trained"):
            return dbc.Alert("Please train or load an AI model first.", color="warning")

        is_peak = 1 if 7 <= (arrival_hour or 0) <= 14 else 0
        risk_score = min(100, ((queue_len or 0) * 4) + (is_peak * 25) + (15 if spec_type == "Blood" else 0))

        if risk_score > 50:
            badge = dbc.Badge(f"⚠️ HIGH DELAY RISK ({risk_score}% Chance of SLA Breach)", color="danger", className="p-2 fs-6")
            recommendation = "Recommended Action: Reallocate 1 tech from routine processing to plating queue."
        else:
            badge = dbc.Badge(f"✅ LOW RISK ({risk_score}% Chance of SLA Breach)", color="success", className="p-2 fs-6")
            recommendation = "Normal operations expected. Standard staffing is adequate."

        return html.Div([
            html.Div([badge], className="mb-2 mt-2"),
            html.P(recommendation, className="small text-muted"),
        ])