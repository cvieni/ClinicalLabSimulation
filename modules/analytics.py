# analytics.py
import pandas as pd
import numpy as np


def export_ai_training_dataset(df_raw, df_state, tracker):
    """
    Pivots raw simulation logs into a daily ML feature matrix 
    for training demand forecasters or establishing AI safety-stock constraints.
    """
    if df_raw.empty:
        return pd.DataFrame()

    # 1. Aggregate daily specimen arrival counts by type
    df_raw["Day"] = (df_raw["Minute"] // 1440).astype(int)
    
    daily_arrivals = df_raw[df_raw["Stage"] == "1. Arrived"].groupby(
        ["Day", "Type"]
    ).size().unstack(fill_value=0)
    
    daily_arrivals.columns = [f"arrivals_{col.lower()}" for col in daily_arrivals.columns]

    # 2. Extract media usage per day
    media_logs = []
    for log in tracker.logs:
        if "Media_Used" in log:
            media_logs.append({
                "Day": int(log["Minute"] // 1440),
                "Media": log["Media_Used"],
                "Qty": log.get("Qty", 1)
            })
            
    df_media = pd.DataFrame(media_logs)
    if not df_media.empty:
        daily_media = df_media.groupby(["Day", "Media"])["Qty"].sum().unstack(fill_value=0)
        daily_media.columns = [f"usage_{col.lower()}" for col in daily_media.columns]
    else:
        daily_media = pd.DataFrame()

    # 3. Aggregate daily bottleneck & queue metrics from state logs
    if not df_state.empty:
        daily_queues = df_state.groupby("Day").agg(
            avg_plating_queue=("Plating_Queue_Length", "mean"),
            max_plating_queue=("Plating_Queue_Length", "max"),
            avg_active_specimens=("Active_Specimens_In_Lab", "mean")
        )
    else:
        daily_queues = pd.DataFrame()

    # 4. Merge features into a unified daily dataset
    ml_dataset = daily_arrivals.join(daily_media, how="outer").join(daily_queues, how="outer").fillna(0)
    
    # 5. Add calendar/day-of-week feature (0 = Day 1 / Mon, 5 & 6 = Weekend)
    ml_dataset.reset_index(inplace=True)
    ml_dataset["day_of_week"] = ml_dataset["Day"] % 7
    ml_dataset["is_weekend"] = ml_dataset["day_of_week"].isin([5, 6]).astype(int)

    return ml_dataset
