import numpy as np
import pandas as pd

def cult_vol(is_weekend=False):
    """
    Generates realistic daily culture counts centered around your observed averages.
    Uses Poisson distribution to represent natural daily variability.
    """
    if is_weekend:
        # Weekend volumes typically drop ~30-50%
        # Replace with our actual values if this works
        return {
            # Currently all made up numbers
            "BCx": np.random.poisson(lam=45),
            "UCx": np.random.poisson(lam=80),
            "TissCx": np.random.poisson(lam=10),
            "Wound": np.random.poisson(lam=15),
            "Respiratory": np.random.poisson(lam=20),
        }
    else:
        # Weekday averages based on 7/1 to 7/30 ranges
        return {
            "BCx": np.random.poisson(lam=75),   # Range 51-99
            "UCx": np.random.poisson(lam=140),  # Range 40-245
            "TissCx": np.random.poisson(lam=18),  # Range 5-33
            "Wound": np.random.poisson(lam=15), # Currently made up numbers
            "Respiratory": np.random.poisson(lam=15) # Currently made up numbers
        }


def adjust_for_weekend_delivery(arrival_day):
    """
    If arrival_day falls on a weekend, shift delivery to Monday:
    Day % 7 == 5 -> Saturday (add 2 days to get to Monday)
    Day % 7 == 6 -> Sunday   (add 1 day to get to Monday)
    """
    day_of_week = int(arrival_day) % 7
    if day_of_week == 5:      # Saturday
        return arrival_day + 2
    elif day_of_week == 6:    # Sunday
        return arrival_day + 1
    return arrival_day