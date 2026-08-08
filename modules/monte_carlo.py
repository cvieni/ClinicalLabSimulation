# modules/monte_carlo.py

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from modules.simulation_d2 import run_simulation

from params_config.config import Instrument_resources  # Import default capacities if available

def run_monte_carlo_simulation(
    proposed_policy: Dict[str, int],
    instrument_resources: Dict[str, Any],
    shift_staffing_profile: Dict[str, Any],
    iterations: int = 20,
    time_plating_mean: float = 5.0,
    time_incubation_hours: float = 12.0,
    sim_days: int = 7,
    seed_base: int = 42,
    set_progress=None  # <--- Pass the Dash progress reporter here
) -> Dict[str, Any]:
    """
    Executes a Monte Carlo stress test across multiple stochastic simulation runs
    to evaluate inventory stockout risks and operational delays.

    Parameters:
    -----------
    proposed_policy : Dict[str, int]
        Inventory limits per consumable type (e.g., {"Blood_Agar": 300, ...})
    iterations : int
        Number of stochastic simulation runs to execute.
    time_plating_mean : float
        Mean time in minutes required for plating a specimen.
    time_incubation_hours : float
        Mean incubation duration in hours.
    sim_days : int
        Duration of each simulation run in days.
    seed_base : int
        Base random seed for reproducibility across iterations.

    Returns:
    --------
    Dict[str, Any]
        Aggregated statistics including stockout risk rate, delays per run,
        and raw metric distributions across iterations.
    """

    # Strict validation for explicit configs
    if instrument_resources is None:
            raise ValueError(
                "instrument_resources cannot be None. "
                "Please explicitly pass Instrument_resources from params_config.config."
            )
    if shift_staffing_profile is None:
        raise ValueError(
            "shift_staffing_profile cannot be None. "
            "Please explicitly pass shift_staffing_profile from params_config.config."
        )
    
    # Key validation
    if "incubator" not in instrument_resources:
        raise KeyError("instrument_resources dictionary is missing required key: 'incubator'")
    if "Weekday" not in shift_staffing_profile:
        raise KeyError("shift_staffing_profile dictionary is missing required key: 'Weekday'")



    delays_per_run: List[int] = []
    total_stockout_incidents: int = 0
    
    # Track consumable consumption distributions
    media_consumption_history: Dict[str, List[int]] = {k: [] for k in proposed_policy.keys()}

    for i in range(iterations):
        # Update progress bar if set_progress was passed
        # if set_progress:
        if callable(set_progress):
            current_iter = i + 1
            percent = int((current_iter / iterations) * 100)
            # set_progress((str(percent), f"Running iteration {current_iter} of {iterations}..."))
            set_progress((percent, f"{percent}%", f"Running iteration {current_iter} of {iterations}...", ))

        # Generate a distinct seed per iteration to ensure stochastic variation
        iteration_seed = seed_base + i
        
        # Inject realistic stochastic jitter into plating times and incubation parameters
        rng = np.random.default_rng(iteration_seed)
        jittered_plating_time = max(1.0, float(rng.normal(time_plating_mean, scale=0.5)))
        jittered_incubation_hours = max(1.0, float(rng.normal(time_incubation_hours, scale=1.0)))

        # Execute single simulation run
        df_pivot, df_state, media_usage, _ = run_simulation(
            sim_days=sim_days,
            seed=iteration_seed,
            time_plating_mean=jittered_plating_time,
            time_incubation_hours=jittered_incubation_hours,
            instrument_resources=instrument_resources,
            shift_staffing_profile=shift_staffing_profile
        )

        # 1. Evaluate consumable stockouts against proposed ordering policy
        run_delays = 0
        for item_type, cap in proposed_policy.items():
            consumed = media_usage.get(item_type, 0)
            media_consumption_history[item_type].append(consumed)
            
            if consumed > cap:
                # Deficit represents unhandled/delayed specimens due to stockout
                stockout_deficit = consumed - cap
                run_delays += stockout_deficit

        delays_per_run.append(run_delays)
        if run_delays > 0:
            total_stockout_incidents += 1

    # 2. Compute summary metrics
    risk_rate = (total_stockout_incidents / iterations) * 100.0
    avg_delays = float(np.mean(delays_per_run))

    return {
        "risk_rate": risk_rate,
        "avg_delays": avg_delays,
        "delays_per_run": delays_per_run,
        "media_consumption_history": media_consumption_history,
        "iterations_executed": iterations
    }


def ai_objective_function(proposed_policy: dict) -> float:
    """
    Objective function for AI optimization (e.g., Bayesian Optimization or RL).
    Balances cost minimization against stockout penalty constraints.
    """
    mc_results = run_monte_carlo_simulation(proposed_policy, iterations=50)
    
    unit_costs = {"Blood_Agar": 1.50, "MacConkey": 1.20, "Chocolate_Agar": 1.80}
    inventory_cost = sum(proposed_policy[k] * unit_costs[k] for k in proposed_policy)
    
    # Heavy penalty for exceeding allowable risk thresholds (> 5%)
    stockout_penalty = 0.0
    if mc_results["risk_rate"] > 5.0:
        stockout_penalty = 10000.0 + (mc_results["avg_delays"] * 50.0)
        
    return inventory_cost + stockout_penalty