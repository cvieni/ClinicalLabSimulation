import simpy
import random
import numpy as np
import pandas as pd

# Centralized parameters file which has the adjustable variables
import params_config.params_d2 as p


# ==================================================================================
# Tech Breaks Generator
# ==================================================================================
def single_shift_breaks(env, resources, bench_key, tech_id, shift_start_time=0):
    """
    Simulates breaks for 1 technician during a SINGLE 8-hour shift.
    Staggers breaks slightly per tech_id so everyone doesn't eat lunch simultaneously.
    """
    # Stagger breaks by 15 mins per tech so 5 techs take lunch sequentially
    stagger_delay = tech_id * 15

    # Calculate offset if process started slightly after shift start
    time_into_shift = env.now - shift_start_time

    # Shift starts at t=0 relative to cycle
    # --- 1. Random 5-min bathroom break in first 2 hours of shift ---
    break1_min = p.break1_wind_min
    break1_max = p.break1_wind_max

    bathroom_break = random.randint(break1_min, break1_max) + stagger_delay
    delay_1 = max(0, bathroom_break - time_into_shift)
    yield env.timeout(delay_1)
    with resources[bench_key].request(priority=-1) as req:
        yield req
        yield env.timeout(5)

    # --- 2. Scheduled 15-min morning break (~2 hours in) ---
    # Subtract previous delay/duration so this lands at the 2-hour mark
    elapsed = env.now - shift_start_time
    delay_2 = max(0, 120 + stagger_delay - elapsed)
    # time_to_morning_break = max(0, 120 - (bathroom_break + 5))
    yield env.timeout(delay_2)
    with resources[bench_key].request(priority=-1) as req:
        yield req
        yield env.timeout(15)

    # 3. Lunch Break (~4.5 hours in)
    # --- Scheduled 30-min lunch break (~4.5 hours in) ---
    # 270 mins target - 135 mins elapsed = 135 mins wait
    elapsed = env.now - shift_start_time
    delay_3 = max(0, 270 + stagger_delay - elapsed)
    yield env.timeout(delay_3)
    # yield env.timeout(135)  
    with resources[bench_key].request(priority=-1) as req:
        yield req
        yield env.timeout(30)
