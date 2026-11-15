"""WHICH ASSUMED PARAMETERS TO VARY, AND BY HOW MUCH.   Edit this file; run_sensitivity.py and analyze_sensitivity.py read it.

One-at-a-time (OAT) design: each entry is run at a LOW and a HIGH value while everything else stays at baseline, with the
same random seeds in every run (common random numbers), so differences are the parameter's effect and not sampling noise.

Entry fields
  name   attribute in params_config/params_d3.py (the baseline value is read from there)
  group  label used in the figures
  tier   1 = core (run these first), 2 = secondary
  why    one line for the supplement: why this value is an assumption and why the range
  range  EITHER  rel=0.25            -> baseline x (1 -/+ 25 %), clipped to [0, 1] when prob=True, rounded sensibly
         OR      lo=..., hi=...       -> explicit values (scalar, tuple/list, or a dict of several linked overrides)
         lo or hi may be None for a one-sided test (e.g. a rate that is already 1.0)
Literature values (Gerada et al. 2024 task times) are REFERENCE inputs, not assumptions: they are not varied here.
"""

PARAMS = [
    # ---------------- reading schedule and incubation (placeholders in params_d3) ----------------
    dict(name="read_min_incubation_primary_hours", group="Reads & incubation", tier=1, lo=12.0, hi=20.0,
         why="Minimum incubation before a direct-plated plate can be read; no LIS timestamp for it."),
    dict(name="read_min_incubation_blood_hours", group="Reads & incubation", tier=1, lo=12.0, hi=20.0,
         why="Minimum incubation of BCx / body-fluid subculture plates."),
    dict(name="read_min_incubation_repeat_hours", group="Reads & incubation", tier=2, lo=8.0, hi=16.0,
         why="Minimum incubation of repeat-workup subcultures."),
    dict(name="plate_read_hours_weekday", group="Reads & incubation", tier=1, lo=(6.0, 14.0), hi=(8.0, 16.0),
         why="Weekday read slots (hour of day) are placeholders: shifted 1 h earlier / later."),
    dict(name="plate_read_hours_weekend", group="Reads & incubation", tier=2, lo=(7.0,), hi=(9.0,),
         why="Weekend read slot shifted 1 h earlier / later."),
    dict(name="scheduled_reads_enabled", group="Reads & incubation", tier=2, lo=False, hi=None,
         why="Structural: random incubation duration (model B) instead of scheduled read slots (model A)."),

    # ---------------- culture outcomes and work-up cascade ----------------
    dict(name="positive_specimen_rate", group="Positivity & work-up", tier=1, rel=0.25, prob=True,
         why="Default culture-positive share (per-type overrides exist for stool); LIS cannot separate positives from growth."),
    dict(name="multiple_organism_rate", group="Positivity & work-up", tier=1, rel=0.25, prob=True,
         why="Share of positives with more than one organism."),
    dict(name="monomicrobial_additional_workup_rate", group="Positivity & work-up", tier=2, rel=0.25, prob=True,
         why="Monomicrobial positives that still need a follow-up work-up."),
    dict(name="polymicrobial_workup_required_rate", group="Positivity & work-up", tier=2, rel=0.25, prob=True,
         why="Polymicrobial positives needing additional work-up."),
    dict(name="polymicrobial_all_organisms_worked_rate", group="Positivity & work-up", tier=2, rel=0.25, prob=True,
         why="Share of polymicrobial work-ups that plate every organism."),
    dict(name="max_isolates_identified", group="Positivity & work-up", tier=2, lo=2, hi=4,
         why="Isolates identified per specimen before it is called mixed flora."),
    dict(name="second_workup_percent", group="Positivity & work-up", tier=1, rel=0.25, prob=True,
         why="Day-2 repeat work-up probability (tuned, not measured)."),
    dict(name="third_workup_percent", group="Positivity & work-up", tier=2, rel=0.25, prob=True,
         why="Day-3 repeat work-up probability."),
    dict(name="additional_workup_percent", group="Positivity & work-up", tier=2, rel=0.25, prob=True,
         why="Additional repeat work-ups with multiple isolates."),
    dict(name="reincubation_percent", group="Positivity & work-up", tier=1, rel=0.25, prob=True,
         why="Share of plates sent back for re-incubation."),
    dict(name="colony_workup_time_factor", group="Positivity & work-up", tier=2, rel=0.25,
         why="Extra tech time per additional colony in a batch (literature gives no value)."),

    # ---------------- instruments ----------------
    dict(name="maldi_testing_percent", group="MALDI / Phoenix", tier=1, rel=0.25, prob=True,
         why="Share of positive isolates identified by MALDI."),
    dict(name="Phoenix_test_percent", group="MALDI / Phoenix", tier=1, rel=0.25, prob=True,
         why="Share of identified isolates that receive Phoenix AST."),
    dict(name="phoenix_run_time_hours", group="MALDI / Phoenix", tier=1, lo=4.0, hi=8.0,
         why="Phoenix run time."),
    dict(name="maldi_batch_max_wait_minutes", group="MALDI / Phoenix", tier=2, lo=90, hi=210,
         why="Wait before a part-full MALDI cartridge is run (stated assumption)."),
    dict(name="maldi_batch_isolates_range", group="MALDI / Phoenix", tier=2, lo=(20, 40), hi=(40, 60),
         why="Isolates per MALDI cartridge."),

    # ---------------- final report timing ----------------
    dict(name="final_read_delay_ast_hours", group="Final report", tier=1, lo=(6.0, 8.0), hi=(10.0, 12.0),
         why="Delay between work-up completion and verified result when AST was done (assumption)."),
    dict(name="final_read_delay_blood_hours", group="Final report", tier=2, lo=(0.5, 1.0), hi=(2.0, 3.0),
         why="Same, positive blood-culture / body-fluid bottles."),
    dict(name="final_read_delay_other_hours", group="Final report", tier=2, lo=(0.5, 1.0), hi=(2.0, 3.0),
         why="Same, positives without AST."),

    # ---------------- tech time and handling ----------------
    dict(name="avg_plating_time", group="Tech time", tier=2,
         lo=dict(avg_plating_time=2.25), hi=dict(avg_plating_time=3.75, max_plating_time=4.5),
         why="Mean manual plating time; high level also raises the upper bound so the triangular mode stays valid."),
    dict(name="auto_plating_probability", group="Tech time", tier=2, lo=0.75, hi=0.95,
         why="Share of urine/stool plated on the WASP rather than by hand."),
    dict(name="handoff_time", group="Tech time", tier=2, lo=5, hi=15,
         why="Shift hand-off minutes."),
    dict(name="accession_batch_max_wait_minutes", group="Tech time", tier=2, lo=5.0, hi=15.0,
         why="Longest wait before a partial accession batch is processed."),
    dict(name="stool_biochem_time_multiplier", group="Tech time", tier=2, lo=0.5, hi=2.0,
         why="Scale on the stool rapid-biochemical time."),

    # ---------------- bench-test positivity (set to 1.0 = every culture proceeds) ----------------
    dict(name="oxidase_positive_rate", group="Stool bench tests", tier=2, lo=0.8, hi=None,
         why="Vibrio oxidase positivity; 1.0 by default (not estimated from the LIS)."),
    dict(name="tsi_positive_rate", group="Stool bench tests", tier=2, lo=0.8, hi=None,
         why="Vibrio TSI K/A share; 1.0 by default."),

    # ---------------- structural assumption ----------------
    dict(name="accession_hold_mode", group="Structural", tier=2, lo="histogram_minus_touch", hi="none",
         why="How the pre-accession hold is drawn: full histogram (default), histogram minus touch time, or no hold."),
]
