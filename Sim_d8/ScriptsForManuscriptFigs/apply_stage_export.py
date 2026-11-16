"""One-time patch (v2): make run_montecarlo_and_plot.py save EVERY registry event timestamp for Fig3B.
    python apply_stage_export.py path\\to\\run_montecarlo_and_plot.py
After specimens_###.csv.gz is written it also writes stages_###.csv.gz: Specimen_ID, Type, Arrival_Minute, Completed_Minute,
In_Window and one column per event_name.py event found in the run's pivot table. Safe to run on a file patched with v1 (the old
block is replaced). A backup <file>.bak is made. Re-run the Monte Carlo afterwards."""
import re
import shutil
import sys
from pathlib import Path

ANCHOR = '    spec.to_csv(rep_dir / f"specimens_{i:03d}.csv.gz", index=False)'
BLOCK = '''
    # --- stage timestamps for manuscript Fig3B (apply_stage_export.py v2): every event_name.py event column ---
    from params_config import event_name as _EV
    _reg = list(_EV._registry().values()) + [_e for _d in _EV.BENCH_TEST_EVENTS.values() for _e in _d.values()]
    _meta = [c for c in ("Specimen_ID", "Type", "Arrival_Minute", "Completed_Minute", "In_Window") if c in df_pivot.columns]
    _ev_cols = [c for c in df_pivot.columns if c not in _meta and any(str(c).startswith(_r) for _r in _reg)]
    df_pivot[_meta + _ev_cols].assign(rep=i).to_csv(rep_dir / f"stages_{i:03d}.csv.gz", index=False)
    # --- end stage timestamps ---
'''

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
nl = "\r\n" if "\r\n" in text else "\n"
t = text.replace("\r\n", "\n")
shutil.copy(path, str(path) + ".bak")
if "# --- end stage timestamps ---" in t:
    sys.exit("already patched (v2)")
old = re.search(r"\n    # --- stage timestamps for manuscript Fig3B \(added by apply_stage_export\.py ---.*?_st\.to_csv\(rep_dir / f\"stages_\{i:03d\}\.csv\.gz\", index=False\)\n", t, re.S)
if old:
    t = t.replace(old.group(0), "\n", 1)
    print("removed the v1 block")
if ANCHOR not in t:
    sys.exit("anchor line not found: is this the _run_one version of run_montecarlo_and_plot.py?")
path.write_text(t.replace(ANCHOR, ANCHOR + BLOCK, 1).replace("\n", nl), encoding="utf-8", newline="")
print("patched; backup at", str(path) + ".bak")
