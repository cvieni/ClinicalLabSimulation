# modules/ml_pipeline.py

import numpy as np
import pandas as pd
from typing import Tuple
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.metrics import classification_report, mean_absolute_error

from modules.simulation_d2 import run_simulation

# modules/ml_pipeline.py

import os
import joblib
from typing import Tuple, Dict, Any

MODEL_DIR = "saved_models"
MODEL_PATH = os.path.join(MODEL_DIR, "bottleneck_predictor.joblib")


def save_trained_model(
    clf_model, reg_model, feature_cols: list, metrics: dict
) -> str:
    """Serializes and saves trained models, feature names, and performance metrics to disk."""
    if not os.path.exists(MODEL_DIR):
        os.makedirs(MODEL_DIR)

    payload = {
        "classifier": clf_model,
        "regressor": reg_model,
        "feature_cols": feature_cols,
        "metrics": metrics,
    }

    joblib.dump(payload, MODEL_PATH)
    return MODEL_PATH


def load_trained_model() -> Tuple[Any, Any, list, dict]:
    """Loads a pre-trained model bundle from disk if available."""
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"No saved model found at {MODEL_PATH}")

    payload = joblib.load(MODEL_PATH)
    return (
        payload["classifier"],
        payload["regressor"],
        payload["feature_cols"],
        payload["metrics"],
    )


def is_model_saved() -> bool:
    """Checks if a saved model artifact exists."""
    return os.path.exists(MODEL_PATH)

def generate_training_data_from_sim(
    num_runs: int = 50, sim_days: int = 7
) -> pd.DataFrame:
    """Runs multiple stochastic simulations across parameter ranges to generate

    an ML training dataset of specimen turn-around times (TAT).
    """
    dataset_records = []

    for run_id in range(num_runs):
        seed = 1000 + run_id
        rng = np.random.default_rng(seed)

        # Randomize lab conditions per run to teach the ML model different states
        plating_time = float(rng.uniform(3.0, 8.0))
        inc_hours = float(rng.uniform(8.0, 18.0))

        # Randomize staffing noise
        wd_techs = int(rng.integers(1, 4))
        we_techs = int(rng.integers(1, 3))

        shift_staffing = {
            "Weekday": {
                "Shift_1_Day": {
                    "tech_blood": wd_techs,
                    "tech_routine": wd_techs,
                    "tech_urine": wd_techs,
                    "tech_general": wd_techs,
                    "plating_capacity": wd_techs * 2,
                },
                "Shift_2_Evening": {
                    "tech_blood": wd_techs,
                    "tech_routine": wd_techs,
                    "tech_urine": wd_techs,
                    "tech_general": wd_techs,
                    "plating_capacity": wd_techs * 2,
                },
                "Shift_3_Night": {
                    "tech_blood": 1,
                    "tech_routine": 1,
                    "tech_urine": 1,
                    "tech_general": 1,
                    "plating_capacity": 1,
                },
            },
            "Weekend": {
                "Shift_1_Day": {
                    "tech_blood": we_techs,
                    "tech_routine": we_techs,
                    "tech_urine": we_techs,
                    "tech_general": we_techs,
                    "plating_capacity": we_techs * 2,
                },
                "Shift_2_Evening": {
                    "tech_blood": we_techs,
                    "tech_routine": we_techs,
                    "tech_urine": we_techs,
                    "tech_general": we_techs,
                    "plating_capacity": we_techs * 2,
                },
                "Shift_3_Night": {
                    "tech_blood": 1,
                    "tech_routine": 1,
                    "tech_urine": 1,
                    "tech_general": 1,
                    "plating_capacity": 1,
                },
            },
        }

        # Run DES
        df_pivot, df_state, _, _ = run_simulation(
            sim_days=sim_days,
            seed=seed,
            shift_staffing_profile=shift_staffing,
            time_plating_mean=plating_time,
            time_incubation_hours=inc_hours,
        )

        if df_pivot.empty or "Arrival_Minute" not in df_pivot.columns:
            continue

        # Feature Extraction per specimen
        for _, row in df_pivot.iterrows():
            arrival_min = row.get("Arrival_Minute", 0)

            # Match specimen arrival minute to system state snapshot in df_state
            state_match = df_state[df_state["Minute"] <= arrival_min]
            if state_match.empty:
                continue
            current_state = state_match.iloc[-1]

            # Compute contextual time features
            hour_of_day = int((arrival_min / 60.0) % 24)
            day_of_week = int((arrival_min / (60.0 * 24)) % 7)  # 0=Mon, 5,6=Weekend

            # Build ML Record
            dataset_records.append(
                {
                    # Predictor Features (X)
                    "Specimen_Type": row.get("Type", "Routine"),
                    "Arrival_Hour": hour_of_day,
                    "Is_Weekend": 1 if day_of_week >= 5 else 0,
                    "Active_Queue_Length": current_state.get(
                        "Plating_Queue_Length", 0
                    ),
                    "Active_Lab_Specimens": current_state.get(
                        "Active_Specimens_In_Lab", 0
                    ),
                    "Active_Techs": current_state.get("Active_Techs", 1),
                    "Plating_Time_Param": plating_time,
                    # Targets (y)
                    "Wait_For_Plating_Mins": row.get(
                        "Wait_For_Plating_Mins", 0.0
                    ),
                    "Total_TAT_Hours": row.get("Total_TAT_Hours", np.nan),
                    "Is_TAT_Bottleneck": (
                        1 if row.get("Wait_For_Plating_Mins", 0.0) > 30.0 else 0
                    ),  # Threshold > 30m wait
                }
            )

    df_ml = pd.DataFrame(dataset_records)
    # Clean up incomplete runs
    df_ml = df_ml.dropna(subset=["Total_TAT_Hours"])
    return df_ml


