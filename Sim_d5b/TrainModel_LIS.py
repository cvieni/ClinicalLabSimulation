import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

# =====================================================
# 1. GENERATE DUMMY LIS DATA (Replace with real LIS CSV)
# =====================================================


def generate_synthetic_lis_data(start_date="2023-01-01", days=730):
  """Generates dummy LIS accession data with day-of-week and seasonal volume trends."""
  dates = pd.date_range(start=start_date, periods=days, freq="D")
  df = pd.DataFrame({"date": dates})

  # Temporal patterns
  dow = df["date"].dt.dayofweek
  month = df["date"].dt.month

  # Base volumes with weekend dropoff and winter spikes
  weekend_mult = np.where(dow >= 5, 0.4, 1.0)
  winter_mult = np.where(month.isin([11, 12, 1, 2]), 1.2, 1.0)

  df["BCx"] = np.random.poisson(lam=45 * weekend_mult * winter_mult)
  df["UCx"] = np.random.poisson(lam=180 * weekend_mult)
  df["TissCx"] = np.random.poisson(lam=25 * weekend_mult)

  return df


# =====================================================
# 2. FEATURE ENGINEERING & FORECASTER CLASS
# =====================================================


class DailyVolumeForecaster:

  def __init__(self, model_dict=None, feature_cols=None):
    self.models = model_dict or {}
    self.feature_cols = feature_cols or []

  def extract_date_features(self, date_obj):
    """Extracts features for a given pd.Timestamp or datetime."""
    dt = pd.to_datetime(date_obj)
    return {
        "day_of_week": dt.dayofweek,
        "is_weekend": int(dt.dayofweek in [5, 6]),
        "month": dt.month,
        "day_of_year": dt.dayofyear,
    }

  def predict_daily_workload(self, current_day, calendar_date):
    feats = pd.DataFrame([self.extract_date_features(calendar_date)])[
        self.feature_cols
    ]
    predictions = {}
    for spec_code, model in self.models.items():
      predictions[spec_code] = float(model.predict(feats)[0])
    return predictions

  def predict_media_demand_horizon(
      self, media, horizon_days, current_date, specimen_cfg, media_types
  ):
    """Calculates cumulative media demand over lead-time horizon based on ML forecasts."""
    total_demand = 0.0
    for h in range(horizon_days):
      future_date = calendar_date + pd.Timedelta(days=h)
      pred_workload = self.predict_daily_workload(h, future_date)

      for spec_code, count in pred_workload.items():
        if spec_code in specimen_cfg:
          req = specimen_cfg[spec_code].get("media_req", {})
          if media in req:
            total_demand += count * req[media]
    return total_demand


# =====================================================
# 3. MODEL TRAINING & SAVING
# =====================================================


def train_and_save_model():
  print("Loading/generating LIS accession data...")
  df = generate_synthetic_lis_data()

  # Engineer features
  df["day_of_week"] = df["date"].dt.dayofweek
  df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
  df["month"] = df["date"].dt.month
  df["day_of_year"] = df["date"].dt.dayofyear

  feature_cols = ["day_of_week", "is_weekend", "month", "day_of_year"]
  specimen_targets = ["BCx", "UCx", "TissCx"]

  # Train-Test Split (80/20 Time Series)
  split_idx = int(len(df) * 0.8)
  train_df, test_df = df.iloc[:split_idx], df.iloc[split_idx:]

  models = {}
  print("\n--- Model Training & Evaluation ---")
  for target in specimen_targets:
    X_train, y_train = train_df[feature_cols], train_df[target]
    X_test, y_test = test_df[feature_cols], test_df[target]

    rf = RandomForestRegressor(n_estimators=100, random_state=42)
    rf.fit(X_train, y_train)

    preds = rf.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    print(f"Specimen '{target}' - Test MAE: {mae:.2f} cultures/day")

    models[target] = rf

  # Save artifact
  forecaster = DailyVolumeForecaster(
      model_dict=models, feature_cols=feature_cols
  )
  joblib.dump(forecaster, "lis_forecaster.pkl")
  print("\nModel pipeline saved successfully to 'lis_forecaster.pkl'.")


if __name__ == "__main__":
  train_and_save_model()