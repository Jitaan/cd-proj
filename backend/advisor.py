# advisor.py - AI pass recommender (Compiler Design, BCSE307L).
# Extracts 8 features and uses a small decision tree to recommend passes.
# The AI never decides correctness; interp verifies the result.

import os
import pickle

import blocks
import passes
import tac


FEATURE_NAMES = [
    "n_instr", "n_const_binops", "n_const_copies", "n_repeated_exprs",
    "n_dead_defs", "n_blocks", "n_loops", "copy_ratio",
    "n_alg_sites", "n_const_branches", "n_peephole_sites",
]


def _count_nonlabel(instrs):
    return sum(1 for i in instrs if i.op != "label")


def _one_round_dce(instrs):
    blks = blocks.split_blocks(instrs)
    li, lo = blocks.liveness(blks)
    new_blks = []
    for bi, b in enumerate(blks):
        live = set(lo[bi])
        out = []
        for ins in reversed(b):
            dst = tac.defs(ins)
            if dst is not None and dst not in live:
                continue
            if dst is not None:
                live.discard(dst)
                for v in tac.uses(ins):
                    if isinstance(v, str):
                        live.add(v)
            else:
                for v in tac.uses(ins):
                    if isinstance(v, str):
                        live.add(v)
            out.append(ins)
        out.reverse()
        new_blks.append(out)
    return blocks.join_blocks(new_blks)


def extract_features(instrs):
    blks = blocks.split_blocks(instrs)
    n_instr = _count_nonlabel(instrs)
    n_const_binops = 0
    for i in instrs:
        if i.op in tac.BINARY_OPS:
            if isinstance(i.a, int) and isinstance(i.b, int):
                n_const_binops += 1
        elif i.op in ("neg", "not"):
            if isinstance(i.a, int):
                n_const_binops += 1
    n_const_copies = sum(1 for i in instrs if i.op == "copy" and isinstance(i.a, int))
    # repeated exprs per block
    n_repeated = 0
    for b in blks:
        seen = set()
        for ins in b:
            if ins.op in tac.BINARY_OPS:
                a, bb = ins.a, ins.b
                if ins.op in ("+", "*", "==", "!="):
                    x, y = sorted([a, bb], key=lambda z: (0, z, "") if isinstance(z, int) else (1, 0, z))
                    key = (ins.op, x, y)
                else:
                    key = (ins.op, a, bb)
                if key in seen:
                    n_repeated += 1
                seen.add(key)
    before = _count_nonlabel(instrs)
    after = _count_nonlabel(_one_round_dce(instrs))
    n_dead_defs = before - after
    n_blocks = len(blks)
    # loops: goto L where L defined earlier
    label_positions = {}
    pos = 0
    for idx, ins in enumerate(instrs):
        if ins.op == "label":
            label_positions[ins.a] = idx
    n_loops = 0
    for idx, ins in enumerate(instrs):
        if ins.op == "goto":
            lp = label_positions.get(ins.a)
            if lp is not None and lp < idx:
                n_loops += 1
    copies = sum(1 for i in instrs if i.op == "copy")
    copy_ratio = (copies / n_instr) if n_instr else 0.0
    # new features
    _, n_alg_sites = passes._alg(instrs) if hasattr(passes, "_alg") else (None, 0)
    n_const_branches = sum(1 for i in instrs if i.op == "ifFalse" and isinstance(i.a, (int, float)) and not isinstance(i.a, bool))
    _, n_peep_sites = cfgopt.peep(instrs) if False else (None, 0)
    try:
        import cfgopt
        _, n_peep_sites = cfgopt.peep(instrs)
    except Exception:
        n_peep_sites = 0
    return [n_instr, n_const_binops, n_const_copies, n_repeated, n_dead_defs,
            n_blocks, n_loops, copy_ratio, n_alg_sites, n_const_branches, n_peep_sites]


_MODEL = None


def _load_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    path = "model.pkl"
    if not os.path.exists(path):
        raise RuntimeError("run `python train.py`")
    with open(path, "rb") as f:
        _MODEL = pickle.load(f)
    return _MODEL


def recommend(instrs):
    model = _load_model()
    feats = extract_features(instrs)
    names = model["features"]
    passes = set()
    preds = {}
    advised = getattr(passes, "ADVISED", ["fold", "alg", "cse", "cfg", "dce"])
    for pname in advised:
        key = pname
        clf = model.get(pname, 0)
        if isinstance(clf, int):
            pred = clf
        else:
            pred = int(clf.predict([feats])[0])
        preds[pname] = pred
        if pred == 1:
            passes.add(pname)
    # include enablers for all passes
    if "cse" in passes:
        passes.add("fold")
        passes.add("dce")
        passes.add("cfg")
        passes.add("copy_prop")
    if "dag" in passes:
        passes.add("fold")
        passes.add("cse")
        passes.add("dce")
    if "licm" in passes:
        passes.add("fold")
        passes.add("dce")
        passes.add("cfg")
    if "strength_red" in passes:
        passes.add("alg")
        passes.add("dce")
    if "iv_elim" in passes:
        passes.add("licm")
        passes.add("strength_red")
        passes.add("dce")
    if "loop_unroll" in passes:
        passes.add("iv_elim")
        passes.add("licm")
        passes.add("dce")
    if "loop_fuse" in passes:
        passes.add("licm")
        passes.add("dce")
    if "alg" in passes:
        passes.add("cfg")
    if "cfg" in passes:
        passes.add("cond_jump")
    if "fold" in passes:
        passes.add("dce")
        passes.add("cond_jump")
    if "copy_prop" in passes:
        passes.add("dce")
        passes.add("cond_jump")
        passes.add("dce")
    if "fold" in passes:
        passes.add("dce")
    if "copy_prop" in passes:
        passes.add("dce")
    explanation = {
        "features": dict(zip(names, feats)),
        "predictions": preds,
        "passes": sorted(passes),
    }
    return passes, explanation
