# ir/program.py - Program and Function structures (C1+C2)
from dataclasses import dataclass, field
import re


def default_value(ty):
    """The initial contents of a variable of this type.

    Arrays get a (possibly nested) list of zeroes.  A scalar local is left
    undefined until the program assigns to it, which the interpreter tracks
    by leaving the slot empty rather than by using this helper.
    """
    if ty is not None and getattr(ty, "kind", None) == "array":
        return [default_value(ty.elem) for _ in range(ty.count or 0)]
    return 0


def is_array_type(ty):
    """True for an array type (a Type object or a legacy string tag)."""
    if ty is None:
        return False
    if getattr(ty, "kind", None) == "array":
        return True
    return isinstance(ty, str) and ty.startswith("array")


@dataclass
class Function:
    name: str
    params: list = field(default_factory=list)   # list of (name, Type)
    ret_ty: object = None                        # Type, or None for void
    body: list = field(default_factory=list)     # list of Instr
    var_types: dict = field(default_factory=dict)  # name -> Type


@dataclass
class Program:
    functions: dict = field(default_factory=dict)  # name -> Function
    globals: dict = field(default_factory=dict)    # name -> (Type, init_value)

    @classmethod
    def from_legacy(cls, tac):
        from ir.tac import Instr
        # Collect variable types from TAC instructions
        var_types = {}
        for ins in tac:
            # Check all operands that could be variables
            for attr in ['arg1', 'arg2', 'result']:
                val = getattr(ins, attr, None)
                if isinstance(val, str) and re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', val):
                    if val not in var_types:
                        var_types[val] = "i32"  # default type
            # Also check instruction-specific attributes
            if hasattr(ins, 'ty') and ins.ty:
                if ins.result and isinstance(ins.result, str):
                    var_types[ins.result] = ins.ty
        f = Function(name="main", params=[], ret_ty="i32", body=list(tac),
                     var_types=var_types)
        return cls(functions={"main": f}, globals={})

    def all_instrs(self):
        out = []
        for f in self.functions.values():
            out.extend(f.body)
        return out

    def main(self):
        return self.functions.get("main")
