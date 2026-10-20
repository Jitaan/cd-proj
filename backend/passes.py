# Module 5: Optimisation passes (Compiler Design, BCSE307L).
# Local passes work per basic block; DCE uses global liveness.
# Each pass returns a new list and never mutates its input.

from blocks import split_blocks, join_blocks
import tac
import cfgopt

class PassContext:
    def __init__(self, globals_set=None, var_types=None):
        self.globals = globals_set or set()
        self.var_types = var_types or {}

ORDER = ["fold", "alg", "cse", "cfg", "dce"]
ADVISED = list(ORDER)   # drop entries here to skip a pass everywhere


def _commutative(op):
    return op in ("+", "*", "==", "!=")


def _sortkey(x):
    if isinstance(x, int):
        return (0, x, "")
    return (1, 0, x)


def _propagate_fold(instrs, ctx=None):
    blocks = split_blocks(instrs)
    new_blocks = []
    changes = 0
    for b in blocks:
        env = {}
        out = []
        for ins in b:
            op = ins.op
            before = ins
            if op in tac.BINARY_OPS:
                a = env[ins.a] if (isinstance(ins.a, str) and ins.a in env) else ins.a
                bb = env[ins.b] if (isinstance(ins.b, str) and ins.b in env) else ins.b
                ins2 = ins._replace(a=a, b=bb)
                if isinstance(ins2.a, int) and isinstance(ins2.b, int):
                    if not ((op == "/" or op == "%") and ins2.b == 0):
                        res = tac.eval_op(op, ins2.a, ins2.b)
                        if res is not None:
                            ins2 = tac.Instr("copy", res, None, ins2.dst)
            elif op in ("neg", "not"):
                a = env[ins.a] if (isinstance(ins.a, str) and ins.a in env) else ins.a
                ins2 = ins._replace(a=a)
                if isinstance(ins2.a, int):
                    res = tac.eval_unary(op, ins2.a)
                    ins2 = tac.Instr("copy", res, None, ins2.dst)
            elif op == "copy":
                a = env[ins.a] if (isinstance(ins.a, str) and ins.a in env) else ins.a
                ins2 = ins._replace(a=a)
            elif op == "ifFalse":
                a = env[ins.a] if (isinstance(ins.a, str) and ins.a in env) else ins.a
                ins2 = ins._replace(a=a)
            elif op == "print":
                a = env[ins.a] if (isinstance(ins.a, str) and ins.a in env) else ins.a
                ins2 = ins._replace(a=a)
            elif op == "out_val":
                a = env[ins.a] if (isinstance(ins.a, str) and ins.a in env) else ins.a
                ins2 = ins._replace(a=a)
            elif op == "cast":
                a = env[ins.a] if (isinstance(ins.a, str) and ins.a in env) else ins.a
                ins2 = ins._replace(a=a)
                if isinstance(ins2.a, int):
                    # fold cast of constant not handled (keep)
                    pass
            elif op == "call":
                # kill env for globals (conservative: clear all)
                env.clear()
                ins2 = ins
            elif op == "return":
                a = env[ins.a] if (isinstance(ins.a, str) and ins.a in env) else ins.a
                ins2 = ins._replace(a=a) if ins.a is not None else ins
            else:
                ins2 = ins
            if ins2 != before:
                changes += 1
            dst = tac.defs(ins2)
            if dst is not None:
                if dst in env:
                    del env[dst]
                for k in [k for k, v in env.items() if v == dst]:
                    del env[k]
                if ins2.op == "copy":
                    a = ins2.a
                    if isinstance(a, int) or (isinstance(a, str) and a != dst):
                        env[dst] = a
            out.append(ins2)
        new_blocks.append(out)
    return join_blocks(new_blocks), changes


def propagate_fold(instrs, ctx=None):
    r, _ = _propagate_fold(instrs, ctx)
    return r


def _alg(instrs, ctx=None):
    out = []
    changes = 0
    for ins in instrs:
        if ins.op in tac.BINARY_OPS and ins.ty if hasattr(ins, "ty") else True:
            pass
        # alg only for int/long (ty defaults to int in our project)
        if ins.op in tac.BINARY_OPS and isinstance(ins.a, str) or isinstance(ins.b, str) or isinstance(ins.a, int) or isinstance(ins.b, int):
            # apply rules
            new_ins = None
            op = ins.op
            a, b = ins.a, ins.b
            # const tests
            a_const = isinstance(a, int) and not isinstance(a, bool)
            b_const = isinstance(b, int) and not isinstance(b, bool)
            x_side = None
            # x + 0, 0 + x
            if op == "+":
                if a_const and a == 0 and not b_const:
                    new_ins = tac.Instr("copy", b, None, ins.dst)
                elif b_const and b == 0 and not a_const:
                    new_ins = tac.Instr("copy", a, None, ins.dst)
            elif op == "-":
                if b_const and b == 0 and not a_const:
                    new_ins = tac.Instr("copy", a, None, ins.dst)
                elif (not a_const) and (not b_const) and a == b and isinstance(a, str) and a == b:
                    new_ins = tac.Instr("copy", 0, None, ins.dst)
            elif op == "*":
                if (a_const and a == 1 and not b_const):
                    new_ins = tac.Instr("copy", b, None, ins.dst)
                elif (b_const and b == 1 and not a_const):
                    new_ins = tac.Instr("copy", a, None, ins.dst)
                elif (a_const and a == 0) or (b_const and b == 0):
                    new_ins = tac.Instr("copy", 0, None, ins.dst)
                # strength reduction: x * 2^k
                elif a_const and not b_const:
                    c = a
                    if c > 0 and (c & (c-1)) == 0:
                        k = c.bit_length() - 1
                        if k >= 1:
                            new_ins = tac.Instr("shl", b, k, ins.dst)
                elif b_const and not a_const:
                    c = b
                    if c > 0 and (c & (c-1)) == 0:
                        k = c.bit_length() - 1
                        if k >= 1:
                            new_ins = tac.Instr("shl", a, k, ins.dst)
            elif op == "/":
                if b_const and b == 1 and not a_const:
                    new_ins = tac.Instr("copy", a, None, ins.dst)
            if new_ins is not None:
                new_ins = new_ins._replace() if False else new_ins
                # preserve ty if present
                out.append(new_ins)
                changes += 1
                continue
        out.append(ins)
    return out, changes


