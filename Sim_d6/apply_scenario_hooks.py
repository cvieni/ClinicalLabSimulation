#!/usr/bin/env python3
"""One-time patch: adds the 2 scenario hooks to your project (idempotent; makes .bak copies).

    python apply_scenario_hooks.py            # run from the project folder (where run_montecarlo_and_plot.py is)

  1. params_config/params_d3.py     + scenario_staffing_json = ""   + stool_biochem_time_multiplier = 1.0
  2. modules/simulation_d4.py       staffing profile copy with the scenario changes applied
  3. modules/specimen_process_d5.py stool biochemical time * stool_biochem_time_multiplier
  4. modules/specimen_generator.py  arrival volume scenarios (global x, per-type x, +N per day)
  5. modules/simulation_d4.py       instrument capacity scenarios
  6. modules/simulation_d4.py       media stock scaling (reorder point / order qty / initial stock, lead time)
Also copy modules/scenario_staffing.py and modules/scenario_volume.py and modules/scenario_media.py next to the others.
"""
import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
ok = True


def patch(rel, edits, append=None, marker=None):
    global ok
    f = root / rel
    if not f.exists():
        print(f"  MISSING {rel}")
        ok = False
        return
    s = f.read_text(encoding="utf-8")
    if marker and marker in s:
        print(f"  already patched: {rel}")
        return
    new = s
    for old, rep in edits:
        if old not in new:
            print(f"  ANCHOR NOT FOUND in {rel}:\n    {old.strip()[:90]}")
            ok = False
            return
        new = new.replace(old, rep, 1)
    if append:
        new = new.rstrip("\n") + "\n" + append
    shutil.copy(f, f.with_suffix(f.suffix + ".bak"))
    f.write_text(new, encoding="utf-8")
    print(f"  patched: {rel}")


patch("params_config/params_d3.py", [], marker="scenario_staffing_json",
      append='\n# --- scenario hooks (set per run through --overrides; see run_scenarios.py) ---\n'
             'scenario_staffing_json = ""          # JSON list of staffing ops, see modules/scenario_staffing.py\n'
             'stool_biochem_time_multiplier = 1.0  # multiplies the rapid-biochemical time for Stool only\n')

patch("modules/simulation_d4.py", [
    ("from params_config.staffing_config import SHIFT_STAFFING_PROFILE\n",
     "from params_config.staffing_config import SHIFT_STAFFING_PROFILE\n"
     "from modules.scenario_staffing import apply_staffing_changes\n"),
    ("    if shift_staffing_profile is None:\n        shift_staffing_profile = SHIFT_STAFFING_PROFILE\n",
     "    if shift_staffing_profile is None:\n        shift_staffing_profile = SHIFT_STAFFING_PROFILE\n"
     "    shift_staffing_profile = apply_staffing_changes(shift_staffing_profile, getattr(p, 'scenario_staffing_json', ''))\n"),
], marker="apply_staffing_changes")

patch("modules/specimen_process_d5.py", [
    ("yield env.timeout(rng.py.uniform(p.min_biochem_screen_time, p.max_biochem_screen_time) * batch_size)",
     "yield env.timeout(rng.py.uniform(p.min_biochem_screen_time, p.max_biochem_screen_time) * batch_size\n"
     "                                  * (getattr(p, 'stool_biochem_time_multiplier', 1.0) if spec_type == 'Stool' else 1.0))"),
], marker="stool_biochem_time_multiplier")

patch("modules/simulation_d4.py", [
    ("from modules.scenario_staffing import apply_staffing_changes\n",
     "from modules.scenario_staffing import apply_staffing_changes\n"
     "from modules.scenario_volume import apply_instrument_changes\n"),
    ("    if instrument_resources is None:\n        instrument_resources = Instrument_resources\n",
     "    if instrument_resources is None:\n        instrument_resources = Instrument_resources\n"
     "    instrument_resources = apply_instrument_changes(instrument_resources, getattr(p, 'scenario_instrument_json', ''))\n"),
], marker="apply_instrument_changes")

patch("modules/specimen_generator.py", [
    ("from modules.specimen_process_d5 import specimen_process\n",
     "from modules.specimen_process_d5 import specimen_process\nimport params_config.params_d3 as p\n"
     "from modules.scenario_volume import apply_volume_scenario\n"),
    ('daily_vol = spec_cfg["daily_volume_mean"]',
     'daily_vol = apply_volume_scenario(spec_type, spec_cfg["daily_volume_mean"], getattr(p, "scenario_volume_json", ""))'),
], marker="apply_volume_scenario")

patch("params_config/params_d3.py", [], marker="scenario_volume_json",
      append='scenario_volume_json = ""           # {"global":1.5,"multipliers":{"BCx":2},"add_per_day":{"BCx":2000}}\n'
             'scenario_instrument_json = ""       # {"bc_instrument": 864}\n')

patch("modules/simulation_d4.py", [
    ("from modules.scenario_staffing import apply_staffing_changes\n",
     "from modules.scenario_staffing import apply_staffing_changes\n"
     "from modules.scenario_media import apply_media_scenario, media_lead_time_days\n"),
    ("    inventory = MediaInventory(env, MEDIA_CONFIG)\n",
     "    _media_json = getattr(p, 'scenario_media_json', '')\n"
     "    inventory = MediaInventory(env, apply_media_scenario(MEDIA_CONFIG, _media_json),\n"
     "                               order_lead_time_days=media_lead_time_days(_media_json))\n"),
    ("inventory_manager_process(env, inventory, MEDIA_CONFIG)", "inventory_manager_process(env, inventory, inventory.media_cfg)"),
], marker="apply_media_scenario")

patch("params_config/params_d3.py", [], marker="scenario_media_json",
      append='scenario_media_json = ""            # {"global":1.5,"per_media":{"Blood_Agar":2},"lead_time_days":3}\n')

print("\nDONE" if ok else "\nSOME PATCHES FAILED - send me the messages above")
