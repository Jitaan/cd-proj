# ir/c_gen.py - C code generator (scalar, C1 + arrays/pointers)
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

    def _lvalue_name(self, base):
        """Return the variable name for a simple lvalue, else None.

        The parser represents `i++` as either a bare name string (statement
        form) or an ("Ident", name[, loc]) node (expression form).
        """
        base = _skip_loc(base)
        if isinstance(base, str):
            return base
        if isinstance(base, tuple) and base and base[0] == "Ident":
            return base[1]
        return None

    def gen_incdec(self, base, op, prefix, fn):
        """Generate `++`/`--` for scalar or array-element lvalues.

        Returns (address, type) of the resulting value: the new value for
        prefix form, the old value for postfix form.
        """
        bop = "+" if op == "++" else "-"
        name = self._lvalue_name(base)
        if name is not None:
            vtag = fn.var_types.get(name, "i32")
            old = None
            if not prefix:
                old = self.new_temp()
                fn.var_types[old] = vtag
                fn.body.append(Instr("copy", name, None, old, ty=vtag))
            tmp = self.new_temp()
            fn.var_types[tmp] = vtag
            fn.body.append(Instr(bop, name, 1, tmp, ty=vtag))
            fn.body.append(Instr("copy", tmp, None, name, ty=vtag))
            return (tmp if prefix else old), vtag
        node = _skip_loc(base)
        if isinstance(node, tuple) and node and node[0] == "Index":
            arr_addr, _ = self.gen_expr(node[1], fn)
            idx_addr, _ = self.gen_expr(node[2], fn)
            old = self.new_temp()
            fn.var_types[old] = "i32"
            fn.body.append(Instr("load", arr_addr, idx_addr, old, ty="i32"))
            new = self.new_temp()
            fn.var_types[new] = "i32"
            fn.body.append(Instr(bop, old, 1, new, ty="i32"))
            fn.body.append(Instr("store", arr_addr, idx_addr, new, ty="i32"))
            return (new if prefix else old), "i32"
        # Unsupported lvalue shape: evaluate for its side effects only.
        return self.gen_expr(node, fn)

    def gen_type_tag(self, ty):
        if isinstance(ty, CType):
            return ty.tag
        if isinstance(ty, tuple):
            if ty[0] == "Type":
                from frontend.c_types import parse_type_specifiers
                return parse_type_specifiers(ty[1]).tag
            if ty[0] == "Array":
                return "array%d" % ty[1]
            if ty[0] == "Pointer":
                return "ptr"
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

    def _gen_cond_jump(self, cond_node, target_label, fn):
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
            # Logical ops - evaluate the whole expression for now
            pass
        # Fall back: jump when the condition is non-zero (true), matching the
        # comparison case above.  Callers always pass the "jump when true"
        # target, so the sense must be consistent for every kind of condition.
        cond_addr, cond_type = self.gen_expr(cond_node, fn)
        fn.body.append(Instr("if", cond_addr, 0, target_label,
                             op_relop="!=", ty=cond_type or "i32"))

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
                # Don't initialize arrays to 0 - in C, arrays are not zero-initialized by default
                if not (isinstance(tag, str) and tag.startswith("array")):
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
                op = e[1]; lhs = e[2]; expr = e[3]
                # Handle array assignment (lhs is Index node)
                if lhs[0] == "Index":
                    base = lhs[1]
                    idx = lhs[2]
                    base_addr, base_ty = self.gen_expr(base, fn)
                    idx_addr, idx_ty = self.gen_expr(idx, fn)
                    val_addr, val_ty = self.gen_expr(expr, fn)
                    vtag = "i32"  # arrays are i32
                    if val_ty != vtag:
                        tmp = self.new_temp()
                        fn.var_types[tmp] = vtag
                        fn.body.append(Instr("cast", val_addr, None, tmp, ty=vtag))
                        val_addr = tmp
                    if op != "=":
                        # Compound assignment: a[i] op= value -> load, op, store
                        old = self.new_temp()
                        fn.var_types[old] = vtag
                        fn.body.append(Instr("load", base_addr, idx_addr, old, ty=vtag))
                        new = self.new_temp()
                        fn.var_types[new] = vtag
                        fn.body.append(Instr(op[:-1], old, val_addr, new, ty=vtag))
                        val_addr = new
                    fn.body.append(Instr("store", base_addr, idx_addr, val_addr, ty=vtag))
                else:
                    # Regular variable assignment
                    name = self._lvalue_name(lhs)
                    if name is None:
                        raise ValueError("unsupported assignment target %r" % (lhs,))
                    addr, t = self.gen_expr(expr, fn)
                    vtag = fn.var_types.get(name, "i32")
                    if t != vtag:
                        tmp = self.new_temp()
                        fn.var_types[tmp] = vtag
                        fn.body.append(Instr("cast", addr, None, tmp, ty=vtag))
                        addr = tmp
                    if op == "=":
                        fn.body.append(Instr("copy", addr, None, name, ty=vtag))
                    else:
                        bop = op[:-1]  # "+=" -> "+", etc.
                        tmp = self.new_temp()
                        fn.var_types[tmp] = vtag
                        fn.body.append(Instr(bop, name, addr, tmp, ty=vtag))
                        fn.body.append(Instr("copy", tmp, None, name, ty=vtag))
            elif e[0] == "IncDec":
                self.gen_incdec(e[3], e[1], e[2], fn)
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
            body = self.new_label()
            end = self.new_label()
            fn.body.append(Instr("label", start, None, None))
            # Jump to the body when the condition is true; otherwise exit.
            self._gen_cond_jump(node[1], body, fn)
            fn.body.append(Instr("goto", end, None, None))
            fn.body.append(Instr("label", body, None, None))
            self.gen_stmt(node[2], fn)
            fn.body.append(Instr("goto", start, None, None))
            fn.body.append(Instr("label", end, None, None))
        elif kind == "DoWhile":
            start = self.new_label()
            end = self.new_label()
            fn.body.append(Instr("label", start, None, None))
            body = self.gen_stmt(node[1], fn)
            cond = node[2]
            cond_addr, cond_type = self.gen_expr(node[2], fn)
            fn.body.append(Instr("ifFalse", cond_addr, end, None))
            fn.body.append(Instr("goto", start, None, None))
            fn.body.append(Instr("label", end, None, None))
        elif kind == "For":
            start = self.new_label()
            end = self.new_label()
            body = self.new_label()
            if node[1] is not None:
                self._gen_for_init(node[1], fn)
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
        elif node[0] == "VarDecls":
            for d in node[1]:
                self.gen_stmt(d, fn)
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
            elif op == "*":
                fn.body.append(Instr("load", addr, None, tmp, ty=t))
            elif op == "&":
                fn.body.append(Instr("addr", addr, None, tmp, ty=t))
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
            return self.gen_incdec(node[3], node[1], node[2], fn)
        if kind == "Index":
            # array subscript: base[index]
            base, base_ty = self.gen_expr(node[1], fn)
            idx, idx_ty = self.gen_expr(node[2], fn)
            tmp = self.new_temp()
            # Check if base is array or pointer
            if base_ty.startswith("array"):
                # array[index] -> load
                fn.var_types[tmp] = "i32"
                fn.body.append(Instr("load", base, idx, tmp, ty="i32"))
            else:
                # pointer arithmetic: base + index * sizeof(elem)
                # For now, treat as load
                fn.var_types[tmp] = "i32"
                fn.body.append(Instr("load", base, idx, tmp, ty="i32"))
            return tmp, "i32"
        if kind == "Arrow":
            # ptr->member: treated as (*ptr).member
            # For now, just load from the pointer
            base, base_ty = self.gen_expr(node[1], fn)
            member = node[2]
            tmp = self.new_temp()
            fn.var_types[tmp] = "i32"
            fn.body.append(Instr("load", base, member, tmp, ty="i32"))
            return tmp, "i32"
        raise ValueError("unknown expr %s" % kind)

def generate_c(tu):
    g = CGenerator()
    return g.generate(tu)