import random
import numpy as np
import params_config.params_d3 as p
from params_config.specimen_config_d2 import resolve_specimen_tuning_value
from modules.specimen_priority import get_specimen_priority
from modules.spec_proc_helpers import req_resource
from modules.shift_manager_d2 import get_current_shift_config
from modules.accession_priority import classify_priority, sample_pre_accession_hold
from params_config import event_name as EV
import pandas as pd
import matplotlib.pyplot as plt
import os

DEBUG_BOTTLENECKS = False   # prints one line per specimen: leave off for Monte Carlo


def _sample_accession_touch_time(spec_cfg, is_stat, sim_minutes=None):
    """Return the accessioning touch duration, allowing specimen- and shift-specific overrides."""
    if is_stat:
        # Tier 1: Check active shift matrix or sensitivity sweep overrides
        override_min = resolve_specimen_tuning_value(spec_cfg, "accession_touch_time_min_stat", sim_minutes=sim_minutes)
        override_max = resolve_specimen_tuning_value(spec_cfg, "accession_touch_time_max_stat", sim_minutes=sim_minutes)

        # Tier 2: Check spec_cfg keys explicitly (with stat fallback to routine specimen values)
        if override_min is not None:
            base_min = float(override_min)
        elif "accession_touch_time_min_stat" in spec_cfg:
            base_min = float(spec_cfg["accession_touch_time_min_stat"])
        elif "accession_touch_time_min" in spec_cfg:
            base_min = float(spec_cfg["accession_touch_time_min"])
        else:
            raise KeyError(f"Specimen config for '{spec_cfg.get('type', 'Unknown')}' missing 'accession_touch_time_min'")

        if override_max is not None:
            base_max = float(override_max)
        elif "accession_touch_time_max_stat" in spec_cfg:
            base_max = float(spec_cfg["accession_touch_time_max_stat"])
        elif "accession_touch_time_max" in spec_cfg:
            base_max = float(spec_cfg["accession_touch_time_max"])
        else:
            raise KeyError(f"Specimen config for '{spec_cfg.get('type', 'Unknown')}' missing 'accession_touch_time_max'")
        
        # base_min = p.bld_touch_time_min if override_min is None else float(override_min)
        # base_max = p.bld_touch_time_max if override_max is None else float(override_max)
    else:
        # Tier 1: Check active shift matrix or sensitivity sweep overrides
        override_min = resolve_specimen_tuning_value(spec_cfg, "accession_touch_time_min", sim_minutes=sim_minutes)
        override_max = resolve_specimen_tuning_value(spec_cfg, "accession_touch_time_max", sim_minutes=sim_minutes)

        # Tier 2: Fetch strictly from spec_cfg
        if override_min is not None:
            base_min = float(override_min)
        elif "accession_touch_time_min" in spec_cfg:
            base_min = float(spec_cfg["accession_touch_time_min"])
        else:
            raise KeyError(f"Specimen config for '{spec_cfg.get('type', 'Unknown')}' missing 'accession_touch_time_min'")

        if override_max is not None:
            base_max = float(override_max)
        elif "accession_touch_time_max" in spec_cfg:
            base_max = float(spec_cfg["accession_touch_time_max"])
        else:
            raise KeyError(f"Specimen config for '{spec_cfg.get('type', 'Unknown')}' missing 'accession_touch_time_max'")
        
        # base_min = p.touch_time_min if override_min is None else float(override_min)
        # base_max = p.touch_time_max if override_max is None else float(override_max)

    return float(random.uniform(base_min, base_max))


def _debug_bottleneck(label, **fields):
    if not DEBUG_BOTTLENECKS:
        return
    parts = [f"{k}={v}" for k, v in fields.items()]
    print(f"DEBUG_BOTTLENECK [{label}] {' | '.join(parts)}")

