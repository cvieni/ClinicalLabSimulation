"""Canonical tracker stage labels.

Analysis code matches on these exact strings instead of substrings such as "4." or
"plating". If you rename a stage in a process module, rename it here too;
run_metrics.build_results_frame() warns when an expected stage never appears in a run.
"""

STAGE_ARRIVED = "1. Arrived"                      # prefix: also matches "1. Arrived (Initial State)"
STAGE_REJECTED_PREFIX = "1b. Rejected"
STAGE_ABORTED = "ABORTED_MEDIA_SHORTAGE"
STAGE_TECH_REVIEW = "4. Tech Review Started (Plate - Day 2)"
STAGE_COMPLETED = "10. Completed"

# First-touch plating events (one per pathway). VERIFY these against the Stage values your
# subpathways module actually logs; they were taken from your commented-out find_col block.
STAGE_PLATING_STARTS = (
    "2C. Routine Plating Started",
    "3A. Priority Blood Plating Started",
    "3B-1. Sample loaded for Automated Plating Started",
    "3B-2. Plating from PrimarySpecimen Started",
)

STAGE_INCUBATION_STARTS = (
    "Incubation from Primary Specimen Started",
    "3a-3. Incubate plate from BCx or BF Bottle",
)

# Stages that mark a specimen as culture-NEGATIVE (used to split TAT by outcome).
STAGE_NEGATIVE_MARKERS = (
    "2A. Bactec Bottle Negative",
    "4B. No significant growth / no repeat workup",
)
