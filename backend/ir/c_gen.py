# ir/c_gen.py - C code generator (scalar, C1)
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend"))
from ir.tac import Instr
from ir.program import Program, Function
from frontend.c_types import CType

class CGenerator:
    def __init__(self):
        self.temp_n = 0
        self.label_n = 0
        self.var_types = {}

    def new_temp(self):
        self.temp_n += 1
        return "_t%d" % self.temp_n

    def new_label(self):
        self.label_n += 1
        return "L%d" % self.label_n

    def gen_type_tag(self, ty):
        if isinstance(ty, CType):
            return ty.tag
        if isinstance(ty, tuple):
            from frontend.c_types import parse_type_specifiers
            return parse_type_specifiers(ty[1]).tag
        return "i32"

    def generate(self, tu):
        prog = Program()
        for decl in tu[1]:
            if decl[0] == "FuncDef":
                fn = self.gen_func(decl)
                prog.functions[fn.name] = fn
            elif decl[0] == "GlobalVar":
                ty = decl[1]
                tag = self.gen_type_tag(ty)
                init = decl[3]
                val = 0
                if init is not None:
                    # constant fold simple
                    val = init[1] if init[0] == "IntLit" else 0
                prog.globals[decl[2]] = (tag, val)
        if "main" not in prog.functions:
            # wrap? assume present
            pass
        return prog

    def gen_func(self, node):
        ret_ty = node[1]
        ret_tag = self.gen_type_tag(ret_ty) if not isinstance(ret_ty, str) else ret_ty
        if isinstance(ret_ty, tuple):
            from frontend.c_types import parse_type_specifiers
            ret_tag = parse_type_specifiers(ret_ty[1]).tag
        name = node[2]
        params = node[3]
        body_node = node[4]
        fn = Function(name=name, params=[], ret_ty=ret_tag, body=[], var_types={})
        self.var_types = fn.var_types
        # params
        for (uniq, pty) in params:
            ptag = self.gen_type_tag(pty)
            fn.params.append((uniq, ptag))
            fn.var_types[uniq] = ptag
        # body
        self.gen_block(body_node, fn)
        # implicit return
        if ret_tag != "void":
            fn.body.append(Instr("return", 0, None, None, ty=ret_tag))
        return fn

    def gen_block(self, node, fn):
        if node[0] == "Block":
            for s in node[1]:
                self.gen_stmt(s, fn)
        else:
            self.gen_stmt(node, fn)

    def gen_stmt(self, node, fn):
        kind = node[0]
        if kind == "VarDecl":
            ty = node[1]
            tag = self.gen_type_tag(ty)
            name = node[2]
            fn.var_types[name] = tag
            init = node[3]
            if init is None:
                fn.body.append(Instr("copy", 0, None, name, ty=tag))
            else:
                addr, t = self.gen_expr(init, fn)
                if t != tag:
                    tmp = self.new_temp()
                    fn.var_types[tmp] = tag
                    fn.body.append(Instr("cast", addr, None, tmp, ty=tag))
                    addr = tmp
                fn.body.append(Instr("copy", addr, None, name, ty=tag))
        elif kind == "ExprStmt":
            e = node[1]
            if e[0] == "Assign":
                op = e[1]; name = e[2]; expr = e[3]
                addr, t = self.gen_expr(expr, fn)
                vtag = fn.var_types.get(name, "i32")
                if t != vtag:
                    tmp = self.new_temp()
                    fn.var_types[tmp] = vtag
                    fn.body.append(Instr("cast", addr, None, tmp, ty=vtag))
                    addr = tmp
                if op == "=":
                    fn.body.append(Instr("copy", addr, None, name, ty=vtag))
                elif op == "+=":
                    # t = name + expr
                    tmp = self.new_temp()
                    fn.var_types[tmp] = vtag
                    fn.body.append(Instr("+", name, addr, tmp, ty=vtag))
                    fn.body.append(Instr("copy", tmp, None, name, ty=vtag))
                elif op == "-=":
                    tmp = self.new_temp()
                    fn.var_types[tmp] = vtag
                    fn.body.append(Instr("-", name, addr, tmp, ty=vtag))
                    fn.body.append(Instr("copy", tmp, None, name, ty=vtag))
                elif op == "*=":
                    tmp = self.new_temp()
                    fn.var_types[tmp] = vtag
                    fn.body.append(Instr("*", name, addr, tmp, ty=vtag))
                    fn.body.append(Instr("copy", tmp, None, name, ty=vtag))
            elif e[0] == "IncDec":
                op = e[1]; prefix = e[2]; name = e[3]
                vtag = fn.var_types.get(name, "i32")
                if prefix:
                    # ++x: x = x + 1; result x
                    tmp = self.new_temp()
                    fn.var_types[tmp] = vtag
                    fn.body.append(Instr("+", name, 1, tmp, ty=vtag))
                    fn.body.append(Instr("copy", tmp, None, name, ty=vtag))
                else:
                    # x++: old = x; x = x+1
                    old = self.new_temp()
                    fn.var_types[old] = vtag
                    fn.body.append(Instr("copy", name, None, old, ty=vtag))
                    tmp = self.new_temp()
                    fn.var_types[tmp] = vtag
                    fn.body.append(Instr("+", name, 1, tmp, ty=vtag))
                    fn.body.append(Instr("copy", tmp, None, name, ty=vtag))
            else:
                addr, t = self.gen_expr(e, fn)
        elif kind == "If":
            cond, ct = self.gen_expr(node[1], fn)
            then_b = self.new_label()
            else_b = self.new_label()
            end_b = self.new_label()
            fn.body.append(Instr("ifFalse", cond, else_b if node[3] else end_b, None))
            self.gen_stmt(node[2], fn)
            if node[3]:
                fn.body.append(Instr("goto", end_b, None, None))
                fn.body.append(Instr("label", else_b, None, None))
                self.gen_stmt(node[3], fn)
            fn.body.append(Instr("label", end_b, None, None))
        elif kind == "While":
            start = self.new_label()
            end = self.new_label()
            fn.body.append(Instr("label", start, None, None))
            cond, ct = self.gen_expr(node[1], fn)
            fn.body.append(Instr("ifFalse", cond, end, None))
            self.gen_stmt(node[2], fn)
            fn.body.append(Instr("goto", start, None, None))
            fn.body.append(Instr("label", end, None, None))
        elif kind == "For":
            if node[1] is not None:
                self.gen_stmt(node[1], fn) if node[1][0] != "VarDecl" else self.gen_stmt(("VarDecl",) + node[1][1:], fn) if False else self._gen_for_init(node[1], fn)
            start = self.new_label()
            end = self.new_label()
            cont = self.new_label()
            fn.body.append(Instr("label", start, None, None))
            if node[2] is not None:
                cond, ct = self.gen_expr(node[2], fn)
                fn.body.append(Instr("ifFalse", cond, end, None))
            if node[3] is not None:
                pass
            self.gen_stmt(node[4], fn)
            # step
            if node[3] is not None:
                if isinstance(node[3], tuple) and node[3][0] == "IncDec":
                    self.gen_stmt(("ExprStmt", node[3]), fn)
                elif isinstance(node[3], tuple) and node[3][0] == "Assign":
                    self.gen_stmt(("ExprStmt", node[3]), fn)
            fn.body.append(Instr("goto", start, None, None))
            fn.body.append(Instr("label", end, None, None))
        elif kind == "Block":
            for s in node[1]:
                self.gen_stmt(s, fn)
        elif kind == "Return":
            if node[1] is not None:
                addr, t = self.gen_expr(node[1], fn)
                fn.body.append(Instr("return", addr, None, None, ty=fn.ret_ty))
            else:
                fn.body.append(Instr("return", None, None, None))
        elif kind == "Printf":
            fmt = node[1]
            if isinstance(fmt, str) and len(fmt) >= 2 and fmt[0] == '"' and fmt[-1] == '"' :
                fmt = fmt[1:-1]
            args = node[2]
            # walk format string for % specifiers
            ai = 0
            i = 0
            # emit literal text segments and out_val for each specifier
            buf = ""
            while i < len(fmt):
                if fmt[i] == "%" and i+1 < len(fmt):
                    # flush buf
                    if buf:
                        fn.body.append(Instr("out_str", buf, None, None))
                        buf = ""
                    spec_char = fmt[i+1]
                    # determine full spec (width/flags)
                    # simple: handle %d, %u, %c, %x, %ld etc
                    spec = spec_char
                    if spec_char in "duxXc":
                        if ai < len(args):
                            addr, t = self.gen_expr(args[ai], fn)
                            fn.body.append(Instr("out_val", addr, spec, None, ty="i32"))
                            ai += 1
                        i += 2
                        continue
                    else:
                        buf += fmt[i]
                        i += 1
                        continue
                else:
                    buf += fmt[i]
                    i += 1
            if buf:
                fn.body.append(Instr("out_str", buf, None, None))
        elif kind == "Putchar":
            addr, t = self.gen_expr(node[1], fn)
            fn.body.append(Instr("out_val", addr, "c", None, ty="i32"))
        elif kind == "Empty":
            pass
        else:
            # try expression
            try:
                addr, t = self.gen_expr(node, fn)
            except Exception:
                pass

    def _gen_for_init(self, node, fn):
        if node[0] == "VarDecl":
            self.gen_stmt(node, fn) if False else self.gen_stmt(("VarDecl",) + node[1:], fn)
        else:
            self.gen_stmt(("ExprStmt", node), fn)

    def gen_expr(self, node, fn):
        kind = node[0]
        if kind == "IntLit":
            return node[1], node[2]
        if kind == "CharLit":
            return node[1], "i32"
        if kind == "Ident":
            name = node[1]
            return name, fn.var_types.get(name, "i32")
        if kind == "Unary":
            addr, t = self.gen_expr(node[2], fn)
            tmp = self.new_temp()
            fn.var_types[tmp] = t
            op = node[1]
            if op == "-":
                fn.body.append(Instr("neg", addr, None, tmp, ty=t))
            elif op == "!":
                fn.body.append(Instr("not", addr, None, tmp, ty=t))
            elif op == "~":
                fn.body.append(Instr("bnot", addr, None, tmp, ty=t))
            return tmp, t
        if kind == "BinOp":
            op = node[1]
            la, lt = self.gen_expr(node[2], fn)
            ra, rt = self.gen_expr(node[3], fn)
            # cast to common type
            from frontend.c_types import common_type, CType
            # parse types
            def to_ct(ty):
                if isinstance(ty, CType): return ty
                if isinstance(ty, str):
                    bits = int(ty[1:]) if ty[1:].isdigit() else 32
                    return CType(bits, ty.startswith("i"))
                return CType(32, True)
            ct = common_type(to_ct(lt), to_ct(rt))
            ctag = ct.tag
            if lt != ctag:
                tmp = self.new_temp(); fn.var_types[tmp] = ctag
                fn.body.append(Instr("cast", la, None, tmp, ty=ctag)); la = tmp
            if rt != ctag:
                tmp = self.new_temp(); fn.var_types[tmp] = ctag
                fn.body.append(Instr("cast", ra, None, tmp, ty=ctag)); ra = tmp
            tmp = self.new_temp()
            fn.var_types[tmp] = ctag
            fn.body.append(Instr(op, la, ra, tmp, ty=ctag))
            return tmp, ctag
        if kind == "Cast":
            ty = node[1]
            tag = self.gen_type_tag(ty)
            addr, t = self.gen_expr(node[2], fn)
            tmp = self.new_temp()
            fn.var_types[tmp] = tag
            fn.body.append(Instr("cast", addr, None, tmp, ty=tag))
            return tmp, tag
        if kind == "Ternary":
            cond, ct = self.gen_expr(node[1], fn)
            tmp = self.new_temp()
            # simplified: ifFalse cond goto else
            el = self.new_label(); en = self.new_label()
            ta, tt = self.gen_expr(node[2], fn)
            fn.body.append(Instr("ifFalse", cond, el, None))
            fn.body.append(Instr("copy", ta, None, tmp, ty=tt))
            fn.body.append(Instr("goto", en, None, None))
            fn.body.append(Instr("label", el, None, None))
            fa, ft = self.gen_expr(node[3], fn)
            fn.body.append(Instr("copy", fa, None, tmp, ty=ft))
            fn.body.append(Instr("label", en, None, None))
            fn.var_types[tmp] = tt
            return tmp, tt
        if kind == "Call":
            # evaluate args
            arg_ops = []
            for a in node[2]:
                ao, at = self.gen_expr(a, fn)
                arg_ops.append(ao)
            tmp = self.new_temp()
            fn.var_types[tmp] = "i32"
            fn.body.append(Instr("call", node[1], None, tmp, ty="i32", args=tuple(arg_ops)))
            return tmp, "i32"
        if kind == "IncDec":
            # as expression (prefix): return new value
            op = node[1]; prefix = node[2]; name = node[3]
            vtag = fn.var_types.get(name, "i32")
            if prefix:
                tmp = self.new_temp()
                fn.var_types[tmp] = vtag
                fn.body.append(Instr("+", name, 1, tmp, ty=vtag))
                fn.body.append(Instr("copy", tmp, None, name, ty=vtag))
                return tmp, vtag
            else:
                old = self.new_temp()
                fn.var_types[old] = vtag
                fn.body.append(Instr("copy", name, None, old, ty=vtag))
                tmp = self.new_temp()
                fn.var_types[tmp] = vtag
                fn.body.append(Instr("+", name, 1, tmp, ty=vtag))
                fn.body.append(Instr("copy", tmp, None, name, ty=vtag))
                return old, vtag
        raise ValueError("unknown expr %s" % kind)

def generate_c(tu):
    g = CGenerator()
    return g.generate(tu)
