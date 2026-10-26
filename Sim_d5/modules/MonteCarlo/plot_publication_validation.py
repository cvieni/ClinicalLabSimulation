# plot_publication_validation.py

import os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from scipy.stats import ks_2samp

# Set publication style defaults (300 DPI, clean typography, journal-ready dimensions)
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 9,
    "axes.labelsize": 10,
    "axes.titlesize": 10,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "legend.fontsize": 8.5,
    "figure.titlesize": 11,
    "lines.linewidth": 1.5,
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight"
})

def generate_publication_validation_figure(
    df_monthly_obs: pd.DataFrame, 
    df_monthly_sim: pd.DataFrame, 
    pooled_sim_tats: np.ndarray, 
    pooled_obs_tats: np.ndarray,
    output_path: str = "fig_monthly_validation.png"
):
    """
    Generates a 3-panel publication figure evaluating Monte Carlo Digital Twin performance
    against 12 individual monthly timepoints from 2024 LIS data.
    """
    fig = plt.figure(figsize=(10, 7.5), constrained_layout=True)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.2, 1.0])

    ax_trend = fig.add_subplot(gs[0, :])   # Panel A: 12-Month Longitudinal Comparison
    ax_parity = fig.add_subplot(gs[1, 0])  # Panel B: P95 Parity Scatter Plot
    ax_ks = fig.add_subplot(gs[1, 1])      # Panel C: K-S Empirical CDF Overlay

    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", 
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    x = np.arange(1, 13)

    # Colors (Clinical journal palette: Deep Blue, Slate, Coral)
    c_obs_p95 = "#1f77b4"
    c_sim_p95 = "#d62728"
    c_obs_p50 = "#2ca02c"
    c_sim_p50 = "#ff7f0e"

    # =========================================================================
    # PANEL A: 12-MONTH LONGITUDINAL TREND & CONFIDENCE INTERVALS
    # -------------------------------------------------------------------------
    # This panel compares the observed monthly LIS values against the simulated mean
    # and 95% confidence interval. It answers the question: "Does the model track the
    # historical monthly operational performance over time?"
    # =========================================================================
    # Plot Observed Monthly LIS Data
    ax_trend.plot(x, df_monthly_obs["obs_p95"], 'o-', color=c_obs_p95, 
                  label="Observed LIS P95 TAT", markersize=6, linewidth=2)
    ax_trend.plot(x, df_monthly_obs["obs_p50"], 's--', color=c_obs_p50, 
                  label="Observed LIS Median TAT", markersize=5, linewidth=1.5)

    # Plot Simulated Monte Carlo Predictions (Mean + 95% CI Ribbon)
    ax_trend.plot(x, df_monthly_sim["sim_p95_mean"], 'd-', color=c_sim_p95, 
                  label="Simulated P95 TAT (Mean)", markersize=5, linewidth=2)
    ax_trend.fill_between(x, df_monthly_sim["sim_p95_ci_low"], df_monthly_sim["sim_p95_ci_high"], 
                          color=c_sim_p95, alpha=0.18, label="Simulated P95 95% CI")

    ax_trend.plot(x, df_monthly_sim["sim_p50_mean"], '^--', color=c_sim_p50, 
                  label="Simulated Median TAT (Mean)", markersize=5, linewidth=1.5)

    ax_trend.set_xticks(x)
    ax_trend.set_xticklabels(months)
    ax_trend.set_ylabel("Turnaround Time (Hours)")
    ax_trend.set_title("A. Longitudinal Model Performance Across 12 Monthly Operational Timepoints (2024)", 
                       loc="left", fontweight="bold")
    ax_trend.grid(True, linestyle=":", alpha=0.6)
    ax_trend.legend(loc="upper left", frameon=True, facecolor="white", edgecolor="none", framealpha=0.9, ncol=2)
    ax_trend.set_ylim(0, max(df_monthly_obs["obs_p95"].max(), df_monthly_sim["sim_p95_mean"].max()) * 1.2)

    # =========================================================================
    # PANEL B: PARITY PLOT (OBSERVED VS. SIMULATED P95 TAT)
    # -------------------------------------------------------------------------
    # The parity plot checks how tightly the monthly simulated P95 values track the
    # measured LIS values. A tight fit around the y = x line supports a valid model.
    # =========================================================================
    obs_p95 = df_monthly_obs["obs_p95"].values
    sim_p95 = df_monthly_sim["sim_p95_mean"].values

    # Calculate Goodness-of-fit metrics
    mape = np.mean(np.abs((obs_p95 - sim_p95) / obs_p95)) * 100
    r2 = np.corrcoef(obs_p95, sim_p95)[0, 1] ** 2

    ax_parity.scatter(obs_p95, sim_p95, color="#1f77b4", edgecolor="black", s=50, zorder=3)
    
    # Ideal y = x line
    min_val = min(obs_p95.min(), sim_p95.min()) * 0.9
    max_val = max(obs_p95.max(), sim_p95.max()) * 1.1
    ax_parity.plot([min_val, max_val], [min_val, max_val], 'k--', alpha=0.7, label="Ideal Parity (y = x)")

    ax_parity.set_xlabel("Observed 2024 LIS P95 TAT (Hours)")
    ax_parity.set_ylabel("Simulated Digital Twin P95 TAT (Hours)")
    ax_parity.set_title("B. Monthly P95 TAT Parity & Goodness-of-Fit", loc="left", fontweight="bold")
    ax_parity.grid(True, linestyle=":", alpha=0.6)
    ax_parity.legend(loc="upper left", frameon=False)

    # Annotate MAPE and R^2
    fit_text = f"MAPE: {mape:.2f}%\n$R^2$: {r2:.3f}\nTarget MAPE < 10%"
    ax_parity.text(0.95, 0.08, fit_text, transform=ax_parity.transAxes,
                    fontsize=8.5, verticalalignment="bottom", horizontalalignment="right",
                    bbox=dict(boxstyle="round,pad=0.4", facecolor="#f8f9fa", edgecolor="#cccccc", alpha=0.9))

    # =========================================================================
    # PANEL C: TWO-SAMPLE KOLMOGOROV-SMIRNOV ECDF OVERLAY
    # -------------------------------------------------------------------------
    # This panel compares the full empirical distributions rather than only the monthly
    # summary points. The KS test checks whether the observed and simulated TAT
    # distributions differ significantly in shape.
    # =========================================================================
    ks_stat, p_value = ks_2samp(pooled_obs_tats, pooled_sim_tats)

    # Calculate Empirical Cumulative Distribution Functions (ECDF)
    obs_sorted = np.sort(pooled_obs_tats)
    obs_cdf = np.arange(1, len(obs_sorted) + 1) / len(obs_sorted)

    sim_sorted = np.sort(pooled_sim_tats)
    sim_cdf = np.arange(1, len(sim_sorted) + 1) / len(sim_sorted)

    ax_ks.plot(obs_sorted, obs_cdf, color=c_obs_p95, label="Observed LIS (Aggregated)", linewidth=2)
    ax_ks.plot(sim_sorted, sim_cdf, color=c_sim_p95, linestyle="--", label="Simulated Pooled Runs", linewidth=2)

    ax_ks.set_xlabel("Turnaround Time (Hours)")
    ax_ks.set_ylabel("Cumulative Probability")
    ax_ks.set_title("C. Empirical Distribution Comparison (K-S Test)", loc="left", fontweight="bold")
    ax_ks.grid(True, linestyle=":", alpha=0.6)
    ax_ks.legend(loc="lower right", frameon=False)
    ax_ks.set_xlim(0, np.percentile(pooled_obs_tats, 99.5))

    # Annotate K-S Test Result
    ks_text = f"K-S Stat ($D$): {ks_stat:.4f}\n$p$-value: {p_value:.4f}\n{'Valid (p > 0.05)' if p_value > 0.05 else 'Failed (p <= 0.05)'}"
    ax_ks.text(0.05, 0.92, ks_text, transform=ax_ks.transAxes,
               fontsize=8.5, verticalalignment="top", horizontalalignment="left",
               bbox=dict(boxstyle="round,pad=0.4", facecolor="#f8f9fa", edgecolor="#cccccc", alpha=0.9))

    # Save output figure
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    plt.savefig(output_path)
    print(f"[+] Publication-ready figure successfully generated: {os.path.abspath(output_path)}")
    plt.close()


