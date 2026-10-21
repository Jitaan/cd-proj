# ir/program.py - Program and Function structures (C1+C2)
from dataclasses import dataclass, field
import re

@dataclass
class Function:
    name: str
    params: list = field(default_factory=list)   # list of (name, ty)
    ret_ty: str = None                          # None for void
    body: list = field(default_factory=list)     # list of Instr
    var_types: dict = field(default_factory=dict)

@dataclass
class Program:
    functions: dict = field(default_factory=dict)  # name -> Function
    globals: dict = field(default_factory=dict)    # name -> (ty, init_value)

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