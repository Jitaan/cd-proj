# passes.py - Optimization passes (Compiler Design, BCSE307L)
# All optimization passes with proper ordering and fixpoint iteration

from blocks import split_blocks, join_blocks
import tac
import cfgopt
import copy_prop
import loop_opt
import cond_jump


class PassContext:
    def __init__(self, globals_set=None, var_types=None):
        self.globals = globals_set or set()
        self.var_types = var_types or {}


# Optimization pass order - carefully ordered for maximum effectiveness
# Phase 1: Local/scalar optimizations
# Phase 2: Loop optimizations
# Phase 3: Global/CFG optimizations
# Phase 4: Cleanup

ORDER = [
    # Phase 1: Local peephole & algebraic
    "cond_jump",   # Convert ifFalse to proper conditional jumps (before folding)
    "fold",        # Constant folding & propagation
    "alg",         # Algebraic simplification
    "cse",         # Common subexpression elimination (local)
    "copy_prop",   # Copy propagation
    # "dag",         # DAG-based optimization (expression DAG) - disabled due to control flow issues
    
    # Phase 2: Loop optimizations
    "licm",        # Loop invariant code motion
    "strength_red",# Reduction in strength
    "iv_elim",     # Induction variable elimination
    "loop_unroll", # Loop unrolling
    "loop_fuse",   # Loop fusion (jamming)
    
    # Phase 3: CFG/Control flow
    "cfg",         # Branch folding, unreachable, peephole
    
    # Phase 4: Dead code & cleanup
    "dce",         # Dead code elimination
    "rename",      # Rename temporaries
    "machine_idiom", # Machine idioms
]

# All available passes (for advisor)
ADVISED = list(ORDER)


def _commutative(op):
    return op in ("+", "*", "&", "|", "^", "==", "!=")


def _sortkey(x):
    if isinstance(x, int):
        return (0, x, "")
    return (1, 0, x)


def _a(ins): return ins.arg1
def _b(ins): return ins.arg2
def _dst(ins): return ins.result
def _with_a(ins, a): return ins._replace(arg1=a)
def _with_b(ins, b): return ins._replace(arg2=b)
def _with_dst(ins, dst): return ins._replace(result=dst)


# ==================== Phase 1: Local/Scalar Optimizations ====================

