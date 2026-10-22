# ir/tac.py - TAC instruction definition (C1+C2 typed version)
# Frozen, typed instruction with ty and args fields.
# Defaults keep legacy instructions valid.

from collections import namedtuple
import re

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

def is_const(x):
    return isinstance(x, int) and not isinstance(x, bool)

def is_var(x):
    return isinstance(x, str)

def wrap(x, ty):
    # reduce to canonical range of ty
    bits = int(ty[1:]) if ty[1:].isdigit() else 32
    signed = ty[0] == "i"
    mod = 1 << bits
    x = x % mod
    if signed and x >= (1 << (bits - 1)):
        x -= mod
    return x

wrap32 = lambda x: wrap(x, "i32")

def eval_binary(op, a, b, ty="i32"):
    if op == "+": return (wrap(a + b, ty), None)
    if op == "-": return (wrap(a - b, ty), None)
    if op == "*": return (wrap(a * b, ty), None)
    if op == "/":
        if b == 0: return (None, "div_by_zero")
        q = abs(a) // abs(b)
        if (a < 0) != (b < 0): q = -q
        # overflow check for INT_MIN / -1
        bits = int(ty[1:]) if ty[1:].isdigit() else 32
        if ty.startswith("i") and a == -(1 << (bits-1)) and b == -1:
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
        if b < 0 or b >= (int(ty[1:]) if ty[1:].isdigit() else 32):
            return (None, "bad_shift")
        return (wrap(a << b, ty), None)
    if op == ">>":
        bits = int(ty[1:]) if ty[1:].isdigit() else 32
        if b < 0 or b >= bits:
            return (None, "bad_shift")
        if ty.startswith("u"):
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

def uses(instr):
    op = instr.op
    if op in ("label", "goto"): return set()
    if op == "ifFalse":
        s = set()
        if isinstance(instr.arg1, str): s.add(instr.arg1)
        return s
    if op == "if":
        s = set()
        if isinstance(instr.arg1, str): s.add(instr.arg1)
        if isinstance(instr.arg2, str): s.add(instr.arg2)
        return s
    if op == "load":
        s = set()
        if isinstance(instr.arg1, str): s.add(instr.arg1)
        if isinstance(instr.arg2, str): s.add(instr.arg2)
        return s
    if op == "store":
        s = set()
        for v in (instr.arg1, instr.arg2, instr.result):
            if isinstance(v, str): s.add(v)
        return s
    if op == "addr":
        s = set()
        if isinstance(instr.arg1, str): s.add(instr.arg1)
        return s
    if op in ("print", "out_val"):
        s = set()
        if isinstance(instr.arg1, str): s.add(instr.arg1)
        return s
    if op == "out_str": return set()
    if op == "read":
        return set()
    if op == "return":
        s = set()
        if isinstance(instr.arg1, str): s.add(instr.arg1)
        return s
    if op == "call":
        s = set()
        for x in (instr.args or ()):
            if isinstance(x, str): s.add(x)
        return s
    if op == "param":
        s = set()
        if isinstance(instr.arg1, str): s.add(instr.arg1)
        return s
    if op in ("cast", "bnot"):
        s = set()
        if isinstance(instr.arg1, str): s.add(instr.arg1)
        return s
    if op in ("copy",):
        s = set()
        if isinstance(instr.arg1, str): s.add(instr.arg1)
        return s
    if op in UNARY_OPS:
        s = set()
        if isinstance(instr.arg1, str): s.add(instr.arg1)
        return s
    if op in BINARY_OPS:
        s = set()
        if isinstance(instr.arg1, str): s.add(instr.arg1)
        if isinstance(instr.arg2, str): s.add(instr.arg2)
        return s
    return set()

def defs(instr):
    op = instr.op
    if op in ("label", "goto", "ifFalse", "print", "out_str", "out_val",
              "read", "return", "store", "param"):
        return None
    return instr.result

def has_side_effect(instr):
    if instr.op in ("print", "out_str", "out_val", "read", "goto", "ifFalse",
                     "label", "return", "call", "store"):
        return True
    if instr.op in ("/", "%", "<<", ">>"):
        return True
    return False

def instr_str(i):
    op = i.op
    if op == "label": return "%s:" % i.arg1
    if op == "goto": return "goto %s" % i.arg1
    if op == "ifFalse": return "ifFalse %s goto %s" % (i.arg1, i.arg2)
    if op == "print": return "print %s" % i.arg1
    if op == "out_str": return 'out_str "%s"' % i.arg1
    if op == "out_val": return "out_val %s, %s" % (i.arg1, i.arg2)
    if op == "read": return "read %s" % i.result
    if op == "return":
        return "return" if i.arg1 is None else "return %s" % i.arg1
    if op == "call":
        args = ", ".join(str(a) for a in (i.args or ()))
        if i.result:
            return "%s = call %s(%s)" % (i.result, i.arg1, args)
        return "call %s(%s)" % (i.arg1, args)
    if op == "cast": return "%s = (%s) %s" % (i.result, i.ty, i.arg1)
    if op == "load": return "%s = %s[%s]" % (i.result, i.arg1, i.arg2)
    if op == "store": return "%s[%s] = %s" % (i.arg1, i.arg2, i.result)
    if op == "addr": return "%s = &%s" % (i.result, i.arg1)
    if op in ("neg", "not", "bnot"):
        return "%s = %s %s" % (i.result, op, i.arg1)
    if op == "copy": return "%s = %s" % (i.result, i.arg1)
    if op == "shl": return "%s = %s << %s" % (i.result, i.arg1, i.arg2)
    if op in BINARY_OPS:
        return "%s = %s %s %s" % (i.result, i.arg1, op, i.arg2)
    return repr(i)

Instr.__str__ = lambda self: instr_str(self)
