# modules/validation.py

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp
from typing import Dict, Any

def validate_tat_distributions(
    simulated_tats: np.ndarray, 
    observed_tats: np.ndarray, 
    alpha: float = 0.05
) -> Dict[str, Any]:
    """
    Performs Two-Sample Kolmogorov-Smirnov test and computes distributional error.
    
    STRESS-DES / ISPOR-SMDM Criterion:
    - p-value > alpha (0.05): Fail to reject H0 (Simulated and Observed distributions match).
    - P95 TAT Absolute Relative Error < 10%: High operational accuracy benchmark.
    """
    sim_clean = simulated_tats[~np.isnan(simulated_tats)]
    obs_clean = observed_tats[~np.isnan(observed_tats)]

    # Step 1: compare the empirical distributions directly. The two-sample Kolmogorov-Smirnov TwoSample test asks
    # whether the simulated and observed turnaround time distributions are statistically
    # distinguishable without assuming a specific parametric family.
    ks_stat, p_value = ks_2samp(sim_clean, obs_clean)

    # Step 2: summarize the key operational benchmarks commonly used in lab operations:
    # median, 90th percentile, and 95th percentile turnaround time.
    sim_p50, sim_p90, sim_p95 = np.percentile(sim_clean, [50, 90, 95])
    obs_p50, obs_p90, obs_p95 = np.percentile(obs_clean, [50, 90, 95])

    # Step 3: compute relative error for those summary metrics. This makes it easier to
    # translate the distribution comparison into an operational metric the lab can use.
    err_p50 = abs(sim_p50 - obs_p50) / obs_p50
    err_p95 = abs(sim_p95 - obs_p95) / obs_p95

    return {
        "ks_stat": round(float(ks_stat), 4),
        "p_value": round(float(p_value), 4),
        "is_valid_distribution": bool(p_value > alpha),
        "metrics": {
            "sim_p50": round(sim_p50, 2), "obs_p50": round(obs_p50, 2), "err_p50_pct": round(err_p50 * 100, 2),
            "sim_p90": round(sim_p90, 2), "obs_p90": round(obs_p90, 2),
            "sim_p95": round(sim_p95, 2), "obs_p95": round(obs_p95, 2), "err_p95_pct": round(err_p95 * 100, 2)
        }
    }