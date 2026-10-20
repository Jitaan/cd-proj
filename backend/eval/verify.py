# eval/verify.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def verify_equivalent(original, optimized, input_sets=None, max_steps=100000):
    if input_sets is None: input_sets = [[]]
    from ir.interpreter import run_program
    failures = []
    for ins in input_sets:
        try:
            r1 = run_program(original, ins, max_steps=max_steps)
            r2 = run_program(optimized, ins, max_steps=max_steps)
        except Exception as e:
            failures.append((ins, str(e), "error"))
            continue
        if r1.stdout != r2.stdout or r1.exit_code != r2.exit_code or r1.error != r2.error:
            failures.append((ins, r1.stdout, r2.stdout))
    return {"ok": len(failures) == 0, "failures": failures}

def generate_inputs(target, n=20, seed=0):
    import random
    random.seed(seed)
    # count reads: approximate 2
    vecs = []
    edge = [0, 1, -1, 5, -5]
    for e in edge:
        vecs.append([e])
    for _ in range(n):
        vecs.append([random.randint(-10, 10)])
    return vecs
