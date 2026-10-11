import os
import json

json_dir = r"c:\Users\205124\OneDrive - ARUP Laboratories\Documents\Research\ClinicalLabSimulation\ARUP_data\json_clned_data"

if os.path.exists(json_dir):
    print("Found JSON files:")
    for f in os.listdir(json_dir):
        if f.endswith('.json'):
            print(f" - {f}")
            path = os.path.join(json_dir, f)
            with open(path) as file:
                data = json.load(file)
                print(f"   Top-level keys in file: {list(data.keys())}")
else:
    print(f"Directory not found: {json_dir}")