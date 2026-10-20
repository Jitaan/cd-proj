# ir/program.py - Program and Function structures (C1+C2)

from dataclasses import dataclass, field

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
        f = Function(name="main", params=[], ret_ty="i32", body=list(tac),
                     var_types={})
        return cls(functions={"main": f}, globals={})

    def all_instrs(self):
        out = []
        for f in self.functions.values():
            out.extend(f.body)
        return out

    def main(self):
        return self.functions.get("main")