def train_bottleneck_predictor(df_ml: pd.DataFrame):
    """Trains ML models to predict bottleneck likelihood and overall TAT."""
    # Encode categorical columns
    df_encoded = pd.get_dummies(
        df_ml, columns=["Specimen_Type"], drop_first=True
    )

    feature_cols = [
        col
        for col in df_encoded.columns
        if col
        not in [
            "Wait_For_Plating_Mins",
            "Total_TAT_Hours",
            "Is_TAT_Bottleneck",
        ]
    ]

    X = df_encoded[feature_cols]
    y_class = df_encoded["Is_TAT_Bottleneck"]
    y_reg = df_encoded["Total_TAT_Hours"]

    # Split
    X_train, X_test, y_train_clf, y_test_clf = train_test_split(
        X, y_class, test_size=0.2, random_state=42
    )
    _, _, y_train_reg, y_test_reg = train_test_split(
        X, y_reg, test_size=0.2, random_state=42
    )

    # 1. Classification Model: Predict Bottleneck (Yes/No)
    clf = RandomForestClassifier(n_estimators=100, random_state=42)
    clf.fit(X_train, y_train_clf)
    clf_preds = clf.predict(X_test)

    print("=== BOTTLENECK CLASSIFICATION REPORT ===")
    print(classification_report(y_test_clf, clf_preds))

    # 2. Regression Model: Predict Total TAT Hours
    reg = RandomForestRegressor(n_estimators=100, random_state=42)
    reg.fit(X_train, y_train_reg)
    reg_preds = reg.predict(X_test)

    mae = mean_absolute_error(y_test_reg, reg_preds)
    print(f"=== TAT REGRESSION MAE: {mae:.2f} hours ===")

    # Feature Importance Analysis
    importance = pd.Series(clf.feature_importances_, index=feature_cols).sort_values(
        ascending=False
    )
    print("\nTop Factors Driving Bottlenecks:")
    print(importance)

    return clf, reg, feature_cols


if __name__ == "__main__":
    print("Generating synthetic lab state data from DES...")
    df_dataset = generate_training_data_from_sim(num_runs=30, sim_days=7)

    print(f"Dataset generated: {len(df_dataset)} specimens logged.")

    clf_model, reg_model, features = train_bottleneck_predictor(df_dataset)