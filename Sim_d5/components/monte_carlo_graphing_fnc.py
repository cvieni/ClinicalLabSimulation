import re
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dash import Input, Output, State, html, no_update, ALL
import dash_bootstrap_components as dbc

# Import modules & params
from modules.MonteCarlo.monte_carlo_d2 import run_monte_carlo_simulation
from params_config.config_d2 import Instrument_resources
from params_config.staffing_config import SHIFT_STAFFING_PROFILE


# ------------------------------------------------------
# --- Figure 1: Delay Incidents per Iteration ---
# ------------------------------------------------------
def build_delay_incidents_figure(df_mc_results):
    """Generates the Delay Incidents per Iteration scatter plot."""
    if df_mc_results is None or df_mc_results.empty:
        fig = go.Figure()
        fig.update_layout(title="Delay Incidents (No Data Loaded)", template="plotly_white")
        return fig

    # Ensure iteration column exists (fallback to index if not)
    if "iteration" not in df_mc_results.columns:
        df_mc_results["iteration"] = df_mc_results.index + 1

    fig_delays = px.scatter(
        df_mc_results,
        x="iteration",
        y="total_delays",
        color="total_delays",
        color_continuous_scale="Reds",
        title="Delay Incidents per Simulation Run",
        labels={"iteration": "Simulation Iteration (#)", "total_delays": "Total Delay Incidents"},
        template="plotly_white",
        hover_data=["seed"] if "seed" in df_mc_results.columns else None,
    )
    fig_delays.update_traces(marker=dict(size=10, opacity=0.8, line=dict(width=1, color="DarkSlateGrey")))
    
    # Add horizontal reference line for mean delays if delays exist
    if "total_delays" in df_mc_results.columns:
        mean_delays = df_mc_results["total_delays"].mean()
        fig_delays.add_hline(
            y=mean_delays,
            line_dash="dash",
            line_color="red",
            annotation_text=f"Mean Delays: {mean_delays:.2f}",
            annotation_position="bottom right"
        )

    return fig_delays


# -------------------------------------------------------------------------
# -------------------------------------------------------------------------
# Fig 2 - consumables
# -------------------------------------------------------------------------
# -------------------------------------------------------------------------
def build_consumables_figure(df_mc_results, proposed_policy):
    """Generates the Consumables Usage vs Order Volume Threshold strip plot."""
    if df_mc_results is None or df_mc_results.empty:
        fig = go.Figure()
        fig.update_layout(title="Consumables Usage (No Data Loaded)", template="plotly_white")
        return fig

    if "iteration" not in df_mc_results.columns:
        df_mc_results["iteration"] = df_mc_results.index + 1

    # Exclude metadata AND capacity columns (cap_*)
    excluded_columns = {
        "iteration", "seed", "total_delays", "stockout_flag", "run_id",
        "total_specimens", "param_BCx_positivity", "param_rejection_percent",
        "plating_delays", "BCX_stockouts",
    }
    media_cols = [
        col for col in df_mc_results.columns 
        if col not in excluded_columns and not col.startswith("cap_") and not col.endswith("_cap")
    ]

    if media_cols:
        df_media_long = df_mc_results.melt(
            id_vars=["iteration"],
            value_vars=media_cols,
            var_name="Media_Type",
            value_name="Units_Consumed"
        )

        # Clean up column names for visual display
        df_media_long["Media_Type_Clean"] = df_media_long["Media_Type"].str.replace("consumed_", "", regex=False)

        fig_consumables = px.strip(
            df_media_long,
            x="Media_Type_Clean",
            y="Units_Consumed",
            color="Media_Type_Clean",
            hover_data=["iteration"],
            title="Consumable Usage vs Order Volume Threshold",
            labels={"Media_Type_Clean": "Media / Consumable Type", "Units_Consumed": "Total Units Consumed"},
            template="plotly_white",
        )
        fig_consumables.update_traces(jitter=0.3, marker=dict(size=8, opacity=0.7))

        # Add Order Volume / Policy threshold markers
        if proposed_policy:
            unique_media = df_media_long["Media_Type_Clean"].unique()
            for media_name in unique_media:
                target_volume = proposed_policy.get(media_name) or proposed_policy.get(f"consumed_{media_name}")
                
                if target_volume is not None:
                    fig_consumables.add_shape(
                        type="line",
                        x0=media_name,
                        x1=media_name,
                        y0=target_volume,
                        y1=target_volume,
                        line=dict(color="Red", width=3, dash="dash"),
                    )

    else:
        fig_consumables = go.Figure()
        fig_consumables.add_annotation(text="No Consumable Data Found", showarrow=False)

    return fig_consumables


