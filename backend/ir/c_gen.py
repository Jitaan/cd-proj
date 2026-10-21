# ir/c_gen.py - C code generator (scalar, C1)
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend"))
from tac import Instr
from ir.program import Program, Function
from frontend.c_types import CType

def _skip_loc(node):
    """If last element is a (line, col) tuple, return node without it."""
    if isinstance(node, tuple) and len(node) > 0:
        last = node[-1]
        if isinstance(last, tuple) and len(last) == 2 and all(isinstance(x, int) for x in last):
            return node[:-1]
    return node


class CGenerator:
    def __init__(self):
        self.temp_n = 0
        self.label_n = 0
        self.var_types = {}

    def new_temp(self):
        self.temp_n += 1
        return "t%d" % self.temp_n

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
            decl = _skip_loc(decl)
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
        node = _skip_loc(node)
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
        for p in params:
            p = _skip_loc(p)
            uniq, pty = p[0], p[1]
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
        node = _skip_loc(node)
        if node[0] == "Block":
            for s in node[1]:
                self.gen_stmt(s, fn)
        else:
            self.gen_stmt(node, fn)

    def _gen_cond_jump(self, cond_node, target_label, fn):
        """Generate proper conditional jump: if x relop y goto L"""
        cond_node = _skip_loc(cond_node)
        if cond_node[0] == "BinOp" and cond_node[1] in ("<", ">", "<=", ">=", "==", "!="):
            op = cond_node[1]
            left_node = cond_node[2]
            right_node = cond_node[3]
            left_addr, left_type = self.gen_expr(left_node, fn)
            right_addr, right_type = self.gen_expr(right_node, fn)
            # Cast to common type if needed
            from frontend.c_types import common_type, CType
            def to_ct(ty):
                if isinstance(ty, CType): return ty
                if isinstance(ty, str):
                    bits = int(ty[1:]) if ty[1:].isdigit() else 32
                    return CType(bits, ty.startswith("i"))
                return CType(32, True)
            ct = common_type(to_ct(left_type), to_ct(right_type))
            ctag = ct.tag
            if left_type != ctag:
                tmp = self.new_temp(); fn.var_types[tmp] = ctag
                fn.body.append(Instr("cast", left_addr, None, tmp, ty=ctag)); left_addr = tmp
            if right_type != ctag:
                tmp = self.new_temp(); fn.var_types[tmp] = ctag
                fn.body.append(Instr("cast", right_addr, None, tmp, ty=ctag)); right_addr = tmp
            # Generate proper conditional jump: if left op right goto target
            fn.body.append(Instr("if", left_addr, right_addr, target_label, op_relop=op, ty=ctag))
            return
        elif cond_node[0] == "BinOp" and cond_node[1] in ("&&", "||"):
            # Logical ops - fall back to ifFalse for now
            pass
        # Fall back to ifFalse for complex conditions
        cond_addr, cond_type = self.gen_expr(cond_node, fn)
        fn.body.append(Instr("ifFalse", cond_addr, target_label, None))

    def gen_stmt(self, node, fn):
        node = _skip_loc(node)
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
            e = _skip_loc(node[1])
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
                    tmp = self.new_temp()
                    fn.var_types[tmp] = vtag
                    fn.body.append(Instr("+", name, 1, tmp, ty=vtag))
                    fn.body.append(Instr("copy", tmp, None, name, ty=vtag))
                else:
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
            cond_node = node[1]
            then_b = self.new_label()  # L1 - true block
            else_b = self.new_label()  # L2 - false block
            end_b = self.new_label()   # L3 - continuation
            # node structure: ("If", cond, then, else?, loc?)
            else_node = None
            for i in range(3, len(node)):
                n = _skip_loc(node[i]) if isinstance(node[i], tuple) else node[i]
                if n is not None:
                    else_node = n
                    break
            # Generate conditional jump: if condition goto then_b (jump to true block)
            self._gen_cond_jump(cond_node, then_b, fn)
            # If false, fall through to else block
            fn.body.append(Instr("goto", else_b, None, None))
            # True block (L1)
            fn.body.append(Instr("label", then_b, None, None))
            self.gen_stmt(node[2], fn)
            if else_node:
                # Skip false block after true block
                fn.body.append(Instr("goto", end_b, None, None))
                # False block (L2)
                fn.body.append(Instr("label", else_b, None, None))
                self.gen_stmt(else_node, fn)
            # Continuation (L3)
            fn.body.append(Instr("label", end_b, None, None))
        elif kind == "While":
            start = self.new_label()
            end = self.new_label()
            fn.body.append(Instr("label", start, None, None))
            cond_node = node[1]
            self._gen_cond_jump(cond_node, end, fn)
            self.gen_stmt(node[2], fn)
            fn.body.append(Instr("goto", start, None, None))
            fn.body.append(Instr("label", end, None, None))
        elif kind == "For":
            if node[1] is not None:
                self._gen_for_init(node[1], fn)
            start = self.new_label()
            end = self.new_label()
            body = self.new_label()
            fn.body.append(Instr("label", start, None, None))
            if node[2] is not None:
                cond_node = node[2]
                # For loops: jump to body when condition is TRUE, else fall through to end
                self._gen_cond_jump(cond_node, body, fn)
                # If condition is false, jump to end
                fn.body.append(Instr("goto", end, None, None))
                fn.body.append(Instr("label", body, None, None))
            else:
                # Infinite loop: just label the body
                body = self.new_label()
                fn.body.append(Instr("label", body, None, None))
            self.gen_stmt(node[4], fn)
            # step
            if node[3] is not None:
                step_node = node[3]
                if isinstance(step_node, tuple):
                    step_node = _skip_loc(step_node)
                    if step_node[0] == "IncDec":
                        self.gen_stmt(("ExprStmt", step_node), fn)
                    elif step_node[0] == "Assign":
                        self.gen_stmt(("ExprStmt", step_node), fn)
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
            if isinstance(fmt, str) and len(fmt) >= 2 and fmt[0] == '"' and fmt[-1] == '"':
                fmt = fmt[1:-1]
            args = node[2]
            # First, generate all argument expressions (may create temporaries)
            arg_addrs = []
            for arg in args:
                addr, t = self.gen_expr(arg, fn)
                arg_addrs.append((addr, t))
            # Emit param for format string
            fn.body.append(Instr("param", fmt, None, None, ty="str"))
            # Emit param for each argument
            for addr, t in arg_addrs:
                fn.body.append(Instr("param", addr, None, None, ty=t))
            # Emit call to printf
            tmp = self.new_temp()
            fn.var_types[tmp] = "i32"
            fn.body.append(Instr("call", "printf", len(args) + 1, tmp, ty="i32"))
        elif kind == "Putchar":
            addr, t = self.gen_expr(node[1], fn)
            fn.body.append(Instr("out_val", addr, "c", None, ty="i32"))
        elif kind == "Empty":
            pass
        else:
            try:
                addr, t = self.gen_expr(node, fn)
            except Exception:
                pass

    def _gen_for_init(self, node, fn):
        node = _skip_loc(node)
        if node[0] == "VarDecl":
            self.gen_stmt(node, fn)
        else:
            self.gen_stmt(("ExprStmt", node), fn)

    def gen_expr(self, node, fn):
        node = _skip_loc(node)
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
                arg_ops.append((ao, at))
            # emit param instructions
            for ao, at in arg_ops:
                fn.body.append(Instr("param", ao, None, None, ty=at))
            # emit call
            tmp = self.new_temp()
            fn.var_types[tmp] = "i32"
            fn.body.append(Instr("call", node[1], len(arg_ops), tmp, ty="i32"))
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