def process_accessioning(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority, arrival_time, 
                        routine_plating_store, accession_incoming_store):

    # ==========================================
    # 1c. CENTRAL PROCESSING & ACCESSIONING
    # ==========================================
    # spec_priority is resolved once per specimen by the caller (it includes the per-specimen STAT draw).
    base_priority, IS_HIGH_PRIORITY_STAT = classify_priority(spec_cfg, rank=spec_priority)
    spec_priority = base_priority          # routine aging is done inside PriorityAccessionStore, from enqueue time
    tracker.log_event(spec_id, spec_type, EV.priority_label(IS_HIGH_PRIORITY_STAT), env.now)
    tracker.log_event(spec_id, spec_type, EV.PRE_ACCESSION_HOLD, env.now)

    # -------------------------------------------------------------
    # Pre-accession hold / sorting delay (NO TECH REQUIRED). See accession_priority.sample_pre_accession_hold
    # for what the JSON histogram represents and the p.accession_hold_mode switch.
    # -------------------------------------------------------------
    hold_multiplier = resolve_specimen_tuning_value(spec_cfg, "pre_accession_hold_multiplier", sim_minutes=env.now)
    pre_accession_hold = sample_pre_accession_hold(
        spec_cfg, IS_HIGH_PRIORITY_STAT, 1.0 if hold_multiplier is None else hold_multiplier)

    if pre_accession_hold > 0:
        yield env.timeout(pre_accession_hold)

    tracker.log_event(spec_id, spec_type, EV.ACCESSION_STORE_WAIT, env.now)

    item = {
            'spec_id': spec_id,
            'spec_type': spec_type,
            'spec_cfg': spec_cfg,
            'priority': spec_priority,
            'is_stat': IS_HIGH_PRIORITY_STAT,
            'arrival_time': arrival_time,
            'done_event': env.event() # Signal when accessioning is complete
        }
    
    yield accession_incoming_store.put(item)

    # Monitor potential deadlocks on the event listener
    wait_start = env.now
    yield item['done_event'] # Block specimen process until batch tech finishes it
    wait_duration = env.now - wait_start
    
    if DEBUG_BOTTLENECKS and wait_duration > 120.0: # Alert if specimen waits > 2 hours for worker
        print(f"⚠️ HIGH LATENCY [{env.now:.1f}m] Specimen {spec_id} waited {wait_duration:.1f}m in store before accession completion!")



    # ==========================================
    # 3. INSTRUMENT DROP-OFF & HANDOFF ROUTING
    # ==========================================
    is_blood = spec_type.upper().startswith("BCX") or spec_cfg.get("is_blood_culture", False)
    is_body_fluid = spec_type.upper().startswith("BODYFLUID") or spec_cfg.get("is_BodyFluid", False)

    if is_blood or is_body_fluid:
        tracker.log_event(spec_id, spec_type, EV.BC_INSTRUMENT_LOAD_PENDING, env.now)
        yield env.timeout(random.uniform(0.1, 0.5))
        tracker.log_event(spec_id, spec_type, EV.BC_INSTRUMENT_LOADED, env.now)
    else:
        # Route standard specimens asynchronously into FIFO plating store
        tracker.log_event(spec_id, spec_type, EV.ROUTINE_PLATING_QUEUED, env.now)
        item = {
            'spec_id': spec_id,
            'spec_type': spec_type,
            'spec_cfg': spec_cfg,
            'priority': spec_priority,
            'accession_completed_at': env.now
        }
        yield routine_plating_store.put(item)



