"""One-time patch: make every Monte Carlo replication save a per-day media log (media_###.csv.gz) for FigS6.
    python apply_media_export.py path\\to\\modules\\simulation_d4.py path\\to\\run_montecarlo_and_plot.py
Also copy the new modules\\inventory.py (it records the daily log; behaviour of the simulation is unchanged).
Edits made (a .bak of each file is kept; running it twice is safe):
  simulation_d4.py            adds  inventory.finalize(sim_minutes)  just before the media_usage line
  run_montecarlo_and_plot.py  after specimens_###.csv.gz is written, also writes media_###.csv.gz
Then re-run the Monte Carlo."""
import shutil
import sys
from pathlib import Path


def patch(path, anchor, block, marker):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    t = text.replace("\r\n", "\n")
    if marker in t:
        print(f"{path.name}: already patched")
        return
    if t.count(anchor) != 1:
        sys.exit(f"{path.name}: anchor line found {t.count(anchor)} times (expected 1); nothing changed")
    shutil.copy(path, str(path) + ".bak")
    path.write_text(t.replace(anchor, block + anchor if block.startswith("    inventory") else anchor + block, 1).replace("\n", nl),
                    encoding="utf-8", newline="")
    print(f"{path.name}: patched (backup {path.name}.bak)")


SIM_ANCHOR = "    media_usage = dict(getattr(tracker, 'media_usage', {}))"
SIM_BLOCK = "    inventory.finalize(sim_minutes)   # per-day media log for FigS6 (apply_media_export.py)\n"
RUN_ANCHOR = '    spec.to_csv(rep_dir / f"specimens_{i:03d}.csv.gz", index=False)'
RUN_BLOCK = '''
    # --- per-day media log for manuscript FigS6 (apply_media_export.py) ---
    from modules import inventory as _inv_mod
    if getattr(_inv_mod, "LAST_DAILY", None) is not None:
        _inv_mod.LAST_DAILY.assign(rep=i).to_csv(rep_dir / f"media_{i:03d}.csv.gz", index=False)
    # --- end per-day media log ---
'''

if len(sys.argv) != 3:
    sys.exit(__doc__)
patch(sys.argv[1], SIM_ANCHOR, SIM_BLOCK, "inventory.finalize(sim_minutes)")
patch(sys.argv[2], RUN_ANCHOR, RUN_BLOCK, "# --- end per-day media log ---")
