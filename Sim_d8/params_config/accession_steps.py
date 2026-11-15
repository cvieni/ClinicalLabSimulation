"""Where Gerada et al. 2024 times fill gaps the LIS data cannot describe.  ASSUMPTIONS: edit freely.

Rule: LIS data first. Accession (pre-accession hold histogram + per-type touch time in specimen_config) is LIS-driven and
untouched. Gerada Table 1 is used only for steps that have no LIS timestamp:
  * bottle hand-off after accession (move to instrument, load analyzer)  -> BCx / BodyFluid
  * Gram stain of a positive bottle (unload, hazard check, vent, prepare smear, stain, dry, read/report)
Label / LIMS / combine-labels / scan-form are NOT used: that time is already inside the LIS accession interval.
"""
BOTTLE_LOAD_STEPS = ["move_location", "load_onto_analyzer"]

GRAM_BOTTLE_PREP_STEPS = ["unload_from_analyzer", "hazard_check", "vent_sample"]
GRAM_BOTTLE_TYPES = ("BCx", "BodyFluid")
GRAM_STEPS = ["prep_initial_culture_smear", "gram_stain_smear", "dry_gram_smear", "read_report_gram_smear"]


# ---- accession touch split (LIS sets the TOTAL, Gerada sets the SPLIT) ------------------------------------------
# The per-type touch time in specimen_config (calibrated to your LIS) is drawn exactly as before. When
# p.accession_substeps_enabled (default True) the tech then spends it on these steps in this order, in proportion to
# Gerada's median per specimen (task time / mean batch size). The total, and so your calibration, is unchanged;
# you gain per-step events. Bottle sets combine aerobic + anaerobic labels. ASSUMPTION: edit freely.
ACCESSION_STEPS_DEFAULT = ["label_with_lab_number", "lims", "scan_request_form"]
ACCESSION_STEPS_BY_TYPE = {
    "BCx":       ["label_with_lab_number", "lims", "combine_labels", "scan_request_form"],
    "BodyFluid": ["label_with_lab_number", "lims", "combine_labels", "scan_request_form"],
}


def accession_steps(spec_type):
    return ACCESSION_STEPS_BY_TYPE.get(spec_type, ACCESSION_STEPS_DEFAULT)
