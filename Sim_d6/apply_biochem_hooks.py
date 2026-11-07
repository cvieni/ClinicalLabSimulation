#!/usr/bin/env python3
"""One-time patch for the bench tests (idempotent, writes .bak copies).   Run from the project root:  python apply_biochem_hooks.py
Copy modules/biochem_tests.py and params_config/biochem_config.py into your project first."""
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


# 1 ---- event names -------------------------------------------------------------------------------
patch("params_config/event_name.py", [
    ('BIOFIRE_DONE = "Optional 2b: BioFire Completed"\n', '''BIOFIRE_DONE = "Optional 2b: BioFire Completed"

# Bench tests (modules/biochem_tests.py).  setup = tech starts, wait = tube/strip incubating, done = result read
BENCH_TEST_EVENTS = {
    "oxidase":       {"setup": "6e. Oxidase Test Started",             "done": "6e. Oxidase Test Completed"},
    "tsi":           {"setup": "6f. TSI Inoculation Started",          "wait": "6f. TSI Incubation Started",      "done": "6f. TSI Read Completed"},
    "indole":        {"setup": "6g. Indole Spot Test Started",         "done": "6g. Indole Spot Test Completed"},
    "catalase":      {"setup": "6h. Catalase Test Started",            "done": "6h. Catalase Test Completed"},
    "pbp":           {"setup": "6i. PBP2a Lateral Flow Setup Started", "wait": "6i. PBP2a Lateral Flow Developing", "done": "6i. PBP2a Lateral Flow Read Completed"},
    "latex":         {"setup": "6j. E. coli Latex Agglutination Started", "done": "6j. E. coli Latex Agglutination Completed"},
    "biochem_panel": {"setup": "6k. Biochemical Panel Started",        "done": "6k. Biochemical Panel Completed"},
}
BIOCHEM_DISCARD = "6z. Presumptive Test Negative - Culture Closed"      # counted as culture-negative (see NEGATIVE_MARKERS)
'''),
    ("NEGATIVE_MARKERS = (BACTEC_NEGATIVE, NO_SIGNIFICANT_GROWTH)", "NEGATIVE_MARKERS = (BACTEC_NEGATIVE, NO_SIGNIFICANT_GROWTH, BIOCHEM_DISCARD)"),
], marker="BENCH_TEST_EVENTS")

# 2 ---- parameters --------------------------------------------------------------------------------
patch("params_config/params_d3.py", [], marker="biochem_tests_enabled", append='''
# --- bench tests (modules/biochem_tests.py; which tests run, and how often, is in params_config/biochem_config.py) ---
biochem_tests_enabled = True
# tech hands-on minutes (min, max)
min_oxidase_time, max_oxidase_time = 1.0, 2.0
min_indole_time, max_indole_time = 1.0, 2.0
min_catalase_time, max_catalase_time = 1.0, 2.0
min_latex_time, max_latex_time = 2.0, 5.0
min_tsi_setup_time, max_tsi_setup_time = 2.0, 4.0
min_tsi_read_time, max_tsi_read_time = 1.0, 2.0
min_tsi_incubation_hours, max_tsi_incubation_hours = 18.0, 24.0          # tube sits in an incubator slot
min_pbp_setup_time, max_pbp_setup_time = 2.0, 3.0
min_pbp_wait_minutes, max_pbp_wait_minutes = 10.0, 15.0                  # lateral-flow development; tech is free
min_pbp_read_time, max_pbp_read_time = 0.5, 1.0
# P(result positive). Only matters where the plan says on_negative="stop" or requires_prev (Vibrio oxidase/TSI).
# 1.0 = every culture proceeds, which is what the draft StoolCulture_biochemicals.py did. SET FROM YOUR LIS.
oxidase_positive_rate = 1.0
tsi_positive_rate = 1.0              # for Vibrio: share of TSI reading K/A
indole_positive_rate = 1.0
catalase_positive_rate = 1.0
pbp_positive_rate = 1.0
latex_positive_rate = 1.0
biochem_panel_positive_rate = 1.0
''')

