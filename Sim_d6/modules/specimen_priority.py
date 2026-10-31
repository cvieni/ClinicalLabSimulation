"""Specimen priority rank (1 = most urgent) from SPEC_PRIORITY_MAP.

Why every specimen came back as 99: the old function looked at spec_cfg["specimen_type"], but no entry in
SPECIMEN_TYPES has that key (the type name is the dict KEY, not a field), and nothing ever sets is_stat or
is_positive_culture. All rules fell through to the default.

Resolution order now:
  1. is_stat (this specimen was ordered STAT: drawn per specimen from spec_cfg["stat_fraction"])  -> "stat" rank
  2. spec_cfg["priority_category"], a key of SPEC_PRIORITY_MAP (set per type, see the snippet for specimen_config_d2.py).
     A misspelt category raises KeyError on purpose.
  3. your original rules on spec_cfg["specimen_type"] (kept as a fallback)
  4. SPEC_PRIORITY_MAP.get("default", 99)
"""
from params_config.specimen_config_d2 import SPEC_PRIORITY_MAP


def get_specimen_priority(spec_cfg, is_stat=None):
    """Priority integer based on SPEC_PRIORITY_MAP (1 = Highest)."""
    if is_stat is None:
        is_stat = spec_cfg.get("is_stat", False)
    if is_stat:
        return SPEC_PRIORITY_MAP["stat"]

    category = spec_cfg.get("priority_category")
    if category is not None:
        return SPEC_PRIORITY_MAP[category]

    spec_type = str(spec_cfg.get("specimen_type", "")).lower()

    if spec_type in ["whole_blood", "bone_marrow"]:
        return SPEC_PRIORITY_MAP["whole_blood_bone_marrow"]
    if spec_type == "csf":
        return SPEC_PRIORITY_MAP["csf"]
    if spec_cfg.get("is_positive_culture", False):
        return SPEC_PRIORITY_MAP["positive_blood_culture"]
    if spec_type in ["surgical_specimen", "fna"]:
        return SPEC_PRIORITY_MAP["surgical_fna"]
    if spec_type in ["bal", "bronchoscopy", "invasive_respiratory"]:
        return SPEC_PRIORITY_MAP["invasive_respiratory"]
    if spec_type in ["unpreserved_stool", "unpreserved_anaerobic", "short_stability"]:
        return SPEC_PRIORITY_MAP["short_stability_unpreserved"]
    if spec_type == "sterile_body_fluid":
        return SPEC_PRIORITY_MAP["sterile_body_fluids_nonsurgical"]
    if spec_type == "tissue_nonsurgical":
        return SPEC_PRIORITY_MAP["tissues_nonsurgical"]
    if spec_type in ["tracheal_aspirate", "gastric_aspirate"]:
        return SPEC_PRIORITY_MAP["tracheal_gastric_aspirates"]
    if spec_type == "anaerobic_transport":
        return SPEC_PRIORITY_MAP["anaerobic_transport"]
    if spec_type in ["wound", "abscess", "sputum"]:
        return SPEC_PRIORITY_MAP["stain_cultures"]
    if spec_type == "stool_transport":
        return SPEC_PRIORITY_MAP["stool_in_transport"]
    if spec_type == "urine":
        return SPEC_PRIORITY_MAP["urine"]
    if spec_type == "genital":
        return SPEC_PRIORITY_MAP["genital_ureaplasma_mycoplasma"]
    if spec_type == "study":
        return SPEC_PRIORITY_MAP["studies"]

    return SPEC_PRIORITY_MAP.get("default", 99)
