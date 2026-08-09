# Specimen Protocols: Plates required for primary setup
SPECIMEN_TYPES = {
    "BCx": {
        "positivity_rate": 0.10,  # 10% of bottles turn positive and get subcultured
        "media_req": {"Blood Agar": 1, "MacConkey": 1, "Chocolate Agar": 1},
        "subculture_prob": 0.40  # 40% need subculture plates
    },
    "UCx": {
        "media_req": {"Blood Agar": 1, "MacConkey": 1},
        "subculture_prob": 0.15  # 20% need subculture plates
    },
    "Wound": {
        "media_req": {"Blood Agar": 1, "MacConkey": 1, "CNA Agar": 1},
        "subculture_prob": 0.60
    },
    "TissCx": {
        "media_req": {"Blood Agar": 1, "MacConkey": 1, "CNA Agar": 1},
        "subculture_prob": 0.60
    },
    "Respiratory": {
        "media_req": {"Blood Agar": 1, "MacConkey": 1, "Chocolate Agar": 1},
        "subculture_prob": 0.10
    }
}