# app.py
import dash
import dash_bootstrap_components as dbc
import diskcache
from dash import DiskcacheManager

from components.layouts import get_main_layout
from components.callbacks_d4 import register_callbacks


# Check version history
# python -c "import dash; print(dash.__version__)"

# Create cache directory (for progress bar)
cache = diskcache.Cache("./cache")
background_callback_manager = DiskcacheManager(cache)

# Initialize Dash application
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    background_callback_manager=background_callback_manager
    )

app.title = "Microbiology Lab Simulator"

# Set layout
app.layout = get_main_layout()

# Register callbacks
register_callbacks(app)

if __name__ == "__main__":
    app.run(debug=True, port=8050)