#!/usr/bin/env python3
"""v3 patch (idempotent, keeps the first .bak).  Run from the project root AFTER apply_biochem_hooks.py:  python apply_v3_hooks.py
Copy modules/literature_times.py and the updated params_config/biochem_config.py into your project first."""
import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
ok = True


def _find(rel):
    for c in (root / rel, root / Path(rel).name, root / "modules" / Path(rel).name, root / "params_config" / Path(rel).name):
        if c.exists():
            return c
    return root / rel


def patch(rel, edits, append=None, marker=None):
    global ok
    f = _find(rel)
    if not f.exists():
        print(f"  MISSING {rel}"); ok = False; return
    raw = f.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw                      # keep Windows line endings so diffs stay small
    s = raw.replace("\r\n", "\n")
    if marker in s:
        print(f"  already patched: {rel}"); return
    new = s
    for old, rep in edits:
        if old not in new:
            print(f"  ANCHOR NOT FOUND in {rel}:\n    {old.strip()[:100]}"); ok = False; return
        new = new.replace(old, rep, 1)
    if append:
        new = new.rstrip("\n") + "\n" + append
    bak = f.with_suffix(f.suffix + ".bak")
    if not bak.exists():                      # keep the FIRST backup (your original file)
        shutil.copy(f, bak)
    f.write_bytes((new.replace("\n", "\r\n") if crlf else new).encode("utf-8"))
    print(f"  patched: {rel}")



# 1 ---- Gram stain time from the literature (OFF by default: your baseline stays calibrated) --------------------------------
patch("modules/MALDI_biochemicals.py", [
    ("from params_config import event_name as EV\n", "from params_config import event_name as EV\nfrom modules.literature_times import gram_stain_minutes\n"),
    ("        # For gram stain a uniform distribution of a tight time window is probably most accurate\n        bio_time = random.uniform(min_bio, max_bio)\n",
     "        # For gram stain a uniform distribution of a tight time window is probably most accurate\n"
     "        bio_time = (gram_stain_minutes(random) if getattr(p, 'use_literature_task_times', False)   # smear + stain + dry + read, Gerada 2024\n"
     "                    else random.uniform(min_bio, max_bio))\n"),
], marker="gram_stain_minutes")
patch("params_config/params_d3.py", [], marker="use_literature_task_times", append="""
# --- literature task times (modules/literature_times.py) ---
use_literature_task_times = False   # True: one Gram stain of one isolate = prepare smear + stain + dry + read/report (Table 1, about 15 min median)
""")

# 2 ---- isolate count per specimen in the replication files (for the specimen-count bar chart) ------------------------------
patch("simulation_d4.py", [
    ("    df_pivot, window_diag = build_results_frame(df_raw, sim_minutes, initial_conditions_loaded)\n",
     "    df_pivot, window_diag = build_results_frame(df_raw, sim_minutes, initial_conditions_loaded)\n"
     "    if {'Specimen_ID', 'Type'} <= set(df_pivot.columns):        # isolates per specimen (0 = culture-negative / never worked up)\n"
     "        _n_iso = {k: s.n for k, s in getattr(env, 'isolate_sets', {}).items()}\n"
     "        df_pivot['N_Isolates'] = [_n_iso.get((t, i), 0) for t, i in zip(df_pivot['Type'], df_pivot['Specimen_ID'])]\n"),
], marker="_n_iso")
patch("run_montecarlo_and_plot.py", [
    ('"Total_TAT_Hours", "Arrival_Shift", "Outcome", "In_Window"]', '"Total_TAT_Hours", "Arrival_Shift", "Outcome", "In_Window", "N_Isolates"]'),
], marker='"In_Window", "N_Isolates"]')

# 3 ---- every stool config gets the Stool final-read distribution (your loop over FINAL_READ_BY_TYPE runs before the 4 new names exist) --
patch("params_config/specimen_config_d2.py", [], marker="_STOOL_FINALREAD_ALL", append="""
# ----- every stool config (whatever it is called) starts from the old "Stool" final-read model; recalibrate each one -----
for _t in [k for k in SPECIMEN_TYPES if k.upper().startswith("STOOL")]:
    if "final_read" not in SPECIMEN_TYPES[_t] and "Stool" in FINAL_READ_BY_TYPE:
        SPECIMEN_TYPES[_t]["final_read"] = dict(FINAL_READ_BY_TYPE["Stool"])
_STOOL_FINALREAD_ALL = True
""")

print("\nDONE" if ok else "\nSOME PATCHES FAILED - send me the messages above")