def plating_worker_process(env, resources, routine_plating_store, priority_plating_store, tracker, worker_id = 1):
    """
    Worker process that prioritizes positive blood culture plating store items
    before pulling routine items on a First-In-First-Out (FIFO) basis.
    """
    while True:
        # 1. Check if there are priority positive blood cultures first
        if len(priority_plating_store.items) > 0:
            item = yield priority_plating_store.get()
            is_priority = True
        else:
            # 2. Otherwise, fetch standard routine specimens (FIFO order)
            get_priority = priority_plating_store.get()
            get_routine = routine_plating_store.get()
            
            # Wait for whichever store receives an item first
            results = yield env.any_of([get_priority, get_routine])
            
            if get_priority in results:
                item = results[get_priority]
                is_priority = True
                get_routine.cancel()
            else:
                item = results[get_routine]
                is_priority = False
                get_priority.cancel()

        spec_id = item['spec_id']
        spec_type = item['spec_type']
        spec_cfg = item['spec_cfg']
        spec_priority = item.get('priority', 5)
        done_event = item.get('done_event', None)

        tracker.log_event(spec_id, spec_type, EV.PLATING_TECH_WAIT, env.now)

        # Select tech pool
        candidate_keys = ['tech_plating', 'tech_urine', 'tech_routine']
        valid_pools = [resources[k] for k in candidate_keys if k in resources and resources[k].capacity > 0]

        tech_pool = min(valid_pools, key=lambda r: len(r.queue) / r.capacity) if valid_pools else resources['tech_plating']

        with tech_pool.request(priority=spec_priority) as req:
            yield req
            
            tracker.log_event(spec_id, spec_type, EV.plating_started(is_priority), env.now)
            
            plating_time = spec_cfg.get("plating_touch_time", random.uniform(1.0, 3.0))
            yield env.timeout(plating_time)
            
            tracker.log_event(spec_id, spec_type, EV.plating_done(is_priority), env.now)

        # Unblock waiting main thread (for priority blood cultures)
        if done_event and not done_event.triggered:
            done_event.succeed()




def accession_worker_process(env, resources, accession_incoming_store, routine_plating_store,
                             tracker, batch_size=1, max_wait_time=None, worker_id=1,
                             shift_staffing_profile=None):
    """Dedicated accession technician (worker_id k works while k <= tech_accession of the current shift).

    Changes vs the previous version
    * Takes ONE specimen at a time straight from the PriorityAccessionStore. The old 'batch of 5' was processed
      one touch after another (no time saved) but meant a STAT specimen arriving mid-batch waited behind up to
      four routine ones. `batch_size` / `max_wait_time` are accepted for signature compatibility and ignored.
    * Fixed `get_evt.has_value` (simpy events have no such attribute -> AttributeError whenever the store was
      non-empty after the first get, which killed the worker process silently).
    * A worker blocked on `get()` used to keep working through the end of its shift (the shift check ran only
      once per loop). It now waits on get() OR a 15-minute timeout and re-checks the roster each time.
    """
    RECHECK = 15.0
    while True:
        if shift_staffing_profile is not None:
            cfg = get_current_shift_config(env.now, shift_staffing_profile)
            active_techs = int(cfg.get("tech_accession", 0)) if cfg else 0
            if worker_id > active_techs:
                yield env.timeout(RECHECK)
                continue

        get_evt = accession_incoming_store.get()
        yield get_evt | env.timeout(RECHECK)
        if not get_evt.triggered:
            get_evt.cancel()
            continue                      # re-check the roster, then wait again
        item = get_evt.value

        spec_id, spec_type, spec_cfg = item['spec_id'], item['spec_type'], item['spec_cfg']
        tracker.log_event(spec_id, spec_type, EV.ACCESSION_START, env.now)
        touch_time = _sample_accession_touch_time(spec_cfg, item.get('is_stat', False), env.now)
        _debug_bottleneck(f"AccessionProcess worker={worker_id}", spec_id=spec_id, spec_type=spec_type,
                          is_stat=item.get('is_stat', False), touch_time_min=round(touch_time, 2),
                          backlog=len(accession_incoming_store.items))
        yield env.timeout(touch_time)
        tracker.log_event(spec_id, spec_type, EV.ACCESSION_DONE, env.now)

        done = item.get('done_event')       # seeded (initial-condition) items carry a dummy event
        if done is not None and not done.triggered:
            done.succeed()
        else:
            print(f"CRITICAL [{env.now:.1f}m] Worker-{worker_id}: {spec_id} done_event missing or already triggered")