# 3 ---- specimen workflow ------------------------------------------------------------------------
patch("modules/specimen_process_d5.py", [
    ("from modules.final_read import process_final_read\n",
     "from modules.final_read import process_final_read\nfrom modules.biochem_tests import process_biochem_phase, hold_primary_incubation\n"),
    # GN broth + HE subculture only for stool configs that plate GN broth (E. coli routine), not Campy/Vibrio/Yersinia
    ("    if is_stool_culture:\n        tracker.log_event(spec_id, spec_type, EV.GN_BROTH_INCUBATION_START, env.now)",
     '    if is_stool_culture and spec_cfg.get("gn_broth_enrichment", True):\n        tracker.log_event(spec_id, spec_type, EV.GN_BROTH_INCUBATION_START, env.now)'),
    ("""    with resources["incubator"].request() as inc_req:
        yield inc_req
        tracker.log_event(spec_id, spec_type, EV.PRIMARY_INCUBATION, env.now)
        yield env.timeout(_sample_incubation_minutes(env, spec_cfg, rng, "primary"))
    return True""",
     """    # per-type override (TCBS 18 h, CVA 72 h, Yersinia 48 h at room temperature) or the default scheduled-read model
    yield from hold_primary_incubation(env, spec_id, spec_type, spec_cfg, resources, tracker,
                                       lambda: _sample_incubation_minutes(env, spec_cfg, rng, "primary"))
    return True"""),
    ("if spec_type == 'Stool' else 1.0", "if spec_type.upper().startswith('STOOL') else 1.0"),
    ("    # ---- 6b/6c. identification and AST, driven by the isolates actually present -----\n",
     """    # ---- 6a-2. presumptive bench tests (oxidase / TSI / indole / catalase ...), before MALDI -------
    if not (yield from process_biochem_phase(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority,
                                             "presumptive", n_isolates=num_colonies)):
        yield from _finish(env, spec_id, spec_type, spec_cfg, rng, resources, tracker, spec_priority, positive=False)   # closed: no MALDI/AST
        return

    # ---- 6b/6c. identification and AST, driven by the isolates actually present -----
"""),
    ('    phoenix_rate = _rate(spec_cfg, "Phoenix_test_percent")\n',
     """    if n_identified > 0:      # post-ID bench tests (PBP2a lateral flow, E. coli latex) before AST
        yield from process_biochem_phase(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority,
                                         "post_id", n_isolates=n_identified)

    phoenix_rate = _rate(spec_cfg, "Phoenix_test_percent")
"""),
], marker="process_biochem_phase")

# 4 ---- stool configs ----------------------------------------------------------------------------
patch("params_config/specimen_config_d2.py", [
    # your file has an extra "}" after the Stool_Yersinia block (SyntaxError before any of my changes): remove it
    ("\n    }\n}\n\n# Attach the explicit tuning matrix", "\n}\n\n# Attach the explicit tuning matrix"),
], marker="_STOOL_PATHWAY_CFG", append='''

# ===== stool pathways (modules/biochem_tests.py) ==============================================================
# primary_incubation overrides the default incubation model: TCBS 18 h (Vibrio), CVA 72 h (Campylobacter),
# Yersinia 48 h at room temperature (no incubator slot).  Per-type test times/percentages can be overridden here too.
_STOOL_PATHWAY_CFG = {
    "Stool_Vibrio":   {"gn_broth_enrichment": False, "primary_incubation": {"hours": 18.0, "incubator": True}},
    "Stool_Campy":    {"gn_broth_enrichment": False, "primary_incubation": {"hours": 72.0, "incubator": True}},
    "Stool_Yersinia": {"gn_broth_enrichment": False, "primary_incubation": {"hours": 48.0, "incubator": False},
                       "min_tsi_setup_time": 3.0, "max_tsi_setup_time": 7.0},       # TSI + two MIO tubes
}
for _t, _c in _STOOL_PATHWAY_CFG.items():
    if _t in SPECIMEN_TYPES:
        SPECIMEN_TYPES[_t].update(_c)
# the four stool configs replace the single "Stool" type: give each the old Stool final-read as a STARTING POINT
# (re-run calibrate_final_read.py per stool test; Campy/Vibrio/Yersinia differ)
for _t in ("Stool_EcoliRoutine", "Stool_Campy", "Stool_Vibrio", "Stool_Yersinia"):
    if _t in SPECIMEN_TYPES and "final_read" not in SPECIMEN_TYPES[_t] and "Stool" in FINAL_READ_BY_TYPE:
        SPECIMEN_TYPES[_t]["final_read"] = dict(FINAL_READ_BY_TYPE["Stool"])
''')

