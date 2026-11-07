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





patch("modules/specimen_process_d5.py", [
    ("from modules.biochem_tests import process_biochem_phase, hold_primary_incubation, start_parallel_biochem, join_parallel\n",
     "from modules.biochem_tests import process_biochem_phase, hold_primary_incubation, start_parallel_biochem, join_parallel, note_processor\n"),
    ("    with req_resource(tech_resource, spec_priority) as req:\n        yield req\n        tracker.log_event(spec_id, spec_type, EV.TECH_REVIEW, env.now)\n",
     "    with req_resource(tech_resource, spec_priority) as req:\n        yield req\n"
     "        note_processor(env, spec_id, spec_type, req, tech_resource)      # remember who read this plate: the same tech runs its bench tests\n"
     "        tracker.log_event(spec_id, spec_type, EV.TECH_REVIEW, env.now)\n"),
], marker="note_processor(env, spec_id")

print("\nDONE" if ok else "\nSOME PATCHES FAILED - send me the messages above")
