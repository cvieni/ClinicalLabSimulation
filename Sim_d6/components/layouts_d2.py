# components/layouts.py
from dash import dcc, html
import dash_bootstrap_components as dbc


from components.layout_subfnc.sim_tab import create_operational_tab
from components.layout_subfnc.monte_carlo_tab import create_monte_carlo_tab
from components.layout_subfnc.ai_predictor_tab import create_ai_predictor_tab

# ===============================================
# Main Layout Assembly
# ===============================================

def get_main_layout():
    """Assembles the primary Dash application layout by assembling sub-components."""
    return dbc.Container([
        html.H2("🧪 Microbiology Lab Operational Simulator & AI Bounding Engine", className="mt-3 mb-3 text-primary"),
        html.P("Simulate lab workflows, identify bottlenecks, and stress-test proposed media ordering policies against stockout risks."),

        dbc.Tabs([
            dcc.Tab(create_operational_tab(), label="Operational Dashboard"),
            dcc.Tab(create_monte_carlo_tab(), label="Monte Carlo Simulations"),
            dcc.Tab(create_ai_predictor_tab(), label="AI Bottleneck Predictor"),
        ]),

        # GLOBAL STORES
        dcc.Store(id="store_sim_data"),
        dcc.Store(id="store_trained_model"),
    ], fluid=True)