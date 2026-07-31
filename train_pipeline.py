# train_pipeline.py
import time
import numpy as np
import pandas as pd
from collections import defaultdict

# Import existing core simulation engine and config
from modules.simulation_d1 import run_simulation
from modules.config import MEDIA_CONFIG, SPECIMEN_TYPES


def run_monte_carlo_dataset_generation(num_runs=50, sim_days_per_run=14, base_seed=42):
    """
    Runs Monte Carlo simulation sweeps to create a large, unbiased training 
    dataset for ML demand forecasting models (e.g., XGBoost, Random Forest, LSTM).
    
    Captures TRUE demand (including stockout delays and lost capacity) 
    rather than just historical consumption logs.
    """
    print(f"🚀 Launching {num_runs} Monte Carlo simulation runs ({sim_days_per_run} days each)...")
    start_time = time.time()
    
    all_daily_records = []

    for run_idx in range(num_runs):
        seed = base_seed + run_idx
        
        # Randomize workplace variability slightly across runs to introduce real-world noise
        plating_cap = np.random.choice([3, 4, 5], p=[0.2, 0.6, 0.2])
        tech_cap = np.random.choice([3, 4, 5], p=[0.2, 0.6, 0.2])
        
        # Run simulation engine
        df_pivot, df_state, media_usage, df_ai_features = run_simulation(
            sim_days=sim_days_per_run,
            seed=seed,
            cap_plating=plating_cap,
            cap_techs=tech_cap,
            cap_incubators=200,
            time_plating_mean=12,
            time_incubation_hours=24
        )
        
        if df_pivot.empty:
            continue
            
        # Parse event logs to compute daily True Demand vs Actual Usage vs Stockouts
        df_pivot["Day"] = (df_pivot["1. Arrived"] // 1440).astype(int)
        
        for day, group in df_pivot.groupby("Day"):
            record = {
                "Run_ID": run_idx,
                "Simulation_Seed": seed,
                "Day": day,
                "Day_Of_Week": day % 7,
                "Is_Weekend": 1 if (day % 7) in [5, 6] else 0,
                "Plating_Bench_Capacity": plating_cap,
                "Tech_Capacity": tech_cap,
            }
            
            # 1. Specimen Arrival Counts (True Clinical Demand)
            for spec_type in SPECIMEN_TYPES.keys():
                spec_group = group[group["Type"] == spec_type]
                record[f"Arrivals_{spec_type}"] = len(spec_group)
                
                # Turnaround Time (TAT) metrics
                if "Total_TAT_Hours" in spec_group.columns:
                    completed = spec_group["Total_TAT_Hours"].dropna()
                    record[f"Avg_TAT_Hours_{spec_type}"] = completed.mean() if not completed.empty else np.nan
            
            # 2. Extract Stockout Delay Incidents
            if "Stockout Delay Started" in group.columns:
                record["Stockout_Incidents"] = group["Stockout Delay Started"].notna().sum()
            else:
                record["Stockout_Incidents"] = 0
                
            all_daily_records.append(record)

    df_dataset = pd.DataFrame(all_daily_records)
    
    # Feature Engineering: Add Lag Features (Previous Day's Volume)
    for spec_type in SPECIMEN_TYPES.keys():
        col = f"Arrivals_{spec_type}"
        df_dataset[f"{col}_Lag1"] = df_dataset.groupby("Run_ID")[col].shift(1)
        df_dataset[f"{col}_7Day_Mean"] = df_dataset.groupby("Run_ID")[col].transform(lambda x: x.rolling(7, min_periods=1).mean())

    elapsed = time.time() - start_time
    print(f"✅ Generated {len(df_dataset)} daily training records across {num_runs} iterations in {elapsed:.2f} seconds.")
    
    return df_dataset


def stress_test_ai_order_policy(ai_order_policy, iterations=30, sim_days=7):
    """
    STRESS TEST / GUARDRAIL ENGINE:
    Takes an AI model's predicted media order schedule and runs it through 
    Monte Carlo conditions to verify if it causes stockout delays.
    
    :param ai_order_policy: Dict of {media_name: order_quantity} proposed by AI model.
    :return: Stockout probability risk assessment score.
    """
    print("\n🛡️ Running Monte Carlo Bounding Guardrail on Proposed AI Policy...")
    print(f"Proposed Order Quantities: {ai_order_policy}")
    
    stockout_failures = 0
    total_delayed_specimens = 0

    for i in range(iterations):
        # Override initial media inventory config with AI proposed policy
        test_media_cfg = MEDIA_CONFIG.copy()
        for media, qty in ai_order_policy.items():
            if media in test_media_cfg:
                test_media_cfg[media]["order_qty"] = qty
        
        # Run simulation under stochastic stress conditions
        df_pivot, df_state, _, _ = run_simulation(
            sim_days=sim_days,
            seed=1000 + i,
            cap_plating=3,  # Constrained staff
            cap_techs=2,
            cap_incubators=150,
            time_plating_mean=14,
            time_incubation_hours=24
        )

        if "Stockout Delay Started" in df_pivot.columns:
            delays = df_pivot["Stockout Delay Started"].notna().sum()
            if delays > 0:
                stockout_failures += 1
                total_delayed_specimens += delays

    stockout_risk_rate = (stockout_failures / iterations) * 100
    print(f"📊 Policy Stress Test Results:")
    print(f"  - Stockout Risk Rate: {stockout_risk_rate:.1f}% of simulation runs experienced stockouts.")
    print(f"  - Avg Delayed Specimens per Failure: {total_delayed_specimens / max(1, stockout_failures):.1f}")
    
    # Boundary Decision Rule
    SAFETY_THRESHOLD_PERCENT = 5.0
    if stockout_risk_rate > SAFETY_THRESHOLD_PERCENT:
        print("❌ REJECT POLICY: Proposed AI order volume violates safety threshold (>5% stockout risk). Enforcing fallback buffer (+15%).")
        bounded_policy = {k: int(v * 1.15) for k, v in ai_order_policy.items()}
        return bounded_policy, False
    else:
        print("✅ PASSED: Proposed AI policy is physically sound and bounded.")
        return ai_order_policy, True


if __name__ == "__main__":
    # --- STEP 1: Generate Monte Carlo Training Dataset ---
    df_training = run_monte_carlo_dataset_generation(num_runs=20, sim_days_per_run=14)
    
    # Export for XGBoost / Machine Learning pipeline
    output_filename = "synthetic_lab_training_data.csv"
    df_training.to_csv(output_filename, index=False)
    print(f"📁 Training dataset exported to: '{output_filename}'")
    
    # --- STEP 2: Example AI Policy Bounding Test ---
    # Imagine an un-constrained AI predicted these order quantities for next week:
    naive_ai_predictions = {
        "Blood_Agar": 200,      # Under-predicted relative to surge risks
        "MacConkey": 100,
        "Chocolate_Agar": 80
    }
    
    # Test and bound the AI policy
    final_policy, is_safe = stress_test_ai_order_policy(naive_ai_predictions, iterations=20)
    print(f"\nFinal Approved Order Policy: {final_policy}")