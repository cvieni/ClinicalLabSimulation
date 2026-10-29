"""Single source of truth for every event (tracker "Stage") name the simulation records.

RULE: no module writes a stage string literal.  Logging code does
        tracker.log_event(spec_id, spec_type, EV.ARRIVED, env.now)
and analysis code matches with the same constants.  Rename an event here and everything follows.

    from params_config import event_name as EV

Parameterised events (the name contains a number) are built with the functions in section 9; use
`EV.is_event(stage, EV.REPEAT_WORKUP_PREFIX)`-style prefix matching for those in analysis.

Audit / keep-in-sync tools (run from the project root):
    python -m params_config.event_name scan modules params_config *.py
        lists every stage-looking string literal in your source that is NOT coming from this file,
        with the registry constant it should be replaced by (or "ADD IT" when it is new).
    EV.check_run(df_raw)
        after a run, warns about expected events that were never logged (typo / renamed / never reached).

Events marked [UNSEEN] are logged by modules I was not given (subpathways, MALDI_biochemicals,
AST_phoenix, initial-conditions loader, ...). Their values are copied from your earlier commented-out
code and are UNVERIFIED: run the `scan` command on those files and fix the values here.
"""
from __future__ import annotations

import re
import warnings

# ----------------------------------------------------------------------------------------------
# 1. Arrival, rejection, priority
# ----------------------------------------------------------------------------------------------
ARRIVED = "1. Arrived"                         # analysis matches by PREFIX: initial-state loader logs "1. Arrived (Initial State)"
REJECTED = "1b. Rejected (Pre-Analytical)"
REJECTED_PREFIX = "1b. Rejected"
PRIORITY_STAT = "1a. Priority: STAT"           # logged once per specimen, right before the pre-accession hold
PRIORITY_ROUTINE = "1a. Priority: Routine"
PRIORITY_PREFIX = "1a. Priority"

# ----------------------------------------------------------------------------------------------
# 2. Accessioning
# ----------------------------------------------------------------------------------------------
PRE_ACCESSION_HOLD = "1c. Arrived at Pre-Accession Hold"
ACCESSION_STORE_WAIT = "1c. Waiting in Accession Store"       # specimen enters the queue for an accession tech
ACCESSION_START = "1d. Accessioning Started (Tech Touch)"
ACCESSION_DONE = "1d. Accessioning Completed"

# ----------------------------------------------------------------------------------------------
# 3. Instrument loading / plating hand-off
# ----------------------------------------------------------------------------------------------
BC_INSTRUMENT_LOAD_PENDING = "2A. Time to Load onto BC Instrument (Automated)"
BC_INSTRUMENT_LOADED = "2A. Loaded into BC Instrument"
BACTEC_NEGATIVE = "2A. Bactec Bottle Negative"
BACTEC_POSITIVE = "2A. Bactec Bottle Positive"
ROUTINE_PLATING_QUEUED = "2B. Queued in Routine Plating Store"
PLATING_TECH_WAIT = "2B. Waiting for Plating Tech"
ROUTINE_PLATING_STARTED = "2C. Routine Plating Started"
ROUTINE_PLATING_DONE = "2C. Routine Plating Completed"
PRIORITY_PLATING_STARTED = "3A. Priority Blood Plating Started"
PRIORITY_PLATING_DONE = "3A. Priority Blood Plating Completed"
AUTOMATED_PLATING_STARTED = "3B-1. Sample loaded for Automated Plating Started"   # [UNSEEN]
MANUAL_PLATING_STARTED = "3B-2. Plating from PrimarySpecimen Started"              # [UNSEEN]

