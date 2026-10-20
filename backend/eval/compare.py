# eval/compare.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def compare_program(prog, configs, inputs):
    from optimizer.pipeline import run_pipeline if False else None
    out = {}
    for name, passes in configs.items():
        out[name] = {"passes": passes}
    return out

def to_table(result):
    return str(result)
