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


# (field, label) in display order, 4 per row. Keys match SHIFT_STAFFING_PROFILE / the simulator.
STAFF_FIELDS = [
    ("tech_accession", "Accession"), ("tech_float_accession", "Float (acc/plating)"), ("tech_plating", "Plating"), ("tech_blood", "Blood"),
    ("tech_urine", "Urine"), ("tech_stool", "Stool"), ("tech_new", "New-plate"), ("tech_routine", "Routine"),
    ("tech_float_newroutine", "Float (new/routine)"), ("tech_supervisor", "Supervisor"),
]


def create_shift_inputs(day_type, shift_key, shift_label):
    """Shift card with one input per bench, pre-populated from SHIFT_STAFFING_PROFILE (pattern-matching ids)."""
    def make_id(field_name):
        return {"type": "staff-input", "day_type": day_type, "shift": shift_key, "field": field_name}

    def col(field, label):
        return dbc.Col([html.Label(label, style={"fontSize": "11px"}),
                        dbc.Input(id=make_id(field), type="number", value=get_default_tech(day_type, shift_key, field, default=0),
                                  min=0, size="sm", debounce=True)], width=3)

    rows = [dbc.Row([col(f, l) for f, l in STAFF_FIELDS[k:k + 4]], className="mb-2") for k in range(0, len(STAFF_FIELDS), 4)]
    return dbc.Card(dbc.CardBody([html.H6(shift_label, className="card-subtitle mb-2 text-primary"), *rows]), className="mb-2 shadow-sm")


def create_progress_bar(prefix="sim"):
    """Reusable progress bar container."""
    return html.Div([
        html.H6("Progress Bar", className="fw-bold mb-2") if prefix == "sim" else None,
        dbc.Progress(id=f"{prefix}_progress_bar", value=0, label="0%", striped=True, animated=True, className="mb-1"),
        html.P(id=f"{prefix}_progress_text", className="text-muted small text-center mb-0")
    ], id=f"{prefix}_progress_container", className="mt-3 mb-2" if prefix == "sim" else "my-3")