# =============================================================================
# DEMONSTRATION EXECUTABLE WITH SYNTHETIC 12-MONTH DATA
# =============================================================================
if __name__ == "__main__":
    np.random.seed(42)

    # 1. Generate Synthetic Observed 12-Month LIS Summary Data
    months = np.arange(1, 13)
    obs_p50_vals = np.array([18.2, 18.5, 19.1, 18.0, 17.8, 18.4, 20.1, 20.8, 19.2, 18.6, 18.1, 18.9])
    obs_p95_vals = obs_p50_vals * 2.1 + np.random.normal(0, 0.8, 12)

    df_obs_monthly = pd.DataFrame({
        "month": months,
        "obs_p50": obs_p50_vals,
        "obs_p95": obs_p95_vals
    })

    # 2. Generate Synthetic Monte Carlo Monthly Outputs (30 runs per month)
    sim_p50_means = obs_p50_vals + np.random.normal(0, 0.3, 12)
    sim_p95_means = obs_p95_vals + np.random.normal(0, 0.6, 12)

    df_sim_monthly = pd.DataFrame({
        "month": months,
        "sim_p50_mean": sim_p50_means,
        "sim_p95_mean": sim_p95_means,
        "sim_p95_ci_low": sim_p95_means - 1.2,
        "sim_p95_ci_high": sim_p95_means + 1.2
    })

    # 3. Generate Synthetic Pooled TAT Distributions for Kolmogorov-Smirnov Test
    pooled_obs = np.random.lognormal(mean=2.9, sigma=0.45, size=5000)
    pooled_sim = np.random.lognormal(mean=2.91, sigma=0.44, size=5000)

    # Execute Figure Generation
    generate_publication_validation_figure(
        df_monthly_obs=df_obs_monthly,
        df_monthly_sim=df_sim_monthly,
        pooled_sim_tats=pooled_sim,
        pooled_obs_tats=pooled_obs,
        output_path="figures/fig_monthly_validation_2024.png"
    )