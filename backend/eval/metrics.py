# eval/metrics.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ir.tac import Instr

COSTS = {"copy":1,"neg":1,"not":1,"bnot":1,"print":1,"read":1,
         "+":1,"-":1,"<":1,">":1,"<=":1,">=":1,"==":1,"!=":1,"&&":1,"||":1,
         "*":3,"/":5,"%":5,"goto":2,"ifFalse":2,"shl":1,"&":1,"|":1,"^":1,
         "<<":1,">>":1,"cast":1,"call":5,"return":1,"out_str":2,"out_val":2,
         "label":0}

def _count_nonlabel(instrs):
    return sum(1 for i in instrs if i.op != "label")

def compute_metrics(target, inputs=None):
    # target can be list or Program
    if hasattr(target, "functions"):
        instrs = target.all_instrs()
    else:
        instrs = target
    static_count = _count_nonlabel(instrs)
    weighted_cost = sum(COSTS.get(i.op, 1) for i in instrs if i.op != "label")
    dynamic_count = 0
    dyn_cost = 0
    if inputs is not None:
        try:
            from ir.interpreter import run_program
            if hasattr(target, "functions"):
                r = run_program(target, inputs)
                dynamic_count = r.steps
                # op_counts not per op in RunResult? use steps
            else:
                from ir.interpreter import run as run_legacy
                out, dc = run_legacy(instrs, inputs)
                dynamic_count = dc
        except Exception:
            dynamic_count = 0
    return {"static_count": static_count, "weighted_cost": weighted_cost,
            "dynamic_count": dynamic_count, "dynamic_cost": dyn_cost,
            "temp_count": len(set(i.result for i in instrs if i.result and i.result.startswith("_t")))}

def reduction_percent(before, after):
    if before == 0: return 0.0
    return (before - after) / before * 100.0
