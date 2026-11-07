#!/usr/bin/env python3
"""v7b: fixes the crash in the Stool KPIs print ('n/rep' is not in replication_summary).  Run from Sim_d6:  python apply_v7b_hooks.py"""
import sys
from pathlib import Path
f = Path(sys.argv[1]) / "run_montecarlo_and_plot.py" if len(sys.argv) > 1 else Path("run_montecarlo_and_plot.py")
raw = f.read_bytes().decode("utf-8"); crlf = "\r\n" in raw; s = raw.replace("\r\n", "\n")
old_a = '''            _n = _m["mean"].get(f"n_tat_{_k}")\n'''
old_b = '''   n/rep={_n:.0f}")'''
if old_a not in s and "n/rep=" not in s:
    sys.exit("v7 print block not found - run apply_v7_hooks.py first")
if "_n = None" in s:
    sys.exit("already patched")
s = s.replace(old_a, "            _n = None\n").replace(old_b, '''")''')
s = s.replace('''print(f"  {_st} {_lab:<22}    n/a (fewer than {10} completed per replication)" if _n is not None else f"  {_st} {_lab:<22}    not in this run")''',
              '''print(f"  {_st} {_lab:<22}    n/a (fewer than 10 completed per replication, or not in this run)")''')
f.write_bytes((s.replace("\n", "\r\n") if crlf else s).encode("utf-8")); print("patched", f)