# 5 ---- per-isolate tracking + parallel TSI (applies on top of stage 3, whether or not v1 was applied before) ---------------
patch("modules/specimen_process_d5.py", [
    ("from modules.biochem_tests import process_biochem_phase, hold_primary_incubation\n",
     "from modules.biochem_tests import process_biochem_phase, hold_primary_incubation, start_parallel_biochem, join_parallel\n"
     "from modules.isolates import get_isolates, PyRng, rate_for\n"),
    # blood / body fluid: one Gram stain PER ISOLATE (the isolate set is created when the bottle flags positive)
    ('    yield from process_GramStain(env, spec_id, spec_type, resources, tracker, spec_priority, "tech_blood")\n',
     '    isolates = get_isolates(env, spec_id, spec_type,\n'
     '                            lambda r: _sample_num_colonies(spec_cfg, PyRng(r), is_blood_culture))\n'
     '    for iso in isolates.pending("gram"):                 # exactly one Gram stain per isolate\n'
     '        isolates.mark(iso, "gram")\n'
     '        yield from process_GramStain(env, spec_id, spec_type, resources, tracker, spec_priority, "tech_blood")\n'),
    # day 2: the isolate set (created at Gram stain for bottles, here for plates) replaces the bare organism count
    ("    num_colonies = _sample_num_colonies(spec_cfg, rng, is_blood_culture)\n",
     "    isolates = get_isolates(env, spec_id, spec_type,\n"
     "                            lambda r: _sample_num_colonies(spec_cfg, PyRng(r), is_blood_culture))\n"
     "    num_colonies = isolates.n\n"),
    ('"presumptive", n_isolates=num_colonies)):', '"presumptive", isolates)):'),
    # MALDI / AST: per-isolate draws, claimed once
    ('    n_candidates = min(num_colonies, p.max_isolates_identified)\n'
     '    maldi_rate = _rate(spec_cfg, "maldi_testing_percent")\n'
     '    n_identified = sum(rng.py.random() < maldi_rate for _ in range(n_candidates))\n',
     '    # TSI (and any other parallel bench test) starts now and runs alongside MALDI/AST; joined before the final read\n'
     '    parallel_bench = start_parallel_biochem(env, spec_id, spec_type, spec_cfg, resources, tracker, spec_priority,\n'
     '                                            "presumptive", isolates)\n'
     '    maldi_rate = rate_for(isolates, spec_cfg, _rate(spec_cfg, "maldi_testing_percent"), "multi_isolate_maldi_rate")\n'
     '    maldi_set = isolates.select("maldi", maldi_rate, limit=p.max_isolates_identified)   # each isolate: at most ONE MALDI\n'
     '    n_identified = len(maldi_set)\n'),
    ('"post_id", n_isolates=n_identified)', '"post_id", isolates)'),
    ('    phoenix_rate = _rate(spec_cfg, "Phoenix_test_percent")\n'
     '    n_ast = sum(rng.py.random() < phoenix_rate for _ in range(n_identified))\n',
     '    phoenix_rate = rate_for(isolates, spec_cfg, _rate(spec_cfg, "Phoenix_test_percent"), "multi_isolate_ast_rate")\n'
     '    n_ast = len(isolates.select("ast", phoenix_rate, among=maldi_set))                # only identified isolates, at most ONE AST each\n'),
    ("    # ---- 10. complete ---------------------------------------------------------------\n",
     "    yield from join_parallel(env, parallel_bench)        # TSI etc. must be read before the final report\n\n"
     "    # ---- 10. complete ---------------------------------------------------------------\n"),
], marker="join_parallel(env, parallel_bench)")

patch("params_config/params_d3.py", [], marker="isolate_strict", append="""
# --- per-isolate tracking (modules/isolates.py) ---
isolate_strict = True            # True: a second Gram/MALDI/AST/bench test on the same isolate (or AST without MALDI) raises an error
multi_isolate_maldi_rate = None  # P(isolate is spotted | specimen has >= 2 isolates); None = same as maldi_testing_percent
multi_isolate_ast_rate = None    # P(identified isolate gets AST | specimen has >= 2 isolates); None = same as Phoenix_test_percent
export_isolate_ledger = False    # True: write results_experiments/isolate_ledger_proc_<pid>_seed<seed>.csv for every run
""")

patch("simulation_d4.py", [
    ("    stochastic_stats = extract_run_stochastic_metrics(df_raw, total_specimens)\n",
     "    stochastic_stats = extract_run_stochastic_metrics(df_raw, total_specimens)\n"
     "    from modules.isolates import audit_ledger, export_ledger          # per-isolate audit: duplicate tests must be 0\n"
     "    if isinstance(stochastic_stats, dict):\n"
     "        stochastic_stats.update(audit_ledger(env))\n"
     "    if getattr(p, 'export_isolate_ledger', False):\n"
     "        export_ledger(env, Path('results_experiments') / f'isolate_ledger_proc_{os.getpid()}_seed{seed}.csv')\n"),
], marker="audit_ledger(env)")

# 6 ---- rates you gave: culture positivity (Campy / Vibrio / Yersinia) --------------------------------------------------------
patch("params_config/specimen_config_d2.py", [], marker="_STOOL_POSITIVITY", append="""
# P(culture positive) per stool config (positive_specimen_rate is read by the day-2 outcome draw)
_STOOL_POSITIVITY = {"Stool_Campy": 0.10, "Stool_Vibrio": 0.025, "Stool_Yersinia": 0.05}
for _t, _v in _STOOL_POSITIVITY.items():
    if _t in SPECIMEN_TYPES:
        SPECIMEN_TYPES[_t]["positive_specimen_rate"] = _v
""")

print("\nDONE" if ok else "\nSOME PATCHES FAILED - send me the messages above")
