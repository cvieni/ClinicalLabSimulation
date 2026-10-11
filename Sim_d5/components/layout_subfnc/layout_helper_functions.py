#/components/layout_subfnc/layout_helper_function.py

import dash
from dash import dcc, html, dash_table
import dash_bootstrap_components as dbc

import params_config.params_d3 as p

# Import configuration dictionaries
from params_config.staffing_config import SHIFT_STAFFING_PROFILE


from components.GraphingFunctions_d2 import Graphing_SampleQueue

SIM_MAX_TIME = p.sim_max_time

# ===============================================
# Helper Functions & UI Snippets
# ===============================================

def get_default_tech(day_type, shift_key, tech_key, default=1):
    """Looks up values from SHIFT_STAFFING_PROFILE dynamically."""
    shift_map = {
        "shift1": "Shift_1_Day",
        "shift2": "Shift_2_Evening",
        "shift3": "Shift_3_Night"
    }
    config_shift_name = shift_map.get(shift_key, shift_key)
    config_day_name = "Weekday" if day_type == "wd" else "Weekend"

    try:
        return SHIFT_STAFFING_PROFILE[config_day_name][config_shift_name].get(tech_key, default)
    except KeyError:
        return default


def create_shift_inputs(day_type, shift_key, shift_label):
    """Helper to build consistent shift input cards pre-populated with config defaults using Pattern-Matching IDs."""
    val_a = get_default_tech(day_type, shift_key, "tech_accession", default=1)
    val_plt = get_default_tech(day_type, shift_key, "tech_plating", default=1)
    val_b = get_default_tech(day_type, shift_key, "tech_blood", default=1)
    val_r = get_default_tech(day_type, shift_key, "tech_routine", default=1)
    val_s = get_default_tech(day_type, shift_key, "tech_stool", default=1)
    val_u = get_default_tech(day_type, shift_key, "tech_urine", default=1)
    val_n = get_default_tech(day_type, shift_key, "tech_new", default=1)
    val_f = get_default_tech(day_type, shift_key, "tech_float", default=1)
    val_p = get_default_tech(day_type, shift_key, "plating_capacity", default=2)

    def make_id(field_name):
        return {
            "type": "staff-input",
            "day_type": day_type,   # e.g. 'wd' or 'we'
            "shift": shift_key,     # e.g. 'shift1', 'shift2', 'shift3'
            "field": field_name,    # e.g. 'tech_accession'
        }

    return dbc.Card(
        dbc.CardBody([
            html.H6(shift_label, className="card-subtitle mb-2 text-primary"),
            dbc.Row([
                dbc.Col([html.Label("Accessioning Techs", style={"fontSize": "11px"}), dbc.Input(id=make_id("tech_accession"), type="number", value=val_a, min=0, size="sm", debounce=True)], width=3),
                dbc.Col([html.Label("Plating Techs", style={"fontSize": "11px"}), dbc.Input(id=make_id("tech_plating"), type="number", value=val_plt, min=0, size="sm", debounce=True)], width=3),
                dbc.Col([html.Label("Blood Techs", style={"fontSize": "11px"}), dbc.Input(id=make_id("tech_blood"), type="number", value=val_b, min=0, size="sm", debounce=True)], width=3),
                dbc.Col([html.Label("Routine Techs", style={"fontSize": "11px"}), dbc.Input(id=make_id("tech_routine"), type="number", value=val_r, min=0, size="sm", debounce=True)], width=3),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([html.Label("Stool Techs", style={"fontSize": "11px"}), dbc.Input(id=make_id("tech_stool"), type="number", value=val_s, min=0, size="sm", debounce=True)], width=3),
                dbc.Col([html.Label("Urine Techs", style={"fontSize": "11px"}), dbc.Input(id=make_id("tech_urine"), type="number", value=val_u, min=0, size="sm", debounce=True)], width=3),
                dbc.Col([html.Label("News Bench", style={"fontSize": "11px"}), dbc.Input(id=make_id("tech_new"), type="number", value=val_n, min=0, size="sm", debounce=True)], width=3),
                dbc.Col([html.Label("Float Tech", style={"fontSize": "11px"}), dbc.Input(id=make_id("tech_float"), type="number", value=val_f, min=0, size="sm", debounce=True)], width=3),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([html.Label("Plating Capacity", style={"fontSize": "11px"}), dbc.Input(id=make_id("plating_capacity"), type="number", value=val_p, min=1, size="sm", debounce=True)], width=6),
            ])
        ]),
        className="mb-2 shadow-sm"
    )


def create_progress_bar(prefix="sim"):
    """Reusable progress bar container."""
    return html.Div([
        html.H6("Progress Bar", className="fw-bold mb-2") if prefix == "sim" else None,
        dbc.Progress(id=f"{prefix}_progress_bar", value=0, label="0%", striped=True, animated=True, className="mb-1"),
        html.P(id=f"{prefix}_progress_text", className="text-muted small text-center mb-0")
    ], id=f"{prefix}_progress_container", className="mt-3 mb-2" if prefix == "sim" else "my-3")