def _propagate_fold(instrs, ctx=None):
    """Constant propagation + folding + copy propagation"""
    blocks_list = split_blocks(instrs)
    new_blocks = []
    changes = 0
    for b in blocks_list:
        env = {}
        out = []
        for ins in b:
            op = ins.op
            before = ins
            if op == "if":
                # Handle conditional jump - propagate constants and fold constant conditions
                a = env[_a(ins)] if (isinstance(_a(ins), str) and _a(ins) in env) else _a(ins)
                b = env[_b(ins)] if (isinstance(_b(ins), str) and _b(ins) in env) else _b(ins)
                ins2 = ins._replace(arg1=a, arg2=b)
                if isinstance(ins2.arg1, int) and isinstance(ins2.arg2, int):
                    relop = ins2.op_relop
                    if relop and not ((relop == "/" or relop == "%") and ins2.arg2 == 0):
                        res = tac.eval_op(relop, ins2.arg1, ins2.arg2)
                        if res is not None:
                            # Constant condition - replace with goto or remove
                            if res == 0:
                                # Always false - fall through (remove the jump)
                                ins2 = None
                            else:
                                # Always true - replace with goto
                                ins2 = tac.Instr("goto", ins2.result, None, None)
            elif op in tac.BINARY_OPS and op != "if":
                a = env[_a(ins)] if (isinstance(_a(ins), str) and _a(ins) in env) else _a(ins)
                b = env[_b(ins)] if (isinstance(_b(ins), str) and _b(ins) in env) else _b(ins)
                ins2 = ins._replace(arg1=a, arg2=b)
                if isinstance(ins2.arg1, int) and isinstance(ins2.arg2, int):
                    if not ((op == "/" or op == "%") and ins2.arg2 == 0):
                        res = tac.eval_op(op, ins2.arg1, ins2.arg2)
                        if res is not None:
                            ins2 = tac.Instr("copy", res, None, ins2.result, ty=ins2.ty)
            elif op in tac.UNARY_OPS:
                a = env[_a(ins)] if (isinstance(_a(ins), str) and _a(ins) in env) else _a(ins)
                ins2 = _with_a(ins, a)
                if isinstance(ins2.arg1, int):
                    res = tac.eval_unary(op, ins2.arg1)
                    ins2 = tac.Instr("copy", res, None, ins2.result, ty=ins2.ty)
            elif op == "copy":
                a = env[_a(ins)] if (isinstance(_a(ins), str) and _a(ins) in env) else _a(ins)
                ins2 = _with_a(ins, a)
            # "if" handled above
            elif op == "ifFalse":
                a = env[_a(ins)] if (isinstance(_a(ins), str) and _a(ins) in env) else _a(ins)
                ins2 = _with_a(ins, a)
            elif op in ("print", "out_val"):
                a = env[_a(ins)] if (isinstance(_a(ins), str) and _a(ins) in env) else _a(ins)
                ins2 = _with_a(ins, a)
            elif op == "cast":
                a = env[_a(ins)] if (isinstance(_a(ins), str) and _a(ins) in env) else _a(ins)
                ins2 = _with_a(ins, a)
                if isinstance(ins2.arg1, int):
                    pass  # fold cast of constant not handled
            elif op == "call":
                env.clear()
                ins2 = ins
            elif op == "return":
                a = env[_a(ins)] if (isinstance(_a(ins), str) and _a(ins) in env) else _a(ins)
                ins2 = _with_a(ins, a) if ins.arg1 is not None else ins
            else:
                ins2 = ins
            if ins2 is not None and ins2 != before:
                changes += 1
            if ins2 is not None:
                dst = tac.defs(ins2)
                if dst is not None:
                    if dst in env:
                        del env[dst]
                    for k in [k for k, v in env.items() if v == dst]:
                        del env[k]
                    if ins2.op == "copy":
                        a = ins2.arg1
                        if isinstance(a, int) or (isinstance(a, str) and a != dst):
                            env[dst] = a
                out.append(ins2)
        new_blocks.append(out)
    return join_blocks(new_blocks), changes


def propagate_fold(instrs, ctx=None):
    r, _ = _propagate_fold(instrs, ctx)
    return r


