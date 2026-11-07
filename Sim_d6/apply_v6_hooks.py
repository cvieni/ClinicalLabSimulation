#!/usr/bin/env python3
"""v6 patch (idempotent, keeps first .bak).  Run from the project root AFTER apply_v5_hooks.py:  python apply_v6_hooks.py
Copy modules/biochem_tests.py, modules/isolates.py and params_config/biochem_config.py from this zip first."""
import shutil, sys
from pathlib import Path
root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
ok = True
def _find(rel):
    for c in (root / rel, root / Path(rel).name, root / "modules" / Path(rel).name):
        if c.exists(): return c
    return root / rel
def patch(rel, edits, marker):
    global ok
    f = _find(rel)
    if not f.exists(): print(f"  MISSING {rel}"); ok = False; return
    raw = f.read_bytes().decode("utf-8"); crlf = "\r\n" in raw; s = raw.replace("\r\n", "\n")
    if marker in s: print(f"  already patched: {rel}"); return
    new = s
    for old, rep in edits:
        if old not in new: print(f"  ANCHOR NOT FOUND in {rel}:\n    {old.strip()[:110]}"); ok = False; return
        new = new.replace(old, rep, 1)
    bak = f.with_suffix(f.suffix + ".bak")
    if not bak.exists(): shutil.copy(f, bak)
    f.write_bytes((new.replace("\n", "\r\n") if crlf else new).encode("utf-8")); print(f"  patched: {rel}")

patch("modules/specimen_process_d5.py", [
 ("start_parallel_biochem, join_parallel, note_processor\n",
  "join_parallel, note_processor, plan_biochem, split_jobs, run_biochem_jobs, plate_incubations\n"),
 ("    if rng.py.random() < p.reincubation_percent:\n",
  "    was_reincubated = rng.py.random() < p.reincubation_percent\n    if was_reincubated:\n"),
 ("    num_colonies = isolates.n\n",
  "    num_colonies = isolates.n\n"
  "    isolates.start_plate(plate_incubations(spec_cfg, was_reincubated))     # v6: incubations this plate has had at the read\n"
  "    parallel_bench = []\n"
  "    bench_now, bench_later = split_jobs(plan_biochem(env, spec_id, spec_type, spec_cfg, 'presumptive', isolates), isolates)\n"
  "    # first plate, not incubated twice -> the tech who read it runs the tests now, before any subculture\n"
  "    _ok, _procs = yield from run_biochem_jobs(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority,\n"
  "                                              'presumptive', isolates, bench_now)\n"
  "    parallel_bench += _procs\n"
  "    if not _ok:\n"
  "        yield from _finish(env, spec_id, spec_type, spec_cfg, rng, resources, tracker, spec_priority, positive=False)\n"
  "        return\n"),
 ("    needs_workup, batch_size = _sample_repeat_workup_profile(spec_cfg, rng, num_colonies)\n",
  "    needs_workup, batch_size = _sample_repeat_workup_profile(spec_cfg, rng, num_colonies)\n"
  "    _tkey = 'tech_blood' if is_blood_culture else 'tech_routine'\n"
  "    _deferred_state = {'closed': False}\n\n"
  "    def _after_first_subculture():\n"
  "        # the isolate's next plate has now had one incubation and was read by _tkey: that tech runs the deferred tests\n"
  "        isolates.start_plate(1); isolates.sub_no = 2\n"
  "        ok2, pr = yield from run_biochem_jobs(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority,\n"
  "                                              'presumptive', isolates, bench_later, bench_key=_tkey)\n"
  "        parallel_bench.extend(pr)\n"
  "        _deferred_state['closed'] = not ok2\n"),
 ("    if not needs_workup:\n        tracker.log_event(spec_id, spec_type, EV.POSITIVE_NO_WORKUP, env.now)\n    else:\n",
  "    if not needs_workup and bench_later:      # a deferred test needs a subculture: set one up for the isolates it covers\n"
  "        ok = yield from _perform_repeat_workup_batch(env, spec_id, spec_type, spec_cfg, rng, resources, inventory, tracker,\n"
  "                                                    spec_priority, _tkey, max(1, min(num_colonies, len(isolates.isolates))))\n"
  "        if not ok:\n            tracker.log_event(spec_id, spec_type, EV.ABORTED, env.now); return\n"
  "        yield from _after_first_subculture()\n"
  "    elif not needs_workup:\n        tracker.log_event(spec_id, spec_type, EV.POSITIVE_NO_WORKUP, env.now)\n    else:\n"),
 ("            with_biochem=not is_blood_culture)\n",
  "            with_biochem=not is_blood_culture,\n            after_first=_after_first_subculture if bench_later else None)\n"),
 ("    # ---- 6a-2. presumptive bench tests (oxidase / TSI / indole / catalase ...), before MALDI -------\n"
  "    if not (yield from process_biochem_phase(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority,\n"
  "                                             \"presumptive\", isolates)):\n",
  "    # ---- 6a-2. (v6) presumptive bench tests already ran: at the read (first plate) or after the first subculture ----\n"
  "    if _deferred_state['closed']:\n"),
 ("    parallel_bench = start_parallel_biochem(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority,\n"
  "                                            \"presumptive\", isolates)\n", ""),
 ("def _run_workup_rounds(env, spec_id, spec_type, spec_cfg, rng, resources, inventory, tracker, spec_priority,\n"
  "                       tech_key, batch_size, max_rounds, with_biochem):\n",
  "def _run_workup_rounds(env, spec_id, spec_type, spec_cfg, rng, resources, inventory, tracker, spec_priority,\n"
  "                       tech_key, batch_size, max_rounds, with_biochem, after_first=None):\n"),
 ("            spec_priority, tech_key, batch_size)\n        if not ok:\n            return False\n    return True\n",
  "            spec_priority, tech_key, batch_size)\n        if not ok:\n            return False\n"
  "        if rnd == 0 and after_first is not None:\n            yield from after_first()\n    return True\n"),
], marker="plate_incubations(spec_cfg, was_reincubated)")
print("\nDONE" if ok else "\nSOME PATCHES FAILED - send me the messages above")
