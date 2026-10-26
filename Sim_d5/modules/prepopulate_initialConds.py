import json

from params_config.specimen_config_d2 import SPECIMEN_TYPES


def _coerce_float(value, default=0.0):
    """Convert seeded values to float and guard against malformed input."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _resolve_seed_group(config, *keys):
    """Return the first matching seeded list from a set of supported aliases."""
    for key in keys:
        if key in config and isinstance(config[key], list):
            return config[key]
    return []


def _log_seed_event(tracker, spec_id, spec_type, event_name, sim_time):
    """Shared logging helper for seeded specimens, so all entries follow the same event schema."""
    if tracker is not None:
        tracker.log_event(spec_id, spec_type, event_name, sim_time)


def _seed_queue_item(env, store, tracker, item, active_counter, default_store_name):
    """Add a queued specimen into the correct SimPy store while respecting the original arrival offset."""
    if store is None:
        return

    spec_id = item.get("spec_id") or item.get("specimen_id")
    spec_type = item.get("spec_type") or item.get("type") or "General"
    if spec_id is None:
        return

    arrival_offset = _coerce_float(item.get("arrival_time", 0.0), 0.0)
    priority = int(item.get("priority", item.get("Priority", 1)))
    spec_cfg = item.get("spec_cfg") or SPECIMEN_TYPES.get(spec_type, {})

    def _deliver():
        _log_seed_event(tracker, spec_id, spec_type, "1. Arrived (Initial State)", env.now)
        _log_seed_event(tracker, spec_id, spec_type, f"2B. Queued in {default_store_name} (Seeded)", env.now)
        active_counter["count"] += 1
        store.put({
            "spec_id": spec_id,
            "spec_type": spec_type,
            "spec_cfg": spec_cfg,
            "priority": priority,
            "accession_completed_at": env.now,
        })

    if arrival_offset > 0:
        env.process(_deliver_after_delay(env, arrival_offset, _deliver))
    else:
        _deliver()


def _deliver_after_delay(env, delay_minutes, callback):
    """Helper used to schedule a seeded queue item so it enters the store at the requested time offset."""
    yield env.timeout(delay_minutes)
    callback()


def _seed_incubating_item(env, item, tracker, active_counter, stores):
    """Seed a specimen that is already incubating when the simulation starts."""
    spec_id = item.get("spec_id") or item.get("specimen_id")
    spec_type = item.get("spec_type") or item.get("type") or "General"
    if spec_id is None:
        return

    remaining_time = item.get("remaining_incubation_time", item.get("remaining_time", item.get("incubation_minutes", 0.0)))
    remaining_time = _coerce_float(remaining_time, 0.0)

    active_counter["count"] += 1
    _log_seed_event(tracker, spec_id, spec_type, "1. Arrived (Initial State)", env.now)
    _log_seed_event(tracker, spec_id, spec_type, "3B-2. Incubation Started (Seeded)", env.now)
    env.process(_incubating_handoff_worker(env, spec_id, spec_type, remaining_time, tracker, active_counter, stores))


def load_initial_conditions_from_json(json_path, env, tracker, active_counter, stores):
    """Load seeded queue and incubation items from a JSON file and insert them into the simulation at startup."""
    with open(json_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    if not isinstance(config, dict):
        raise ValueError(f"Initial conditions file did not contain a JSON object: {json_path}")

    routine_store = stores.get("routine_plating_store")
    priority_store = stores.get("priority_plating_store")
    accession_store = stores.get("accession_incoming_store")

    for item in _resolve_seed_group(config, "seed_plating_queue", "seed_routine_plating_queue", "seed_routine_queue"):
        _seed_queue_item(env, routine_store, tracker, item, active_counter, "routine_plating_store")

    for item in _resolve_seed_group(config, "seed_priority_plating_queue", "seed_urgent_plating_queue"):
        _seed_queue_item(env, priority_store, tracker, item, active_counter, "priority_plating_store")

    for item in _resolve_seed_group(config, "seed_accession_queue", "seed_incoming_queue"):
        _seed_queue_item(env, accession_store, tracker, item, active_counter, "accession_incoming_store")

    for item in _resolve_seed_group(config, "seed_incubating_specimens"):
        _seed_incubating_item(env, item, tracker, active_counter, stores)


def _incubating_handoff_worker(env, spec_id, spec_type, remaining_time, tracker, active_counter, stores):
    """Waits for remaining incubation time, then logs completion and triggers downstream review."""
    yield env.timeout(max(0.0, remaining_time))
    _log_seed_event(tracker, spec_id, spec_type, "3B-2. Incubation Completed", env.now)

    if 'review_store' in stores:
        stores['review_store'].put({
            'spec_id': spec_id,
            'spec_type': spec_type,
            'ready_at': env.now,
        })

    active_counter['count'] = max(0, active_counter.get('count', 0) - 1)