def _alg(instrs, ctx=None):
    """Algebraic simplification: identities, strength reduction, commutative/associative"""
    out = []
    changes = 0
    for ins in instrs:
        if ins.op in tac.BINARY_OPS and ins.op != "if":
            new_ins = None
            op = ins.op
            a, b = _a(ins), _b(ins)
            a_const = isinstance(a, int) and not isinstance(a, bool)
            b_const = isinstance(b, int) and not isinstance(b, bool)
            
            # Algebraic identities
            if op == "+":
                if a_const and a == 0 and not b_const:
                    new_ins = tac.Instr("copy", b, None, _dst(ins), ty=ins.ty)
                elif b_const and b == 0 and not a_const:
                    new_ins = tac.Instr("copy", a, None, _dst(ins), ty=ins.ty)
            elif op == "-":
                if b_const and b == 0 and not a_const:
                    new_ins = tac.Instr("copy", a, None, _dst(ins), ty=ins.ty)
                elif not a_const and not b_const and a == b:
                    new_ins = tac.Instr("copy", 0, None, _dst(ins), ty=ins.ty)
            elif op == "*":
                if a_const and a == 1 and not b_const:
                    new_ins = tac.Instr("copy", b, None, _dst(ins), ty=ins.ty)
                elif b_const and b == 1 and not a_const:
                    new_ins = tac.Instr("copy", a, None, _dst(ins), ty=ins.ty)
                elif (a_const and a == 0) or (b_const and b == 0):
                    new_ins = tac.Instr("copy", 0, None, _dst(ins), ty=ins.ty)
                # Strength reduction: x * 2^k -> x << k
                elif a_const and not b_const:
                    c = a
                    if c > 0 and (c & (c-1)) == 0:
                        k = c.bit_length() - 1
                        if k >= 1:
                            new_ins = tac.Instr("shl", b, k, _dst(ins), ty=ins.ty)
                elif b_const and not a_const:
                    c = b
                    if c > 0 and (c & (c-1)) == 0:
                        k = c.bit_length() - 1
                        if k >= 1:
                            new_ins = tac.Instr("shl", a, k, _dst(ins), ty=ins.ty)
            elif op == "/":
                if b_const and b == 1 and not a_const:
                    new_ins = tac.Instr("copy", a, None, _dst(ins), ty=ins.ty)
                # x / 2^k -> x >> k
                elif b_const and not a_const:
                    c = b
                    if c > 0 and (c & (c-1)) == 0:
                        k = c.bit_length() - 1
                        if k >= 1:
                            new_ins = tac.Instr(">>", a, k, _dst(ins), ty=ins.ty)
            elif op == "%":
                # x % 2^k -> x & (2^k - 1)
                if b_const and not a_const:
                    c = b
                    if c > 0 and (c & (c-1)) == 0:
                        new_ins = tac.Instr("&", a, c-1, _dst(ins), ty=ins.ty)
            elif op in ("&", "|", "^"):
                if a_const and a == 0:
                    if op == "&":
                        new_ins = tac.Instr("copy", 0, None, _dst(ins), ty=ins.ty)
                    elif op == "|":
                        new_ins = tac.Instr("copy", b, None, _dst(ins), ty=ins.ty)
                    elif op == "^":
                        new_ins = tac.Instr("copy", b, None, _dst(ins), ty=ins.ty)
                elif b_const and b == 0:
                    if op == "&":
                        new_ins = tac.Instr("copy", 0, None, _dst(ins), ty=ins.ty)
                    elif op == "|":
                        new_ins = tac.Instr("copy", a, None, _dst(ins), ty=ins.ty)
                    elif op == "^":
                        new_ins = tac.Instr("copy", a, None, _dst(ins), ty=ins.ty)
                elif op == "^" and not a_const and a == b:
                    new_ins = tac.Instr("copy", 0, None, _dst(ins), ty=ins.ty)
                elif op == "&" and a_const and a == -1:
                    new_ins = tac.Instr("copy", b, None, _dst(ins), ty=ins.ty)
                elif op == "|" and a_const and a == -1:
                    new_ins = tac.Instr("copy", -1, None, _dst(ins), ty=ins.ty)
            elif op in ("<<", ">>"):
                if b_const and b == 0:
                    new_ins = tac.Instr("copy", a, None, _dst(ins), ty=ins.ty)
                elif a_const and a == 0:
                    new_ins = tac.Instr("copy", 0, None, _dst(ins), ty=ins.ty)
            
            if new_ins is not None:
                out.append(new_ins)
                changes += 1
                continue
        out.append(ins)
    return out, changes


def alg(instrs, ctx=None):
    r, _ = _alg(instrs, ctx)
    return r


def _cse(instrs, ctx=None):
    """Common subexpression elimination (per basic block)"""
    blocks_list = split_blocks(instrs)
    new_blocks = []
    changes = 0
    for b in blocks_list:
        table = {}
        out = []
        for ins in b:
            orig = ins
            replaced = False
            if ins.op == "call":
                table.clear()
            if ins.op in tac.BINARY_OPS and ins.op != "if":
                a = _a(ins)
                bb = _b(ins)
                if _commutative(ins.op):
                    x, y = sorted([a, bb], key=_sortkey)
                    key = (ins.op, x, y)
                else:
                    key = (ins.op, a, bb)
                if key in table:
                    ins = tac.Instr("copy", table[key], None, _dst(ins), ty=ins.ty)
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
            if (not replaced) and orig.op in tac.BINARY_OPS and orig.op != "if" and tac.defs(orig) is not None:
                dst = _dst(orig)
                a = _a(orig)
                bb = _b(orig)
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


def _copy_prop_pass(instrs, ctx=None):
    """Copy propagation pass"""
    return copy_prop.copy_prop(instrs)


def copy_prop_pass(instrs, ctx=None):
    return _copy_prop_pass(instrs, ctx)


# ==================== Phase 2: Loop Optimizations ====================

def _licm(instrs, ctx=None):
    """Loop invariant code motion"""
    return loop_opt.loop_invariant_code_motion(instrs)


def licm(instrs, ctx=None):
    r, _ = _licm(instrs, ctx)
    return r


def _strength_red(instrs, ctx=None):
    """Reduction in strength"""
    return loop_opt.strength_reduction(instrs)


