# ir/tac.py - TAC instruction definition (C1+C2 typed version)
# Frozen, typed instruction with ty and args fields.
# Defaults keep legacy instructions valid.

import os
import sys
from collections import namedtuple
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from frontend.c_types import Type

# Instr with ty and args (C1+C2)
class Instr(namedtuple("Instr", "op arg1 arg2 result ty args op_relop", defaults=(None, None, None, "i32", (), None))):
    @property
    def a(self): return self.arg1
    @property
    def b(self): return self.arg2
    @property
    def dst(self): return self.result
    def _replace(self, **kw):
        # map legacy names
        if "a" in kw: kw["arg1"] = kw.pop("a")
        if "b" in kw: kw["arg2"] = kw.pop("b")
        if "dst" in kw: kw["result"] = kw.pop("dst")
        return super()._replace(**kw)

BINARY_OPS = {"+", "-", "*", "/", "%", "<", ">", "<=", ">=", "==", "!=", "&&", "||",
               "&", "|", "^", "<<", ">>", "shl"}
UNARY_OPS = {"neg", "not", "bnot"}

# Ops that write to memory.  They must never be merged with each other and
# must never be removed by dead code elimination.
STORE_OPS = {"store", "storeoff", "blkcopy"}

# Ops that read memory.  They are deliberately kept out of BINARY_OPS so that
# the expression-level passes never treat a load as a pure value.
LOAD_OPS = {"load", "loadoff"}

# Ops that produce an address rather than a plain value.
ADDRESS_OPS = {"addr", "indexadd", "addoff", "litaddr"}


def is_const(x):
    return isinstance(x, int) and not isinstance(x, bool)


def is_var(x):
    return isinstance(x, str)


def _bits_signed(ty):
    """(bits, signed) for a Type, or for a legacy string tag."""
    if isinstance(ty, Type):
        if ty.kind == "scalar":
            return ty.bits, ty.signed
        if ty.kind == "pointer":
            return 64, False
        return 32, True
    if isinstance(ty, str):
        if ty == "ptr":
            return 64, False
        if len(ty) >= 2 and ty[0] in "iu" and ty[1:].isdigit():
            return int(ty[1:]), ty[0] == "i"
    return 32, True


def wrap(x, ty):
    # reduce to canonical range of ty
    bits, signed = _bits_signed(ty)
    mod = 1 << bits
    x = x % mod
    if signed and x >= (1 << (bits - 1)):
        x -= mod
    return x

wrap32 = lambda x: wrap(x, "i32")

def eval_binary(op, a, b, ty="i32"):
    bits, signed = _bits_signed(ty)
    if op == "+": return (wrap(a + b, ty), None)
    if op == "-": return (wrap(a - b, ty), None)
    if op == "*": return (wrap(a * b, ty), None)
    if op == "/":
        if b == 0: return (None, "div_by_zero")
        q = abs(a) // abs(b)
        if (a < 0) != (b < 0): q = -q
        # overflow check for INT_MIN / -1
        if signed and a == -(1 << (bits-1)) and b == -1:
            return (None, "div_overflow")
        return (wrap(q, ty), None)
    if op == "%":
        if b == 0: return (None, "div_by_zero")
        q = eval_binary("/", a, b, ty)
        if q[1]: return q
        return (wrap(a - q[0] * b, ty), None)
    if op == "<": return (1 if a < b else 0, None)
    if op == ">": return (1 if a > b else 0, None)
    if op == "<=": return (1 if a <= b else 0, None)
    if op == ">=": return (1 if a >= b else 0, None)
    if op == "==": return (1 if a == b else 0, None)
    if op == "!=": return (1 if a != b else 0, None)
    if op == "&&": return (1 if (a != 0 and b != 0) else 0, None)
    if op == "||": return (1 if (a != 0 or b != 0) else 0, None)
    if op == "shl": return (wrap(a << b, ty), None)
    if op == "&": return (wrap(a & b, ty), None)
    if op == "|": return (wrap(a | b, ty), None)
    if op == "^": return (wrap(a ^ b, ty), None)
    if op == "<<":
        if b < 0 or b >= bits:
            return (None, "bad_shift")
        return (wrap(a << b, ty), None)
    if op == ">>":
        if b < 0 or b >= bits:
            return (None, "bad_shift")
        if not signed:
            return (wrap((a & ((1 << bits) - 1)) >> b, ty), None)
        # arithmetic shift for signed
        return (wrap(a >> b, ty), None)
    raise ValueError("unknown op %s" % op)

def eval_unary(op, a, ty="i32"):
    if op == "neg": return wrap(-a, ty)
    if op == "not": return 1 if a == 0 else 0
    if op == "bnot": return wrap(~a, ty)
    raise ValueError("unknown unary %s" % op)

def eval_op(op, a, b):
    # legacy alias: returns value or None on error
    r = eval_binary(op, a, b)
    if isinstance(r, tuple):
        return r[0]
    return r

def _names(*operands):
    s = set()
    for v in operands:
        if isinstance(v, str):
            s.add(v)
    return s

