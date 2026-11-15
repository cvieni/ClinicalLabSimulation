"""Canonical tracker stage labels.

Analysis code matches on these exact strings instead of substrings such as "4." or
"plating". If you rename a stage in a process module, rename it here too;
run_metrics.build_results_frame() warns when an expected stage never appears in a run.
"""

from Sim_d6.params_config import event_name as _EV

STAGE_ARRIVED = _EV.ARRIVED
STAGE_REJECTED_PREFIX = _EV.REJECTED_PREFIX
STAGE_ABORTED = _EV.ABORTED
STAGE_TECH_REVIEW = _EV.TECH_REVIEW
STAGE_COMPLETED = _EV.COMPLETED

# First-touch plating events (one per pathway). VERIFY these against the Stage values your
# subpathways module actually logs; they were taken from your commented-out find_col block.
STAGE_PLATING_STARTS = _EV.PLATING_STARTS
STAGE_INCUBATION_STARTS = _EV.INCUBATION_STARTS
STAGE_NEGATIVE_MARKERS = _EV.NEGATIVE_MARKERS