# ----------------------------------------------------------------------------------------------
# 4. Incubation
# ----------------------------------------------------------------------------------------------
BLOOD_PLATE_INCUBATION = "3a-3. Incubate plate from BCx or BF Bottle"
PRIMARY_INCUBATION = "Incubation from Primary Specimen Started"
GN_BROTH_INCUBATION_START = "GN Broth 6-Hour Incubation Started"
GN_BROTH_INCUBATION_DONE = "GN Broth 6-Hour Incubation Completed"
GN_BROTH_SUBCULTURE_START = "GN Broth Subculture Plating Started"
GN_BROTH_SUBCULTURE_DONE = "GN Broth Subculture Plating Completed"

# ----------------------------------------------------------------------------------------------
# 5. Plate reading / work-up decisions
# ----------------------------------------------------------------------------------------------
TECH_REVIEW = "4. Tech Review Started (Plate - Day 2)"
EXTENDED_REINCUBATION = "4a. Extended Re-Incubation"
EVALUATE_BLOOD_SUBCULTURE = "4a. Evaluate Blood Subculture (Plate - Day 2)"
# NOTE: the trailing space below is in your original string; kept byte-for-byte so old logs still match.
# Remove it HERE (one place) if it was a typo.
RAPID_BIOCHEM_SCREEN = "4a. Rapid Biochemical Screening "
DIRECT_BIOCHEM_DONE = "4a. Direct Biochemical Screening Completed"
NO_SIGNIFICANT_GROWTH = "4B. No significant growth / no repeat workup"
MIXED_FLORA = "4B. Likely Mixed Flora (4+ organisms)"
POSITIVE_NO_WORKUP = "4B. Positive culture but no repeat workup required"

# ----------------------------------------------------------------------------------------------
# 6. Repeat work-up (subculture, incubation, read)
# ----------------------------------------------------------------------------------------------
REPEAT_WORKUP_SINGLE = "5a. Repeat workup (1 organism)"
REPEAT_WORKUP_PARALLEL_PREFIX = "5a. Parallel repeat workup"
REPEAT_WORKUP_INCUBATION = "5b. Repeat workup incubation"
REPEAT_WORKUP_READ = "5c. Repeat workup plate read"
MULTI_ORGANISM_PARALLEL_PREFIX = "4B. Multiple organisms worked up in parallel"

# ----------------------------------------------------------------------------------------------
# 7. Terminal states
# ----------------------------------------------------------------------------------------------
ABORTED = "ABORTED_MEDIA_SHORTAGE"
COMPLETED = "10. Completed"

# ----------------------------------------------------------------------------------------------
# 8. Groups used by analysis code (edit membership here, not in the analysis files)
# ----------------------------------------------------------------------------------------------
PLATING_STARTS = (ROUTINE_PLATING_STARTED, PRIORITY_PLATING_STARTED,
                  AUTOMATED_PLATING_STARTED, MANUAL_PLATING_STARTED)
INCUBATION_STARTS = (PRIMARY_INCUBATION, BLOOD_PLATE_INCUBATION)
NEGATIVE_MARKERS = (BACTEC_NEGATIVE, NO_SIGNIFICANT_GROWTH)      # culture-negative -> TAT split by outcome
ACCESSION_EVENTS = (ACCESSION_STORE_WAIT, ACCESSION_START, ACCESSION_DONE)

# Events that must show up in any run long enough to finish a specimen. check_run() warns otherwise.
EXPECTED_IN_ANY_RUN = (ARRIVED, PRE_ACCESSION_HOLD, ACCESSION_STORE_WAIT, ACCESSION_START, ACCESSION_DONE,
                       COMPLETED)


# ----------------------------------------------------------------------------------------------
# 9. Parameterised event builders
# ----------------------------------------------------------------------------------------------
def repeat_workup(n_organisms: int) -> str:
    """'5a. Repeat workup (1 organism)' or '5a. Parallel repeat workup (3 organisms)'."""
    if n_organisms > 1:
        return f"{REPEAT_WORKUP_PARALLEL_PREFIX} ({n_organisms} organisms)"
    return REPEAT_WORKUP_SINGLE


