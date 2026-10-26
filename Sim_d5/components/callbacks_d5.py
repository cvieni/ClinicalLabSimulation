from .callbacks_subfnc.sim_callbacks_d2 import register_sim_callbacks
from .callbacks_subfnc.monte_carlo_callbacks import register_monte_carlo_callbacks
from .callbacks_subfnc.ml_callbacks import register_ml_callbacks


def register_callbacks(app, output_directory, log_output, init_conditions_json):
    """Registers all modularized callbacks onto the Dash app instance."""
    register_sim_callbacks(app, log_output, init_conditions_json)
    register_monte_carlo_callbacks(app, output_directory)
    register_ml_callbacks(app)