def alg(instrs, ctx=None):
    r, _ = _alg(instrs, ctx)
    return r


def _cse(instrs, ctx=None):
    blocks = split_blocks(instrs)
    new_blocks = []
    changes = 0
    for b in blocks:
        table = {}
        out = []
        for ins in b:
            orig = ins
            replaced = False
            if ins.op == "call":
                table.clear()
            if ins.op in tac.BINARY_OPS:
                a = ins.a
                bb = ins.b
                if _commutative(ins.op):
                    x, y = sorted([a, bb], key=_sortkey)
                    key = (ins.op, x, y)
                else:
                    key = (ins.op, a, bb)
                if key in table:
                    ins = tac.Instr("copy", table[key], None, ins.dst)
                    replaced = True
                    changes += 1
            v = tac.defs(ins)
            if v is not None:
                to_del = []
                for key, res in table.items():
                    if res == v:
                        to_del.append(key)
                    elif len(key) >= 3 and (key[1] == v or key[2] == v):
                        to_del.append(key)
                for key in to_del:
                    del table[key]
            if (not replaced) and orig.op in tac.BINARY_OPS and tac.defs(orig) is not None:
                dst = orig.dst
                a = orig.a
                bb = orig.b
                if dst != a and dst != bb:
                    if _commutative(orig.op):
                        x, y = sorted([a, bb], key=_sortkey)
                        key = (orig.op, x, y)
                    else:
                        key = (orig.op, a, bb)
                    table[key] = dst
            out.append(ins)
        new_blocks.append(out)
    return join_blocks(new_blocks), changes


def cse(instrs, ctx=None):
    r, _ = _cse(instrs, ctx)
    return r


def _dce(instrs, ctx=None):
    cur = list(instrs)
    total_removed = 0
    changed = True
    while changed:
        changed = False
        blocks = split_blocks(cur)
        live_in, live_out = __import__("blocks").liveness(blocks)
        new_blocks = []
        for bi, b in enumerate(blocks):
            live = set(live_out[bi])
            new_instrs = []
            for ins in reversed(b):
                dst = tac.defs(ins)
                # never remove side-effect / control / call / io
                if ins.op in ("call", "return", "out_str", "out_val", "read",
                              "goto", "ifFalse", "label", "/", "%"):
                    # keep; for dead call result, null it
                    if ins.op == "call" and dst is not None and dst not in live:
                        ins = ins._replace(result=None)
                        changed = True
                    if dst is not None:
                        live.discard(dst)
                        for v in tac.uses(ins):
                            if isinstance(v, str):
                                live.add(v)
                    else:
                        for v in tac.uses(ins):
                            if isinstance(v, str):
                                live.add(v)
                    new_instrs.append(ins)
                    continue
                if dst is not None and dst not in live:
                    changed = True
                    total_removed += 1
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
                new_instrs.append(ins)
            new_instrs.reverse()
            new_blocks.append(new_instrs)
        cur = join_blocks(new_blocks)
    return cur, total_removed


def dce(instrs, ctx=None):
    r, _ = _dce(instrs, ctx)
    return r


# cfg composite
def _cfg(instrs, ctx=None):
    a, na = cfgopt.branch(instrs)
    b, nb = cfgopt.unreach(a)
    c, nc = cfgopt.peep(b)
    return c, na + nb + nc


def cfg(instrs, ctx=None):
    r, _ = _cfg(instrs, ctx)
    return r


PASSES = {
    "fold": propagate_fold,
    "alg": alg,
    "cse": cse,
    "cfg": cfg,
    "dce": dce,
}


def _run_pass(name, instrs, ctx=None):
    if name == "fold":
        return _propagate_fold(instrs, ctx)
    if name == "alg":
        return _alg(instrs, ctx)
    if name == "cse":
        return _cse(instrs, ctx)
    if name == "cfg":
        return _cfg(instrs, ctx)
    if name == "dce":
        return _dce(instrs, ctx)
    raise KeyError(name)


def optimise(instrs, enabled, ctx=None, log=None):
    enabled = set(enabled)
    cur = list(instrs)
    for rnd in range(10):
        before = cur
        for name in ORDER:
            if name in enabled:
                new, ch = _run_pass(name, cur, ctx)
                if log is not None:
                    log.append((rnd, name, bool(ch)))
                cur = new
        if cur == before:
            break
    return cur


optimize = optimise
optimize = optimise