def strength_red(instrs, ctx=None):
    r, _ = _strength_red(instrs, ctx)
    return r


def _iv_elim(instrs, ctx=None):
    """Induction variable elimination"""
    return loop_opt.induction_variable_elimination(instrs)


def iv_elim(instrs, ctx=None):
    r, _ = _iv_elim(instrs, ctx)
    return r


def _loop_unroll(instrs, ctx=None):
    """Loop unrolling"""
    return loop_opt.loop_unrolling(instrs)


def loop_unroll(instrs, ctx=None):
    r, _ = _loop_unroll(instrs, ctx)
    return r


def _loop_fuse(instrs, ctx=None):
    """Loop fusion (jamming)"""
    return loop_opt.loop_fusion(instrs)


def loop_fuse(instrs, ctx=None):
    r, _ = _loop_fuse(instrs, ctx)
    return r


# ==================== Phase 3: CFG/Control Flow ====================

def _cfg(instrs, ctx=None):
    a, na = cfgopt.branch(instrs)
    b, nb = cfgopt.unreach(a)
    c, nc = cfgopt.peep(b)
    return c, na + nb + nc


def cfg(instrs, ctx=None):
    r, _ = _cfg(instrs, ctx)
    return r


# ==================== Phase 4: Cleanup ====================

def _dce(instrs, ctx=None):
    cur = list(instrs)
    total_removed = 0
    changed = True
    while changed:
        changed = False
        blocks_list = split_blocks(cur)
        live_in, live_out = __import__("blocks").liveness(blocks_list)
        new_blocks = []
        for bi, b in enumerate(blocks_list):
            live = set(live_out[bi])
            new_instrs = []
            for ins in reversed(b):
                dst = tac.defs(ins)
                # Keep instructions with side effects
                if ins.op in ("call", "return", "out_str", "out_val", "read",
                              "goto", "ifFalse", "if", "label", "/", "%", "store"):
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


def _rename(instrs, ctx=None):
    """Rename temporaries"""
    return loop_opt.rename_temporaries(instrs)


def rename(instrs, ctx=None):
    r, _ = _rename(instrs, ctx)
    return r


def _machine_idiom(instrs, ctx=None):
    """Machine idioms"""
    return loop_opt.machine_idioms(instrs)


def machine_idiom(instrs, ctx=None):
    r, _ = _machine_idiom(instrs, ctx)
    return r


# ==================== Pass Registry ====================

PASSES = {
    # Phase 1
    "fold": propagate_fold,
    "alg": alg,
    "cse": cse,
    "copy_prop": copy_prop_pass,
    # Phase 2
    "licm": licm,
    "strength_red": strength_red,
    "iv_elim": iv_elim,
    "loop_unroll": loop_unroll,
    "loop_fuse": loop_fuse,
    # Phase 3
    "cfg": cfg,
    "cond_jump": cond_jump,
    # Phase 4
    "dce": dce,
    "rename": rename,
    "machine_idiom": machine_idiom,
}


def _run_pass(name, instrs, ctx=None):
    if name == "fold":
        return _propagate_fold(instrs, ctx)
    if name == "alg":
        return _alg(instrs, ctx)
    if name == "cse":
        return _cse(instrs, ctx)
    if name == "copy_prop":
        return _copy_prop_pass(instrs, ctx)
    if name == "licm":
        return _licm(instrs, ctx)
    if name == "strength_red":
        return _strength_red(instrs, ctx)
    if name == "iv_elim":
        return _iv_elim(instrs, ctx)
    if name == "loop_unroll":
        return _loop_unroll(instrs, ctx)
    if name == "loop_fuse":
        return _loop_fuse(instrs, ctx)
    if name == "cfg":
        return _cfg(instrs, ctx)
    if name == "cond_jump":
        return cond_jump.cond_jump(instrs, ctx)
    if name == "dce":
        return _dce(instrs, ctx)
    if name == "rename":
        return _rename(instrs, ctx)
    if name == "machine_idiom":
        return _machine_idiom(instrs, ctx)
    raise KeyError(name)


def optimise(instrs, enabled, ctx=None, log=None):
    """Main optimization driver with fixpoint iteration"""
    enabled = set(enabled)
    cur = list(instrs)
    
    # Run passes in order with fixpoint
    for rnd in range(20):  # max 20 rounds
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