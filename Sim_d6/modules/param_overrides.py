"""Scoped parameter overrides.

Problem this fixes: the old code did setattr(p, ...) / mutated SPECIMEN_TYPES permanently.
ProcessPoolExecutor reuses worker processes, so scenario B silently inherited every key
scenario A set that B did not mention, and the "unknown key" check in run_simulation only
passed because monte_carlo had already setattr'd the key.

Now there is ONE implementation. Overrides are applied for the duration of a run and then
rolled back (params module attributes AND every dict in specimen_config_d2).
"""
import copy
from contextlib import contextmanager

import params_config.params_d3 as p
import params_config.specimen_config_d2 as spec_cfg_module


def _normalise(name: str) -> str:
    return name.replace("-", "_")


def validate_overrides(overrides) -> None:
    """Cheap fail-fast check (used by the parent process before spawning workers)."""
    for raw_name, value in (overrides or {}).items():
        name = _normalise(raw_name)
        if name.startswith("specimen_override_"):
            if not isinstance(value, dict) or not (value.get("specimen_type") and value.get("config_key")):
                raise ValueError(
                    f"'{raw_name}' must be a dict with 'specimen_type', 'config_key', 'value' "
                    f"(optionally 'shift_label'); got {value!r}"
                )
        elif not hasattr(p, name):
            raise ValueError(f"Unknown tuning override '{raw_name}': no such attribute in params_d3")


def _snapshot_spec_config():
    return {
        k: copy.deepcopy(v)
        for k, v in vars(spec_cfg_module).items()
        if isinstance(v, dict) and not k.startswith("__")
    }


def _restore_spec_config(snapshot):
    for k, saved in snapshot.items():
        live = getattr(spec_cfg_module, k)
        live.clear()          # restore in place: other modules hold references to these dicts
        live.update(saved)


@contextmanager
def scoped_overrides(overrides=None):
    if not overrides:
        yield
        return

    validate_overrides(overrides)
    from params_config.specimen_config_d2 import apply_specimen_shift_tuning

    saved_attrs = {}
    saved_cfg = _snapshot_spec_config()
    try:
        for raw_name, value in overrides.items():
            name = _normalise(raw_name)
            if name.startswith("specimen_override_"):
                apply_specimen_shift_tuning(
                    value["specimen_type"],
                    value.get("shift_label", "Day"),
                    value["config_key"],
                    value.get("value"),
                )
            else:
                saved_attrs.setdefault(name, getattr(p, name))
                setattr(p, name, value)
        yield
    finally:
        for name, old in saved_attrs.items():
            setattr(p, name, old)
        _restore_spec_config(saved_cfg)