def save_accession_breakdown_png_plt(tracker_or_df, output_folder, filename):
    """
    Exports a PNG breakdown of accessioned specimens over time by specimen type.
    Dynamically extracts event records from various SpecimenTracker implementations.
    """
    df_events = None

    # 1. Direct DataFrame
    if isinstance(tracker_or_df, pd.DataFrame):
        df_events = tracker_or_df.copy()

    # 2. Objects with methods returning DataFrames or lists
    elif hasattr(tracker_or_df, "get_events_df"):
        df_events = tracker_or_df.get_events_df()
    elif hasattr(tracker_or_df, "get_log"):
        df_events = pd.DataFrame(tracker_or_df.get_log())

    # 3. Common attribute names for lists/dicts inside tracker classes
    elif hasattr(tracker_or_df, "events"):
        df_events = pd.DataFrame(tracker_or_df.events)
    elif hasattr(tracker_or_df, "event_log"):
        df_events = pd.DataFrame(tracker_or_df.event_log)
    elif hasattr(tracker_or_df, "logs"):
        df_events = pd.DataFrame(tracker_or_df.logs)
    elif hasattr(tracker_or_df, "records"):
        df_events = pd.DataFrame(tracker_or_df.records)

    # 4. Fallback: Search attributes of tracker_or_df for list of dicts
    else:
        for attr_name in dir(tracker_or_df):
            if not attr_name.startswith("__"):
                val = getattr(tracker_or_df, attr_name)
                if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                    print(f"[Diagnostic] Found event log in tracker attribute: '{attr_name}'")
                    df_events = pd.DataFrame(val)
                    break

    if df_events is None or df_events.empty:
        print(f"[Warning] Could not parse tracker object. Available attributes on tracker: {[a for a in dir(tracker_or_df) if not a.startswith('_')]}")
        return

    # Normalize column names for flexible matching
    col_map = {c.lower(): c for c in df_events.columns}
    
    # Updated column mapping logic to match your exact DataFrame schema
    event_col = col_map.get("stage", col_map.get("event_name", col_map.get("event")))
    time_col = col_map.get("minute", col_map.get("time", col_map.get("timestamp")))
    type_col = col_map.get("type", col_map.get("specimen_type", col_map.get("spec_type")))

    if not event_col or not time_col or not type_col:
        print(f"[Warning] Required columns missing from event log. Found: {list(df_events.columns)}")
        return

    # Filter for Accession events
    accession_df = df_events[df_events[event_col].astype(str).str.contains("Accession", case=False, na=False)].copy()

    if accession_df.empty:
        print("[Warning] No Accession events found in event log.")
        return

    accession_df["Day"] = pd.to_numeric(accession_df[time_col], errors="coerce") / 1440.0
    accession_df = accession_df.sort_values("Day")

    accession_df["Count"] = 1
    accession_df["Cumulative_Count"] = accession_df.groupby(type_col)["Count"].cumsum()

    # Define high-contrast distinct color map and line styles
    unique_types = sorted(accession_df[type_col].dropna().unique())
    
    # Custom distinct palette mapping
    color_palette = [
        "#E6194B", "#3CB44B", "#FFE119", "#4363D8", "#F58231", 
        "#911EB4", "#46F0F0", "#F032E6", "#BCF60C", "#FABEBE", 
        "#008080", "#E6BEFF", "#9A6324", "#FFFAC8", "#800000"
    ]
    line_styles = ["-", "--", "-."]

    plt.figure(figsize=(13, 7))

    for idx, spec_type in enumerate(unique_types):
        group = accession_df[accession_df[type_col] == spec_type]
        color = color_palette[idx % len(color_palette)]
        style = line_styles[(idx // len(color_palette)) % len(line_styles)]
        
        plt.plot(
            group["Day"], 
            group["Cumulative_Count"], 
            label=spec_type, 
            linewidth=2.2,
            color=color,
            linestyle=style
        )

    plt.title("Cumulative Specimens Accessioned Over Time by Specimen Type", fontsize=14, fontweight="bold")
    plt.xlabel("Simulation Time (Days)", fontsize=12)
    plt.ylabel("Specimens Accessioned", fontsize=12)
    plt.legend(title="Specimen Type", bbox_to_anchor=(1.02, 1), loc="upper left", frameon=True)
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.tight_layout()

    os.makedirs(output_folder, exist_ok=True)
    full_path = os.path.join(output_folder, filename)
    plt.savefig(full_path, dpi=300)
    plt.close()
    print(f"[Diagnostic] High-contrast chart saved successfully to: {full_path}")

