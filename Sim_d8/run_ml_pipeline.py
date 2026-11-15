"""Run from the project root:  python run_ml_pipeline.py gen|train|forecast|recommend|validate [options]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from modules.ml_pipeline import main
if __name__ == "__main__":
    main()