# -------------------------------------------------------------------------
# -------------------------------------------------------------------------
# I want some way to also visualize the distribution of the parameters
# -------------------------------------------------------------------------
# -------------------------------------------------------------------------
def build_parameter_distribution_figures(df_results):
    """
    Plots distributions for stochastic input parameters.
    """
    # Identify parameter columns
    param_cols = [c for c in df_results.columns if c.startswith("param_")]
    
    # Fallback list if prefix isn't used
    if not param_cols:
        target_params = ["BCx_positivity", "BdyFluid_positivity", "rejection_percent"]
        param_cols = [c for c in target_params if c in df_results.columns]

    if not param_cols or df_results.empty:
        # Return an empty figure placeholder if no parameter columns are present
        fig = go.Figure()
        fig.update_layout(
            title="No stochastic parameter columns found in results",
            template="plotly_white",
        )
        return fig

    # Create subplots for each parameter
    num_params = len(param_cols)
    fig = make_subplots(
        rows=1, 
        cols=num_params, 
        subplot_titles=[col.replace("param_", "") for col in param_cols]
    )

    for idx, col in enumerate(param_cols, start=1):
        fig.add_trace(
            go.Histogram(
                x=df_results[col], 
                name=col.replace("param_", ""),
                nbinsx=15,
                marker_color="#2b5c8f"
            ),
            row=1, 
            col=idx
        )

    fig.update_layout(
        title_text="Stochastic Parameter Distributions across Iterations",
        showlegend=False,
        template="plotly_white",
        height=350,
        margin=dict(l=40, r=40, t=60, b=40),
    )

    return fig


# -------------------------------------------------------------------------
# -------------------------------------------------------------------------
# Plot trend of delays?
# -------------------------------------------------------------------------
# -------------------------------------------------------------------------
def render_iteration_trend_graph(df_export: pd.DataFrame) -> go.Figure:
    """
    Plots the trend of delays across Monte Carlo iterations.
    """
    fig = go.Figure()

    if df_export is None or df_export.empty:
        fig.update_layout(
            title="Iteration Trend Analysis (No Data)",
            xaxis_title="Run ID",
            yaxis_title="Total Delays"
        )
        return fig

    # Determine X-axis (Run ID or Index)
    x_data = df_export["run_id"] if "run_id" in df_export.columns else df_export.index
    
    # Determine Y-axis column for delays
    delay_col = None
    for candidate in ["total_delays", "delays", "plating_delays"]:
        if candidate in df_export.columns:
            delay_col = candidate
            break

    if delay_col:
        # Total Delays Trend Line
        fig.add_trace(
            go.Scatter(
                x=x_data,
                y=df_export[delay_col],
                mode="lines+markers",
                name="Total Stockout/Run Delays",
                line=dict(color="#d9534f", width=2),
                marker=dict(size=6)
            )
        )

    # Optional: Add Plating Delays if available as a separate trace
    if "plating_delays" in df_export.columns and delay_col != "plating_delays":
        fig.add_trace(
            go.Scatter(
                x=x_data,
                y=df_export["plating_delays"],
                mode="lines+markers",
                name="Plating Delays (>120 min)",
                line=dict(color="#f0ad4e", width=2, dash="dash"),
                marker=dict(size=6)
            )
        )

    fig.update_layout(
        title="Delay Trends Across Iterations",
        xaxis_title="Monte Carlo Iteration / Run ID",
        yaxis_title="Delay Incidents / Unmet Demand",
        hovermode="x unified",
        template="plotly_white"
    )

    return fig


# -------------------------------------------------------------------------
# -------------------------------------------------------------------------
# Plot specimen turn around times
# -------------------------------------------------------------------------
# -------------------------------------------------------------------------
def build_specimen_tat_figure(df_results: pd.DataFrame) -> go.Figure:
    """
    Generates a box plot distribution of Turnaround Times (TAT) per Specimen Type across iterations.
    Reads columns starting with 'tat_' exported by the Monte Carlo simulation engine.
    """
    if df_results is None or df_results.empty:
        fig = go.Figure()
        fig.update_layout(title="No Monte Carlo data available", template="plotly_white")
        return fig

    # Find all columns generated with the 'tat_' prefix
    tat_cols = [c for c in df_results.columns if c.startswith("tat_")]

    if not tat_cols:
        fig = go.Figure()
        fig.update_layout(
            title="No Specimen TAT metrics found in simulation export log.<br><sup>Ensure 'tat_*' columns are recorded in monte_carlo_d2.py</sup>",
            template="plotly_white"
        )
        return fig

    # Melt wide columns into long format for Plotly Express
    df_long = df_results.melt(
        value_vars=tat_cols,
        var_name="Specimen_Type",
        value_name="Mean_TAT_Hours"
    )

    # Clean display labels (e.g., 'tat_Blood_Culture' -> 'Blood Culture')
    df_long["Specimen_Type"] = (
        df_long["Specimen_Type"]
        .str.replace(r"^tat_", "", regex=True)
        .str.replace("_", " ")
        .str.title()
    )

    fig = px.box(
        df_long,
        x="Specimen_Type",
        y="Mean_TAT_Hours",
        color="Specimen_Type",
        points="all",
        title="Mean Specimen Turnaround Time (TAT) Distribution Across Runs",
        labels={
            "Specimen_Type": "Specimen Type",
            "Mean_TAT_Hours": "Mean Turnaround Time (Hours)"
        },
        template="plotly_white"
    )

    fig.update_layout(
        showlegend=False,
        yaxis_title="Mean Turnaround Time (Hours)",
        xaxis_title="Specimen Type",
        margin=dict(l=40, r=40, t=50, b=40)
    )

    return fig