def multi_organism_parallel(batch_size: int) -> str:
    return f"{MULTI_ORGANISM_PARALLEL_PREFIX} ({batch_size})"


def priority_label(is_stat: bool) -> str:
    return PRIORITY_STAT if is_stat else PRIORITY_ROUTINE


def plating_started(is_priority: bool) -> str:
    return PRIORITY_PLATING_STARTED if is_priority else ROUTINE_PLATING_STARTED


def plating_done(is_priority: bool) -> str:
    return PRIORITY_PLATING_DONE if is_priority else ROUTINE_PLATING_DONE


# ----------------------------------------------------------------------------------------------
# 10. Matching helpers (analysis side)
# ----------------------------------------------------------------------------------------------
def is_event(stage: str, event: str) -> bool:
    """Prefix match, so '1. Arrived' also matches '1. Arrived (Initial State)' but NOT
    '1c. Arrived at Pre-Accession Hold'."""
    return str(stage).startswith(event)


def mask(stage_series, event: str):
    """Boolean mask over a pandas Series of stage names (prefix match)."""
    return stage_series.astype(str).str.startswith(event)


def _registry() -> dict:
    return {k: v for k, v in globals().items()
            if k.isupper() and isinstance(v, str) and not k.startswith("_")}


def check_run(df_raw, expected=EXPECTED_IN_ANY_RUN) -> list:
    """Warn about expected events that never appear in the raw event log (columns: Stage)."""
    stages = df_raw["Stage"].astype(str)
    missing = [e for e in expected if not stages.str.startswith(e).any()]
    for e in missing:
        warnings.warn(f"Event never logged in this run: {e!r}. Renamed in a module, or no specimen got that far "
                      f"(run too short)? Edit params_config/event_name.py or the logging call.")
    return missing


# ----------------------------------------------------------------------------------------------
# 11. Audit: find stage-looking literals that bypass this registry
# ----------------------------------------------------------------------------------------------
_STAGE_LIKE = re.compile(r"^\s*(\d+[A-Za-z]?(-\d+)?\.\s|ABORTED|GN Broth|Incubation from)")


def scan_sources(paths) -> list:
    """AST-scan .py files (dirs are walked) for string literals / f-strings that look like stage names.
    Returns [(file, line, text, suggested_constant_or_None)]. Skips this file."""
    import ast
    from pathlib import Path

    reg = {v: k for k, v in _registry().items()}
    files = []
    for p in paths:
        p = Path(p)
        files += sorted(p.rglob("*.py")) if p.is_dir() else [p]
    out = []
    for f in files:
        if f.name == Path(__file__).name:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except (SyntaxError, UnicodeDecodeError) as e:
            out.append((str(f), 0, f"<could not parse: {e}>", None))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and _STAGE_LIKE.match(node.value):
                out.append((str(f), node.lineno, node.value, reg.get(node.value)))
            elif isinstance(node, ast.JoinedStr):
                head = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
                if _STAGE_LIKE.match(head):
                    out.append((str(f), node.lineno, "f\"" + head + "{...}\"", "use a builder function in section 9"))
    # f-string pieces are also visited as plain Constants: drop those already covered by a JoinedStr on the same line
    covered = {(f, ln) for f, ln, t, _ in out if t.startswith('f"')}
    return [r for r in out if r[3] == "use a builder function in section 9" or (r[0], r[1]) not in covered]


def _main(argv):
    if len(argv) < 2 or argv[0] != "scan":
        print(__doc__)
        return 0
    hits = scan_sources(argv[1:])
    if not hits:
        print("No stage-looking string literals outside event_name.py.")
        return 0
    for f, ln, text, sug in hits:
        tail = f"-> EV.{sug}" if sug and sug.isupper() else (f"-> {sug}" if sug else "-> ADD IT to event_name.py, then use the constant")
        print(f"{f}:{ln}: {text!r}  {tail}")
    print(f"\n{len(hits)} literal(s) found.")
    return 1


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