def uses(instr):
    op = instr.op
    if op in ("label", "goto"): return set()
    if op == "ifFalse":
        return _names(instr.arg1)
    if op == "if":
        return _names(instr.arg1, instr.arg2)
    if op in LOAD_OPS:
        # load/loadoff base[index] -> result
        return _names(instr.arg1, instr.arg2)
    if op in STORE_OPS:
        # store base[index] = value (value travels in `result`)
        return _names(instr.arg1, instr.arg2, instr.result)
    if op == "addr":
        return _names(instr.arg1)
    if op in ("indexadd", "addoff", "ptrdiff"):
        return _names(instr.arg1, instr.arg2)
    if op == "litaddr":
        return set()
    if op in ("print", "out_val"):
        return _names(instr.arg1)
    if op == "out_str": return set()
    if op == "read":
        return set()
    if op == "return":
        return _names(instr.arg1)
    if op == "call":
        return _names(*(instr.args or ()))
    if op == "param":
        return _names(instr.arg1)
    if op in ("cast", "bnot"):
        return _names(instr.arg1)
    if op in ("copy",):
        return _names(instr.arg1)
    if op in UNARY_OPS:
        return _names(instr.arg1)
    if op in BINARY_OPS:
        return _names(instr.arg1, instr.arg2)
    return set()

def defs(instr):
    op = instr.op
    if op in ("label", "goto", "ifFalse", "if", "print", "out_val", "out_str",
              "param", "return", "read") or op in STORE_OPS:
        # `store`/`storeoff` write memory; their `result` field holds the
        # stored value, not a definition.  `blkcopy` has no result at all.
        return None
    return instr.result

def has_side_effect(instr):
    if instr.op in ("print", "out_val", "out_str", "read", "goto", "ifFalse",
                     "label", "return", "call") or instr.op in STORE_OPS:
        return True
    if instr.op in ("/", "%", "<<", ">>"):
        return True
    return False

def _escape_str(s):
    """Escape control characters so a string literal prints on one line."""
    if not isinstance(s, str):
        return s
    return (s.replace("\\", "\\\\")
             .replace("\n", "\\n")
             .replace("\r", "\\r")
             .replace("\t", "\\t")
             .replace('"', '\\"'))


def instr_str(i):
    op = i.op
    if op == "label": return "%s:" % i.arg1
    if op == "goto": return "goto %s" % i.arg1
    if op == "ifFalse": return "ifFalse %s goto %s" % (i.arg1, i.arg2)
    if op == "if": return "if %s %s %s goto %s" % (i.arg1, i.op_relop, i.arg2, i.result)
    if op == "print": return "print %s" % i.arg1
    if op == "out_str": return 'out_str "%s"' % _escape_str(i.arg1)
    if op == "out_val": return "out_val %s, %s" % (i.arg1, i.arg2)
    if op == "read": return "read %s" % i.result
    if op == "return":
        return "return" if i.arg1 is None else "return %s" % i.arg1
    if op == "call":
        args = ", ".join(str(a) for a in (i.args or ()))
        if i.result:
            return "%s = call %s(%s)" % (i.result, i.arg1, args)
        return "call %s(%s)" % (i.arg1, args)
    if op == "param":
        if getattr(i, "ty", None) == "str":
            return 'param "%s"' % _escape_str(i.arg1)
        return "param %s" % i.arg1
    if op == "cast": return "%s = (%s) %s" % (i.result, i.ty, i.arg1)
    if op == "load": return "%s = %s[%s]" % (i.result, i.arg1, i.arg2)
    if op == "store": return "%s[%s] = %s" % (i.arg1, i.arg2, i.result)
    if op == "loadoff": return "%s = *(%s + %s)" % (i.result, i.arg1, i.arg2)
    if op == "storeoff": return "*(%s + %s) = %s" % (i.arg1, i.arg2, i.result)
    if op == "addr": return "%s = &%s" % (i.result, i.arg1)
    if op == "indexadd": return "%s = %s + %s * %s" % (i.result, i.arg1, i.arg2, (i.args or (1,))[0])
    if op == "addoff": return "%s = %s + %s" % (i.result, i.arg1, i.arg2)
    if op == "ptrdiff": return "%s = %s - %s" % (i.result, i.arg1, i.arg2)
    if op == "blkcopy": return "blkcopy %s, %s, %s" % (i.arg1, i.arg2, (i.args or (0,))[0])
    if op == "litaddr": return "%s = &%r" % (i.result, i.arg1)
    if op in ("neg", "not", "bnot"):
        return "%s = %s %s" % (i.result, op, i.arg1)
    if op == "copy": return "%s = %s" % (i.result, i.arg1)
    if op == "shl": return "%s = %s << %s" % (i.result, i.arg1, i.arg2)
    if op in BINARY_OPS:
        return "%s = %s %s %s" % (i.result, i.arg1, op, i.arg2)
    return repr(i)

Instr.__str__ = lambda self: instr_str(self)
