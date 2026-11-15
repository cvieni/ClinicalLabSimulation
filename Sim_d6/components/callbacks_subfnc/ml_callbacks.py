import dash
from dash import Input, Output, State, html, dcc
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd

from modules.ml_pipeline import (
    load_model_cached, train_from_cache, forecast_point, recommend_predicted,
)

_ZERO = {"trained": False}


def _scenario(media, start, duration, severity, volume):
    return {"media": media, "start_day": int(start or 20), "duration_days": int(duration or 10),
            "severity": float(severity if severity is not None else 0.8), "volume": float(volume or 1.0)}


def _cv_outputs(bundle, n_points=None):
    cv = pd.DataFrame(bundle["cv"])
    colors = ["#2a78d6" if r else "#eb6834" for r in cv["reliable"]]
    fig = go.Figure(go.Bar(x=cv["cv_r2"], y=cv["target"], orientation="h", marker_color=colors))
    fig.update_layout(title="Cross-validated R² per outcome (orange = below the reliability threshold)", template="plotly_white",
                      xaxis_title="CV R²", yaxis={"autorange": "reversed"}, height=380)
    tbl = cv.round(3)
    return fig, tbl.to_dict("records"), [{"name": c, "id": c} for c in tbl.columns]


def register_ml_callbacks(app):

    # 1. load / train
    @app.callback(
        [Output("ml_training_status", "children"), Output("kpi_ml_n", "children"), Output("kpi_ml_r2", "children"),
         Output("kpi_ml_reliable", "children"), Output("chart_ml_cv", "figure"), Output("table_ml_cv", "data"),
         Output("table_ml_cv", "columns"), Output("store_trained_model", "data"), Output("ml_exclude", "options")],
        [Input("btn_load_ml", "n_clicks"), Input("btn_train_ml", "n_clicks")],
        [State("ml_out_dir", "value"), State("ml_mock", "value")],
        prevent_initial_call=True,
    )
    def handle_model_lifecycle(load_clicks, train_clicks, out_dir, mock):
        trig = dash.callback_context.triggered[0]["prop_id"].split(".")[0]
        out_dir = (out_dir or "ml_out").strip()
        empty = ("-", "-", "-", {}, [], [], _ZERO, [])
        try:
            n_pts = None
            if trig == "btn_train_ml":
                n_pts, _ = train_from_cache(out_dir, mock=bool(mock))
            bundle = load_model_cached(out_dir)
        except Exception as e:
            return (dbc.Alert(f"{type(e).__name__}: {e}", color="danger"), *empty)
        fig, rows, cols = _cv_outputs(bundle)
        cv = pd.DataFrame(bundle["cv"])
        groups = [t[5:] for t in bundle["targets"] if t.startswith("d95__")]
        msg = (f"Trained on {n_pts} simulated points and saved to '{out_dir}'." if n_pts else f"Loaded model from '{out_dir}'.")
        return (dbc.Alert(msg, color="success"), n_pts or "-", f"{cv['cv_r2'].median():.2f}", f"{int(cv['reliable'].sum())} / {len(cv)}",
                fig, rows, cols, {"trained": True, "out_dir": out_dir}, [{"label": g, "value": g} for g in groups])

    # 2. forecast
    @app.callback(
        [Output("chart_ml_forecast", "figure"), Output("table_ml_forecast", "data"), Output("table_ml_forecast", "columns"),
         Output("ml_forecast_text", "children")],
        Input("btn_forecast", "n_clicks"),
        [State("store_trained_model", "data"), State("ml_media", "value"), State("ml_start", "value"), State("ml_duration", "value"),
         State("ml_severity", "value"), State("ml_volume", "value"), State("ml_abort_cap", "value"), State("ml_tol", "value")],
        prevent_initial_call=True,
    )
    def handle_forecast(n, store, media, start, duration, severity, volume, abort_cap, tol):
        if not store or not store.get("trained"):
            return {}, [], [], dbc.Alert("Load or train a model first (section 1).", color="warning")
        bundle = load_model_cached(store["out_dir"])
        sc = _scenario(media, start, duration, severity, volume)
        df, p_exceed = forecast_point(bundle, sc, float(abort_cap if abort_cap is not None else 5))
        g = df[df["target"].str.startswith("d95__")]
        fig = go.Figure(go.Bar(x=[t[5:] for t in g["target"]], y=g["predicted"], error_y=dict(type="data", array=g["sd"]),
                               marker_color=["#2a78d6" if r else "#eb6834" for r in g["reliable"]]))
        fig.add_hline(y=float(tol if tol is not None else 10), line_dash="dash", line_color="red", annotation_text="limit")
        fig.update_layout(template="plotly_white", title="Predicted p95 TAT increase vs no disruption, no response (%, +/- model sd)", yaxis_title="%")
        tbl = df.round(2)
        ab = df.loc[df["target"] == "n_aborted_media", "predicted"]
        txt = dbc.Alert([html.B(f"{media} cut {severity:.0%} for {duration} d: "),
                         f"about {ab.iloc[0]:.0f} specimens aborted for media; chance it exceeds the cap of {abort_cap}: {p_exceed:.0%} (share of trees). ",
                         "Orange bars come from outcomes the model predicts poorly (low CV R²)."], color="danger" if p_exceed > 0.5 else "info")
        return fig, tbl.to_dict("records"), [{"name": c, "id": c} for c in tbl.columns], txt

    # 3. recommend
    @app.callback(
        [Output("table_ml_rec", "data"), Output("table_ml_rec", "columns"), Output("ml_rec_text", "children"), Output("ml_rec_detail", "children")],
        Input("btn_recommend", "n_clicks"),
        [State("store_trained_model", "data"), State("ml_media", "value"), State("ml_start", "value"), State("ml_duration", "value"),
         State("ml_severity", "value"), State("ml_volume", "value"), State("ml_tol", "value"), State("ml_abort_cap", "value"),
         State("ml_margin", "value"), State("ml_exclude", "value")],
        prevent_initial_call=True,
    )
    def handle_recommend(n, store, media, start, duration, severity, volume, tol, abort_cap, margin, exclude):
        if not store or not store.get("trained"):
            return [], [], dbc.Alert("Load or train a model first (section 1).", color="warning"), ""
        bundle = load_model_cached(store["out_dir"])
        sc = _scenario(media, start, duration, severity, volume)
        rec, n_ok, n_all, unreliable = recommend_predicted(
            bundle, sc, tol_pct=float(tol if tol is not None else 10), abort_cap=float(abort_cap if abort_cap is not None else 5),
            margin=float(margin if margin is not None else 1), exclude_groups=tuple(exclude or ()))
        show = rec[["plan", "pred_cost", "pred_aborted", "pred_worst_p95_pct", "feasible_pred"]].round(1)
        notes = [f"{n_ok} of {n_all} candidate responses are predicted to meet the limits (cheapest first)."]
        if not n_ok:
            notes = ["No candidate meets the limits within the lever ranges: showing the options with the fewest predicted aborts. Loosen the limits or the margin."]
        if unreliable:
            notes.append("Low-confidence outcomes used as constraints: " + ", ".join(unreliable) + ".")
        notes.append("These are model predictions. Verify the chosen plan in the simulator before acting:")
        txt = dbc.Alert([*[html.Div(n_) for n_ in notes], html.Pre(_verify_cmd(sc, tol, abort_cap), style={"fontSize": "11px", "marginTop": "6px"})],
                        color="success" if n_ok else "warning")
        data = show.assign(overrides_json=rec["overrides_json"].values).to_dict("records")       # overrides_json is carried but not displayed
        return data, [{"name": c, "id": c} for c in show.columns], txt, ""

    # 4. detail of the selected recommendation: the overrides that reproduce it in the Operational tab
    @app.callback(
        Output("ml_rec_detail", "children", allow_duplicate=True),
        Input("table_ml_rec", "selected_rows"),
        State("table_ml_rec", "data"),
        prevent_initial_call=True,
    )
    def show_detail(selected, data):
        if not selected or not data:
            return dash.no_update
        row = data[selected[0]]
        return html.Div([html.B("Selected: "), row["plan"],
                         html.P("To see this plan in the Operational Dashboard, paste the JSON below into 'Advanced > Extra parameter overrides' "
                                "(Scenario Tweaks), switch nothing else on, and run.", className="small text-muted mt-2 mb-1"),
                         html.Pre(row["overrides_json"], style={"fontSize": "11px", "background": "#f8f9fa", "padding": "6px", "whiteSpace": "pre-wrap"})])


def _verify_cmd(sc, tol, abort_cap):
    return (f"python run_ml_pipeline.py recommend --out-dir ml_out --media {sc['media']} --start-day {sc['start_day']} --duration {sc['duration_days']} "
            f"--severity {sc['severity']} --volume {sc['volume']} --tol-pct {tol} --abort-cap {abort_cap} --verify 4 --verify-reps 5")
