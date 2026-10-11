# components/callbacks_subfnc/monte_carlo_callbacks.py
import re
import io
import base64
from datetime import datetime
from pathlib import Path

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import ALL, MATCH, Input, Output, State, ctx, html, no_update

# Import modules
from modules.MonteCarlo.monte_carlo_d2 import run_monte_carlo_simulation
from components.monte_carlo_graphing_fnc import build_delay_incidents_figure, build_consumables_figure, build_parameter_distribution_figures, render_iteration_trend_graph, build_specimen_tat_figure

# Import configuration dictionaries
from params_config.config_d2 import Instrument_resources
from params_config.staffing_config import SHIFT_STAFFING_PROFILE

def generate_timestamped_filepath(output_directory: Path) -> Path:
    """Generates a unique timestamped file path for simulation results."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_directory / f"sim_{timestamp}.csv"


def register_monte_carlo_callbacks(app, output_directory):
    out_dir = Path(output_directory)

    # --------------------------------------------------------------------------
    # Callback 1: Populate Dropdown with Historical Run Files
    # --------------------------------------------------------------------------
    @app.callback(
        Output("dd_past_sim_runs", "options"),
        [
            Input("btn_refresh_sim_history", "n_clicks"),
            Input("btn_mc_run", "n_clicks"),
        ],
    )
    def update_history_dropdown(refresh_clicks, run_clicks):
        sim_files = sorted(
            out_dir.glob("sim_*.csv"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        return [{"label": f.name, "value": str(f)} for f in sim_files]

    # --------------------------------------------------------------------------
    # Callback 2: CSV File Upload Handler
    # --------------------------------------------------------------------------
    @app.callback(
        [
            Output("store_mc_results", "data", allow_duplicate=True),
            Output("upload_status_msg", "children"),
        ],
        Input("upload_mc_csv", "contents"),
        State("upload_mc_csv", "filename"),
        prevent_initial_call=True,
    )
    def handle_csv_upload(contents, filename):
        if contents is None:
            return no_update, no_update

        try:
            content_type, content_string = contents.split(",")
            decoded = base64.b64decode(content_string)
            df_uploaded = pd.read_csv(io.StringIO(decoded.decode("utf-8")))

            records = df_uploaded.to_dict("records")
            status_msg = f"Successfully loaded '{filename}' ({len(df_uploaded)} iterations)."
            return records, status_msg

        except Exception as e:
            return no_update, f"Error loading CSV: {str(e)}"

    # --------------------------------------------------------------------------
    # Callback 3: Handle Active Simulation or Load Historical Run
    # --------------------------------------------------------------------------
    @app.callback(
        [
            Output("mc_results_container", "children"),
            Output("chart_mc_stockout_dist", "figure"),
            Output("chart_mc_media_boxplots", "figure"),
            Output("chart_mc_specimen_tat", "figure"),  # <-- Swapped ID here
            Output("chart_mc_params", "figure"),
            Output("table_mc_summary", "data"),
            Output("table_mc_summary", "columns"),
        ],
        [
            Input("btn_mc_run", "n_clicks"),
            Input("store_mc_results", "data"),
            Input("dd_past_sim_runs", "value"),
        ],
        [
            State({"type": "mc_media_policy_input", "index": ALL}, "value"),
            State({"type": "mc_media_policy_input", "index": ALL}, "id"),
            State("mc_iterations", "value"),
        ],
        background=True,
        progress=[
            Output("mc_progress_bar", "value"),
            Output("mc_progress_bar", "label"),
            Output("mc_progress_text", "children"),
        ],
        progress_default=(0, "0%", "Ready to start simulation..."),
        prevent_initial_call=True,
    )
    def handle_simulation_or_history(
        set_progress,
        run_clicks,
        store_data,
        selected_file_path,
        media_values,
        media_ids,
        mc_iterations,
    ):
        trigger_id = ctx.triggered_id

        # Extracted policy map
        proposed_policy = {
            item_id["index"]: (val if val is not None else 0)
            for item_id, val in zip(media_ids or [], media_values or [])
        }

        df_results = None
        summary_card = html.Div()

        # BRANCH 1: Active Run
        if trigger_id == "btn_mc_run":
            if not run_clicks:
                return (no_update,) * 7

            set_progress((0, "0%", "0% Complete. You have started the sim."))
            csv_output_path = generate_timestamped_filepath(out_dir)

            mc_results = run_monte_carlo_simulation(
                proposed_policy=proposed_policy,
                iterations=mc_iterations,
                instrument_resources=Instrument_resources,
                shift_staffing_profile=SHIFT_STAFFING_PROFILE,
                set_progress=set_progress,
                csv_output_path=csv_output_path,
            )

            df_results = mc_results.get("export_dataframe")
            if df_results is None or df_results.empty:
                alert = dbc.Alert("Monte Carlo run returned no data.", color="warning")
                return alert, {}, {}, {}, {}, [], []

            stockout_rate = mc_results.get("risk_rate", 0.0)
            summary_card = dbc.Card(
                dbc.CardBody(
                    [
                        html.H5(
                            f"Stockout Risk: {stockout_rate:.1f}%",
                            className="text-danger" if stockout_rate > 15 else "text-success",
                        ),
                        html.P(
                            f"Saved run output to: {csv_output_path.name}",
                            className="small text-secondary font-monospace mb-0",
                        ),
                    ]
                ),
                color="light",
                className="mb-3",
            )

        # BRANCH 2: Uploaded Store Data
        elif trigger_id == "store_mc_results":
            if not store_data:
                return (no_update,) * 7

            df_results = pd.DataFrame(store_data)
            summary_card = dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("Loaded Data from Direct Upload", className="text-info"),
                        html.P(
                            f"Iterations loaded: {len(df_results)}",
                            className="small text-secondary font-monospace mb-0",
                        ),
                    ]
                ),
                color="light",
                className="mb-3",
            )

        # BRANCH 3: Historical Dropdown File Select
        elif trigger_id == "dd_past_sim_runs":
            if not selected_file_path or not Path(selected_file_path).exists():
                return (no_update,) * 7

            df_results = pd.read_csv(selected_file_path)
            file_name = Path(selected_file_path).name
            total_runs = len(df_results)
            stockout_runs = (
                (df_results["total_delays"] > 0).sum()
                if "total_delays" in df_results.columns
                else 0
            )
            risk_rate = (stockout_runs / total_runs * 100.0) if total_runs > 0 else 0.0

            summary_card = dbc.Card(
                dbc.CardBody(
                    [
                        html.H5(
                            f"Stockout Risk: {risk_rate:.1f}%",
                            className="text-danger" if risk_rate > 15 else "text-success",
                        ),
                        html.P(
                            f"Loaded Historical Log: {file_name} ({total_runs} runs)",
                            className="small text-primary font-monospace mb-0",
                        ),
                    ]
                ),
                color="light",
                className="mb-3",
            )

        else:
            return (no_update,) * 7

        # Generate figures using modularized functions
        fig_delays = build_delay_incidents_figure(df_results)
        fig_consumables = build_consumables_figure(df_results, proposed_policy)
        fig_tat = build_specimen_tat_figure(df_results)  # <-- Graph function call
        fig_params = build_parameter_distribution_figures(df_results)

        table_columns = [{"name": i, "id": i} for i in df_results.columns]
        table_data = df_results.to_dict("records")

        return (
            summary_card,
            fig_delays,
            fig_consumables,
            fig_tat,
            fig_params,
            table_data,
            table_columns,
        )