# config.py

# Setup resources dictionary
bc_instrument_capacity = 432 # 16 racks w/ 27 bottles each -> 432 per instrument # per SOP BACT-PROC-224
num_BACTEC_virtuo = 3
incubator_capacity = 10000
temp_slots_phenix = 1 # termpature slot on the phenix
phoenix_capacity_permach = 50 - temp_slots_phenix
numphenix = 3
maldi_cap = 2 # number of maldi instruments

Instrument_resources = {
    "incubator": incubator_capacity,
    "bc_instrument": int(num_BACTEC_virtuo * bc_instrument_capacity),
    "phoenix_instrument": int(numphenix*phoenix_capacity_permach),
    "maldi_instrument": maldi_cap
}