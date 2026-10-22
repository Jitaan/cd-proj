# ir/c_gen.py - C code generator (scalar, C1 + arrays/pointers)
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ir.tac import Instr
from ir.program import Program, Function
from frontend.c_types import Type, common_type, type_from_tag

INT = Type("scalar", bits=32, signed=True)


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

    def _elem_type(self, base_ty):
        """The element type of an indexable base (array or pointer)."""
        if base_ty is None:
            return INT
        if base_ty.kind == "array":
            return base_ty.elem
        if base_ty.kind == "pointer":
            return base_ty.pointee
        return INT

    def _cast_if_needed(self, addr, src_ty, dst_ty, fn):
        """Cast a value to `dst_ty` when both are scalars and differ."""
        if dst_ty is None or src_ty is None:
            return addr
        if src_ty == dst_ty:
            return addr
        if not (src_ty.is_scalar and dst_ty.is_scalar):
            return addr
        tmp = self.new_temp()
        fn.var_types[tmp] = dst_ty
        fn.body.append(Instr("cast", addr, None, tmp, ty=dst_ty))
        return tmp

    def _emit_arith(self, op, a, a_ty, b, b_ty, fn):
        """Emit `a op b`, scaling pointer arithmetic by the pointee size."""
        ad = a_ty.decay() if isinstance(a_ty, Type) else a_ty
        bd = b_ty.decay() if isinstance(b_ty, Type) else b_ty
        ap = ad is not None and ad.kind == "pointer"
        bp = bd is not None and bd.kind == "pointer"
        if op in ("+", "-") and (ap or bp):
            if ap and bp:
                # pointer difference: element count
                size = ad.pointee.size_bytes if ad.pointee else 1
                ty = Type("scalar", bits=64, signed=True)
                tmp = self.new_temp()
                fn.var_types[tmp] = ty
                fn.body.append(Instr("ptrdiff", a, b, tmp, args=(size,), ty=ty))
                return tmp, ty
            ptr_ty = ad if ap else bd
            size = ptr_ty.pointee.size_bytes if ptr_ty.pointee else 1
            if ap and op == "+":
                idx = b
            elif ap:  # ptr - int  -> ptr + (-int)
                idx = self.new_temp()
                fn.var_types[idx] = b_ty
                fn.body.append(Instr("neg", b, None, idx, ty=b_ty))
            else:  # int + ptr
                a, idx = b, a
            tmp = self.new_temp()
            fn.var_types[tmp] = ptr_ty
            fn.body.append(Instr("indexadd", a, idx, tmp, args=(size,), ty=ptr_ty))
            return tmp, ptr_ty
        ct = common_type(a_ty, b_ty)
        a = self._cast_if_needed(a, a_ty, ct, fn)
        b = self._cast_if_needed(b, b_ty, ct, fn)
        tmp = self.new_temp()
        fn.var_types[tmp] = ct
        fn.body.append(Instr(op, a, b, tmp, ty=ct))
        return tmp, ct

    def gen_addr(self, node, fn):
        """Return (address_operand, object_type) for an lvalue expression."""
        node = _skip_loc(node)
        kind = node[0]
        if kind == "Ident":
            name = node[1]
            ty = fn.var_types.get(name, INT)
            tmp = self.new_temp()
            fn.var_types[tmp] = Type.pointer(ty)
            fn.body.append(Instr("addr", name, None, tmp, ty=Type.pointer(ty)))
            return tmp, ty
        if kind == "Unary" and node[1] == "*":
            a, t = self.gen_expr(node[2], fn)
            ty = getattr(t, "pointee", None) or INT
            return a, ty
        if kind == "Index":
            base, base_ty = self.gen_expr(node[1], fn)
            idx, _ = self.gen_expr(node[2], fn)
            elem_ty = self._elem_type(base_ty)
            tmp = self.new_temp()
            fn.var_types[tmp] = Type.pointer(elem_ty)
            fn.body.append(Instr("indexadd", base, idx, tmp,
                                 args=(elem_ty.size_bytes,), ty=Type.pointer(elem_ty)))
            return tmp, elem_ty
        if kind == "Member":
            base_addr, _ = self.gen_addr(node[1], fn)
            mty = node[4]
            tmp = self.new_temp()
            fn.var_types[tmp] = Type.pointer(mty)
            fn.body.append(Instr("addoff", base_addr, node[3], tmp, ty=Type.pointer(mty)))
            return tmp, mty
        if kind == "Arrow":
            ptr, _pt = self.gen_expr(node[1], fn)
            mty = node[4]
            tmp = self.new_temp()
            fn.var_types[tmp] = Type.pointer(mty)
            fn.body.append(Instr("addoff", ptr, node[3], tmp, ty=Type.pointer(mty)))
            return tmp, mty
        raise ValueError("not an lvalue: %r" % (node,))

    def _load_at(self, addr, ty, fn):
        """Load the object of type `ty` stored at address `addr`."""
        tmp = self.new_temp()
        fn.var_types[tmp] = ty
        fn.body.append(Instr("loadoff", addr, 0, tmp, ty=ty))
        return tmp

    def gen_incdec(self, base, op, prefix, fn):
        """Generate `++`/`--` for any lvalue shape.

        Returns (address, type) of the resulting value: the new value for the
        prefix form, the old value for the postfix form.
        """
        node = base
        if isinstance(node, str):
            node = ("Ident", node)
        node = _skip_loc(node)
        kind = node[0] if isinstance(node, tuple) and node else None
        if kind == "Ident":
            name = node[1]
            ty = fn.var_types.get(name, INT)
            get = lambda: (name, ty)
            def put(v):
                fn.body.append(Instr("copy", v, None, name, ty=ty))
        elif kind == "Unary" and node[1] == "*":
            ptr, pt = self.gen_expr(node[2], fn)
            ty = getattr(pt, "pointee", None) or INT
            get = lambda: (self._load_at(ptr, ty, fn), ty)
            def put(v):
                fn.body.append(Instr("store", ptr, 0, v, ty=ty))
        elif kind == "Index":
            base_op, bty = self.gen_expr(node[1], fn)
            idx, _ = self.gen_expr(node[2], fn)
            ty = self._elem_type(bty)
            def get():
                t = self.new_temp()
                fn.var_types[t] = ty
                fn.body.append(Instr("load", base_op, idx, t, ty=ty))
                return t, ty
            def put(v):
                fn.body.append(Instr("store", base_op, idx, v, ty=ty))
        elif kind in ("Member", "Arrow"):
            addr, ty = self.gen_addr(node, fn)
            get = lambda: (self._load_at(addr, ty, fn), ty)
            def put(v):
                fn.body.append(Instr("storeoff", addr, 0, v, ty=ty))
        else:
            return self.gen_expr(node, fn)

        old, oty = get()
        if not prefix:
            res = self.new_temp()
            fn.var_types[res] = oty
            fn.body.append(Instr("copy", old, None, res, ty=oty))
        else:
            res = None
        new = self.new_temp()
        fn.var_types[new] = oty
        if oty is not None and oty.kind == "pointer":
            size = oty.pointee.size_bytes if oty.pointee else 1
            delta = 1 if op == "++" else -1
            fn.body.append(Instr("indexadd", old, delta, new, args=(size,), ty=oty))
        else:
            fn.body.append(Instr("+" if op == "++" else "-", old, 1, new, ty=oty))
        put(new)
        return (new if prefix else res), oty

    def _gen_assign(self, lhs, rhs, op, fn):
        """Generate an assignment to any lvalue shape."""
        if isinstance(lhs, str):
            lhs = ("Ident", lhs)
        lhs = _skip_loc(lhs)
        kind = lhs[0] if isinstance(lhs, tuple) and lhs else None

        if kind == "Ident":
            name = lhs[1]
            ty = fn.var_types.get(name, INT)
            if ty.is_record and op == "=":
                dst, _ = self.gen_addr(lhs, fn)
                src, _ = self.gen_addr(rhs, fn)
                fn.body.append(Instr("blkcopy", dst, src, None,
                                     args=(ty.size_bytes,), ty=ty))
                return
            val, vty = self.gen_expr(rhs, fn)
            if op == "=":
                val = self._cast_if_needed(val, vty, ty, fn)
                fn.body.append(Instr("copy", val, None, name, ty=ty))
            else:
                res, _ = self._emit_arith(op[:-1], name, ty, val, vty, fn)
                fn.body.append(Instr("copy", res, None, name, ty=ty))
            return

        if kind == "Index":
            base, base_ty = self.gen_expr(lhs[1], fn)
            idx, _ = self.gen_expr(lhs[2], fn)
            ty = self._elem_type(base_ty)
            if ty.is_record and op == "=":
                dst = self.new_temp()
                fn.var_types[dst] = Type.pointer(ty)
                fn.body.append(Instr("indexadd", base, idx, dst,
                                     args=(ty.size_bytes,), ty=Type.pointer(ty)))
                src, _ = self.gen_addr(rhs, fn)
                fn.body.append(Instr("blkcopy", dst, src, None,
                                     args=(ty.size_bytes,), ty=ty))
                return
            val, vty = self.gen_expr(rhs, fn)
            if op == "=":
                val = self._cast_if_needed(val, vty, ty, fn)
                fn.body.append(Instr("store", base, idx, val, ty=ty))
            else:
                old = self.new_temp()
                fn.var_types[old] = ty
                fn.body.append(Instr("load", base, idx, old, ty=ty))
                res, _ = self._emit_arith(op[:-1], old, ty, val, vty, fn)
                fn.body.append(Instr("store", base, idx, res, ty=ty))
            return

        if kind == "Unary" and lhs[1] == "*":
            ptr, pt = self.gen_expr(lhs[2], fn)
            ty = getattr(pt, "pointee", None) or INT
            if ty.is_record and op == "=":
                src, _ = self.gen_addr(rhs, fn)
                fn.body.append(Instr("blkcopy", ptr, src, None,
                                     args=(ty.size_bytes,), ty=ty))
                return
            val, vty = self.gen_expr(rhs, fn)
            if op == "=":
                val = self._cast_if_needed(val, vty, ty, fn)
                fn.body.append(Instr("store", ptr, 0, val, ty=ty))
            else:
                old = self.new_temp()
                fn.var_types[old] = ty
                fn.body.append(Instr("load", ptr, 0, old, ty=ty))
                res, _ = self._emit_arith(op[:-1], old, ty, val, vty, fn)
                fn.body.append(Instr("store", ptr, 0, res, ty=ty))
            return

        if kind in ("Member", "Arrow"):
            addr, ty = self.gen_addr(lhs, fn)
            if ty.is_record and op == "=":
                src, _ = self.gen_addr(rhs, fn)
                fn.body.append(Instr("blkcopy", addr, src, None,
                                     args=(ty.size_bytes,), ty=ty))
                return
            val, vty = self.gen_expr(rhs, fn)
            if op == "=":
                val = self._cast_if_needed(val, vty, ty, fn)
                fn.body.append(Instr("storeoff", addr, 0, val, ty=ty))
            else:
                old = self._load_at(addr, ty, fn)
                res, _ = self._emit_arith(op[:-1], old, ty, val, vty, fn)
                fn.body.append(Instr("storeoff", addr, 0, res, ty=ty))
            return

        raise ValueError("unsupported assignment target %r" % (lhs,))

    def generate(self, tu):
        prog = Program()
        for decl in tu[1]:
            decl = _skip_loc(decl)
            if decl[0] == "FuncDef":
                fn = self.gen_func(decl)
                prog.functions[fn.name] = fn
            elif decl[0] == "GlobalVar":
                ty = decl[1]
                init = decl[3]
                val = 0
                if init is not None:
                    if init[0] == "IntLit":
                        val = init[1]
                    elif init[0] == "InitList":
                        val = [self._const_value(item) for item in init[1]]
                prog.globals[decl[2]] = (ty, val)
        if "main" not in prog.functions:
            # wrap? assume present
            pass
        return prog

    def gen_func(self, node):
        node = _skip_loc(node)
        ret_ty = node[1]
        name = node[2]
        params = node[3]
        body_node = node[4]
        fn = Function(name=name, params=[], ret_ty=ret_ty, body=[], var_types={})
        self.var_types = fn.var_types
        # params
        for p in params:
            p = _skip_loc(p)
            uniq, pty = p[0], p[1]
            fn.params.append((uniq, pty))
            fn.var_types[uniq] = pty
        # body
        self.gen_block(body_node, fn)
        # implicit return, unless the body already ends by returning
        if ret_ty is not None and not ret_ty.is_void:
            if not fn.body or fn.body[-1].op != "return":
                fn.body.append(Instr("return", 0, None, None, ty=ret_ty))
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
            ct = common_type(left_type, right_type)
            left_addr = self._cast_if_needed(left_addr, left_type, ct, fn)
            right_addr = self._cast_if_needed(right_addr, right_type, ct, fn)
            # Generate proper conditional jump: if left op right goto target
            fn.body.append(Instr("if", left_addr, right_addr, target_label, op_relop=op, ty=ct))
            return
        elif cond_node[0] == "BinOp" and cond_node[1] in ("&&", "||"):
            # Logical ops - evaluate the whole expression for now
            pass
        # Fall back: jump when the condition is non-zero (true), matching the
        # comparison case above.  Callers always pass the "jump when true"
        # target, so the sense must be consistent for every kind of condition.
        cond_addr, cond_type = self.gen_expr(cond_node, fn)
        fn.body.append(Instr("if", cond_addr, 0, target_label,
                             op_relop="!=", ty=cond_type or INT))

    def gen_stmt(self, node, fn):
        node = _skip_loc(node)
        kind = node[0]
        if kind == "VarDecl":
            ty = node[1]
            name = node[2]
            fn.var_types[name] = ty
            init = node[3]
            if init is None:
                # Aggregates (arrays/records) are not zero-initialized by default.
                if not ty.is_aggregate:
                    fn.body.append(Instr("copy", 0, None, name, ty=ty))
            elif init[0] == "InitList":
                self._gen_init_list(init[1], name, ty, fn)
            elif ty.is_record:
                dst, _ = self.gen_addr(("Ident", name), fn)
                src, _ = self.gen_addr(init, fn)
                fn.body.append(Instr("blkcopy", dst, src, None,
                                     args=(ty.size_bytes,), ty=ty))
            else:
                addr, t = self.gen_expr(init, fn)
                addr = self._cast_if_needed(addr, t, ty, fn)
                fn.body.append(Instr("copy", addr, None, name, ty=ty))
        elif kind == "ExprStmt":
            e = _skip_loc(node[1])
            if e[0] == "Assign":
                self._gen_assign(e[2], e[3], e[1], fn)
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
                # For loops: jump to body when condition is TRUE, else jump to end
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
            fn.var_types[tmp] = INT
            fn.body.append(Instr("call", "printf", len(args) + 1, tmp, ty=INT))
        elif kind == "Putchar":
            addr, t = self.gen_expr(node[1], fn)
            fn.body.append(Instr("out_val", addr, "c", None, ty=INT))
        elif kind == "Empty":
            pass
        else:
            try:
                addr, t = self.gen_expr(node, fn)
            except Exception:
                pass

    def _const_value(self, node):
        """The constant value of an initialiser expression, or 0."""
        node = _skip_loc(node)
        if node[0] == "IntLit":
            return node[1]
        if node[0] == "CharLit":
            return node[1]
        return 0

    def _gen_init_list(self, items, name, ty, fn):
        """Initialise an aggregate from a brace-enclosed list of values."""
        if ty.kind == "record":
            base = self.new_temp()
            fn.var_types[base] = Type.pointer(ty)
            fn.body.append(Instr("addr", name, None, base, ty=Type.pointer(ty)))
            for i, item in enumerate(items):
                if i >= len(ty.members):
                    break
                m = ty.members[i]
                addr, t = self.gen_expr(item, fn)
                addr = self._cast_if_needed(addr, t, m.type, fn)
                fn.body.append(Instr("storeoff", base, m.offset, addr, ty=m.type))
            return
        elem_ty = ty.elem if ty.kind == "array" else INT
        for i, item in enumerate(items):
            addr, t = self.gen_expr(item, fn)
            addr = self._cast_if_needed(addr, t, elem_ty, fn)
            fn.body.append(Instr("store", name, i, addr, ty=elem_ty))

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
            return node[1], type_from_tag(node[2])
        if kind == "CharLit":
            return node[1], INT
        if kind == "Ident":
            name = node[1]
            return name, fn.var_types.get(name, INT)
        if kind == "Unary":
            op = node[1]
            if op == "&":
                addr, ty = self.gen_addr(node[2], fn)
                return addr, Type.pointer(ty)
            addr, t = self.gen_expr(node[2], fn)
            if op == "*":
                elem_ty = getattr(t, "pointee", None) or t
                if elem_ty.is_aggregate:
                    return addr, elem_ty
                tmp = self.new_temp()
                fn.var_types[tmp] = elem_ty
                fn.body.append(Instr("load", addr, 0, tmp, ty=elem_ty))
                return tmp, elem_ty
            tmp = self.new_temp()
            fn.var_types[tmp] = t
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
            return self._emit_arith(op, la, lt, ra, rt, fn)
        if kind == "Cast":
            ty = node[1]
            addr, t = self.gen_expr(node[2], fn)
            tmp = self.new_temp()
            fn.var_types[tmp] = ty
            fn.body.append(Instr("cast", addr, None, tmp, ty=ty))
            return tmp, ty
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
            fn.var_types[tmp] = INT
            fn.body.append(Instr("call", node[1], len(arg_ops), tmp, ty=INT))
            return tmp, INT
        if kind == "IncDec":
            return self.gen_incdec(node[3], node[1], node[2], fn)
        if kind == "Index":
            # array/pointer subscript: base[index]
            base, base_ty = self.gen_expr(node[1], fn)
            idx, idx_ty = self.gen_expr(node[2], fn)
            elem_ty = self._elem_type(base_ty)
            if elem_ty.is_aggregate:
                tmp = self.new_temp()
                fn.var_types[tmp] = Type.pointer(elem_ty)
                fn.body.append(Instr("indexadd", base, idx, tmp,
                                     args=(elem_ty.size_bytes,), ty=Type.pointer(elem_ty)))
                return tmp, elem_ty
            tmp = self.new_temp()
            fn.var_types[tmp] = elem_ty
            fn.body.append(Instr("load", base, idx, tmp, ty=elem_ty))
            return tmp, elem_ty
        if kind in ("Arrow", "Member"):
            addr, ty = self.gen_addr(node, fn)
            if ty.is_aggregate:
                return addr, ty
            tmp = self._load_at(addr, ty, fn)
            return tmp, ty
        raise ValueError("unknown expr %s" % kind)


def generate_c(tu):
    g = CGenerator()
    return g.generate(tu)
