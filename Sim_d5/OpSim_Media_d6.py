"""Compatibility wrapper for the Dash app.

The front-end remains in the dashboard package so the simulation and CLI workflows remain cleanly separated.
"""

from dashboard.app import app


if __name__ == "__main__":
    app.run(debug=True, port=8050)

