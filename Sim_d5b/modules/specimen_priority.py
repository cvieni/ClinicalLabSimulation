from params_config.config_d2 import SPEC_PRIORITY_MAP

def get_specimen_priority(spec_cfg):
    """Calculates priority integer based on SPEC_PRIORITY_MAP (1 = Highest)."""
    spec_type = spec_cfg.get("specimen_type", "").lower()

    # Rule A: Whole Blood / Bone Marrow (not in blood culture bottles)
    if spec_type in ["whole_blood", "bone_marrow"]:
        return SPEC_PRIORITY_MAP["whole_blood_bone_marrow"]

    # Rule B: Any STAT request
    if spec_cfg.get("is_stat", False):
        return SPEC_PRIORITY_MAP["stat"]

    # Rule C: CSF
    if spec_type == "csf":
        return SPEC_PRIORITY_MAP["csf"]

    # Rule D: Positive Routine Blood Culture
    if spec_cfg.get("is_positive_culture", False):
        return SPEC_PRIORITY_MAP["positive_blood_culture"]

    # Rule E: Surgical / FNA
    if spec_type in ["surgical_specimen", "fna"]:
        return SPEC_PRIORITY_MAP["surgical_fna"]

    # Rule F: Invasive Respiratory (BALs, Bronchoscopy)
    if spec_type in ["bal", "bronchoscopy", "invasive_respiratory"]:
        return SPEC_PRIORITY_MAP["invasive_respiratory"]

    # Rule G: Short stability unpreserved
    if spec_type in [
        "unpreserved_stool",
        "unpreserved_anaerobic",
        "short_stability",
    ]:
        return SPEC_PRIORITY_MAP["short_stability_unpreserved"]

    # Rule H: Non-surgical sterile body fluids
    if spec_type == "sterile_body_fluid":
        return SPEC_PRIORITY_MAP["sterile_body_fluids_nonsurgical"]

    # Rule I: Non-surgical tissue
    if spec_type == "tissue_nonsurgical":
        return SPEC_PRIORITY_MAP["tissues_nonsurgical"]

    # Rule J: Tracheal and gastric aspirates
    if spec_type in ["tracheal_aspirate", "gastric_aspirate"]:
        return SPEC_PRIORITY_MAP["tracheal_gastric_aspirates"]

    # Rule K: Anaerobic in transport system
    if spec_type == "anaerobic_transport":
        return SPEC_PRIORITY_MAP["anaerobic_transport"]

    # Rule L: Stains (wounds, abscesses, sputums)
    if spec_type in ["wound", "abscess", "sputum"]:
        return SPEC_PRIORITY_MAP["stain_cultures"]

    # Rule M: Stools in transport media
    if spec_type == "stool_transport":
        return SPEC_PRIORITY_MAP["stool_in_transport"]

    # Rule N: Urine
    if spec_type == "urine":
        return SPEC_PRIORITY_MAP["urine"]

    # Rule O: Genital specimens
    if spec_type == "genital":
        return SPEC_PRIORITY_MAP["genital_ureaplasma_mycoplasma"]

    # Rule P: Studies
    if spec_type == "study":
        return SPEC_PRIORITY_MAP["studies"]

    # Fallback for unexpected or unmapped specimen types
    return SPEC_PRIORITY_MAP.get("default", 99)