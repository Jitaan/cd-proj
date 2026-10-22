# tac.py - TAC helpers shared by the optimiser and the MiniC front end.
#
# The instruction class and the per-op tables live in ir/tac.py, so the C
# front end, the IR and the optimiser all agree on what an instruction means.
# Previously this file kept its own copy of every table and the two drifted
# apart (one of them, for instance, could not see the arguments of a call).
# What stays here is the MiniC-specific evaluation helpers.

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ir.tac import (Instr, BINARY_OPS, UNARY_OPS, STORE_OPS, LOAD_OPS,
                    ADDRESS_OPS, uses, defs, has_side_effect, instr_str,
                    wrap, wrap32, eval_binary)
from ir.tac import eval_unary as _eval_unary


def is_const(x):
    return isinstance(x, int) and not isinstance(x, bool)


def is_var(x):
    return isinstance(x, str)


def is_temp(x):
    return isinstance(x, str) and re.fullmatch(r"t\d+", x) is not None


def eval_op(op, a, b):
    """Evaluate a binary operation, or return None if it has no value."""
    r = eval_binary(op, a, b)
    if isinstance(r, tuple):
        return r[0]
    return r


def eval_unary(op, a, ty="i32"):
    """MiniC spells negation `neg` as `-` and logical not as `!`."""
    if op == "-":
        return _eval_unary("neg", a, ty)
    if op == "!":
        return _eval_unary("not", a, ty)
    return _eval_unary(op, a, ty)
