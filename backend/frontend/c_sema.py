# frontend/c_sema.py - semantic analysis (scopes, types, lvalues)
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from frontend.c_types import (Type, common_type, VOID, type_from_tag,
                              layout_record, member_of)
from frontend.errors import SemanticError, UnsupportedFeatureError

__all__ = ["SemanticError", "UnsupportedFeatureError", "Sema", "analyze"]


def _get_loc(node):
    """Extract (line, col) from AST node. Returns (0, 0) if not found."""
    if isinstance(node, tuple) and len(node) > 0:
        # Check last element if it's a location tuple
        last = node[-1]
        if isinstance(last, tuple) and len(last) == 2 and all(isinstance(x, int) for x in last):
            return last
    return (0, 0)


def _strip_loc(node):
    """Remove a trailing (line, col) tuple from a node, if present."""
    if isinstance(node, tuple) and len(node) > 0:
        last = node[-1]
        if isinstance(last, tuple) and len(last) == 2 and all(isinstance(x, int) for x in last):
            return node[:-1]
    return node


def _is_lvalue(node):
    """True for an expression that designates storage (after annotation)."""
    if not isinstance(node, tuple) or not node:
        return False
    kind = node[0]
    if kind in ("Ident", "Index", "Member", "Arrow"):
        return True
    return kind == "Unary" and node[1] == "*"


class Sema:
    def __init__(self):
        self.scopes = [{}]  # list of dict name->unique
        self.functions = {}  # name -> (ret_ty, params)
        self.globals = {}
        self.unique_counter = {}
        self.loop_depth = 0
        self.current_func_ret = None
        self.warnings = []

    def new_unique(self, name):
        # if name not used in any scope yet, keep; else suffix
        if name not in self.unique_counter:
            self.unique_counter[name] = 0
            return name
        self.unique_counter[name] += 1
        return "%s.%d" % (name, self.unique_counter[name])

    def enter_scope(self):
        self.scopes.append({})

    def exit_scope(self):
        self.scopes.pop()

    def declare(self, name, ty, line, col, is_global=False):
        # check redeclaration in current scope
        if name in self.scopes[-1]:
            raise SemanticError(line, col, "redeclaration of %s" % name)
        uniq = self.new_unique(name)
        self.scopes[-1][name] = (uniq, ty)
        if is_global:
            self.globals[uniq] = (ty, 0)
        return uniq

    def lookup(self, name, line, col):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise SemanticError(line, col, "undeclared identifier %s" % name)

    def _complete_type(self, ty, init, loc):
        """Finish an incomplete array type from its initialiser."""
        if ty.kind != "array":
            raise SemanticError(loc[0], loc[1], "invalid initializer")
        if ty.count is None:
            return Type.array(ty.elem, len(init[1]))
        if len(init[1]) > ty.count:
            raise SemanticError(loc[0], loc[1], "too many initializers")
        return ty

    def annotate_expr(self, node):
        kind = node[0]
        loc = _get_loc(node)
        if kind == "IntLit":
            return node, type_from_tag(node[2])
        if kind == "CharLit":
            return node, Type("scalar", bits=32, signed=True)
        if kind == "Ident":
            uniq, ty = self.lookup(node[1], loc[0], loc[1])
            # rewrite node to unique
            new = ("Ident", uniq)
            return new, ty
        if kind == "StringLit":
            return node, None
        if kind == "Cast":
            ty = node[1]
            e, et = self.annotate_expr(node[2])
            return ("Cast", ty, e), ty
        if kind == "Unary":
            e, et = self.annotate_expr(node[2])
            op = node[1]
            if op == "!":
                return ("Unary", op, e), Type("scalar", bits=32, signed=True)
            if op == "*":
                # dereference: the operand may be a pointer or an array
                if et is not None and et.kind == "pointer":
                    return ("Unary", op, e), et.pointee
                if et is not None and et.kind == "array":
                    return ("Unary", op, e), et.elem
                raise SemanticError(loc[0], loc[1], "dereference of non-pointer")
            if op == "&":
                # address-of: only valid on an lvalue.  &arr is a pointer to the
                # whole array; &x a pointer to x (or to a dereferenced/indexed
                # or member lvalue).
                if et is not None and _is_lvalue(e):
                    return ("Unary", op, e), Type.pointer(et)
                raise SemanticError(loc[0], loc[1], "address-of non-lvalue")
            return ("Unary", op, e), et
        if kind == "IncDec":
            # prefix/postfix: resolve the lvalue name in the current scope
            base = node[3]
            if isinstance(base, str):
                uniq, ty = self.lookup(base, loc[0], loc[1])
                return ("IncDec", node[1], node[2], uniq), ty
            b, bt = self.annotate_expr(_strip_loc(base))
            return ("IncDec", node[1], node[2], b), bt
        if kind == "Assign":
            op = node[1]
            lhs = node[2]
            if isinstance(lhs, str):
                uniq, lty = self.lookup(lhs, loc[0], loc[1])
                lhs = uniq
            elif isinstance(lhs, tuple):
                lhs, lty = self.annotate_expr(_strip_loc(lhs))
            else:
                lty = Type("scalar", bits=32, signed=True)
            rhs, rty = self.annotate_expr(node[3])
            return ("Assign", op, lhs, rhs), (rty or lty or Type("scalar", bits=32, signed=True))
        if kind == "BinOp":
            l, lt = self.annotate_expr(node[2])
            r, rt = self.annotate_expr(node[3])
            op = node[1]
            if lt is None or rt is None:
                return ("BinOp", op, l, r), Type("scalar", bits=32, signed=True)
            if op in ("&&", "||"):
                return ("BinOp", op, l, r), Type("scalar", bits=32, signed=True)
            if op in ("<<", ">>"):
                return ("BinOp", op, l, r), lt
            if op in ("<", ">", "<=", ">=", "==", "!="):
                return ("BinOp", op, l, r), Type("scalar", bits=32, signed=True)
            ld = lt.decay()
            rd = rt.decay()
            if ld.kind == "pointer" or rd.kind == "pointer":
                if op in ("+", "-"):
                    if ld.kind == "pointer" and rd.kind == "pointer":
                        if op == "-":
                            # pointer difference: a signed element count
                            return ("BinOp", op, l, r), Type("scalar", bits=64, signed=True)
                        raise SemanticError(loc[0], loc[1], "cannot add two pointers")
                    ptr = ld if ld.kind == "pointer" else rd
                    other = rd if ld.kind == "pointer" else ld
                    if other.kind != "scalar":
                        raise SemanticError(loc[0], loc[1], "invalid pointer arithmetic")
                    if ptr.pointee is None or ptr.pointee.kind == "void":
                        raise SemanticError(loc[0], loc[1], "arithmetic on void pointer")
                    return ("BinOp", op, l, r), ptr
                raise SemanticError(loc[0], loc[1], "invalid operator %s on pointer" % op)
            ct = common_type(lt, rt)
            return ("BinOp", op, l, r), ct
        if kind == "Ternary":
            c, ct = self.annotate_expr(node[1])
            t, tt = self.annotate_expr(node[2])
            f, ft = self.annotate_expr(node[3])
            ct2 = tt if tt else ft
            if tt and ft:
                ct2 = common_type(tt, ft)
            return ("Ternary", c, t, f), ct2
        if kind == "Call":
            name = node[1]
            args = []
            for a in node[2]:
                an, at = self.annotate_expr(a)
                args.append(an)
            if name in self.functions:
                ret = self.functions[name][0]
            else:
                # builtin (printf, putchar, ...)
                ret = Type("scalar", bits=32, signed=True)
            return ("Call", name, args), ret
        if kind == "Index":
            # array subscript: base[index]
            base, bt = self.annotate_expr(node[1])
            idx, it = self.annotate_expr(node[2])
            if bt is not None and bt.kind == "array":
                return ("Index", base, idx), bt.elem
            if bt is not None and bt.kind == "pointer":
                return ("Index", base, idx), bt.pointee
            raise SemanticError(loc[0], loc[1], "subscripted value is not an array or pointer")
        if kind == "Arrow":
            # ptr->member : base must be a pointer to a record
            base, bt = self.annotate_expr(node[1])
            if bt is None or bt.kind != "pointer" or bt.pointee is None \
                    or bt.pointee.kind != "record":
                raise SemanticError(loc[0], loc[1], "arrow on non-pointer-to-record")
            m = member_of(bt.pointee, node[2], loc[0], loc[1])
            return ("Arrow", base, m.name, m.offset, m.type), m.type
        if kind == "Member":
            # obj.member : base must be a record
            base, bt = self.annotate_expr(node[1])
            if bt is None or bt.kind != "record":
                raise SemanticError(loc[0], loc[1], "member access on non-record type")
            m = member_of(bt, node[2], loc[0], loc[1])
            return ("Member", base, m.name, m.offset, m.type), m.type
        if kind == "UnaryAssign":
            # `*p = v` / `&x = v` statement forms from parse_simple_stmt
            lhs, lty = self.annotate_expr(_strip_loc(node[2]))
            rhs, rty = self.annotate_expr(node[4])
            return ("Assign", node[3], lhs, rhs), (rty or lty or Type("scalar", bits=32, signed=True))
        if kind == "UnaryIncDec":
            base, bt = self.annotate_expr(_strip_loc(node[3]))
            return ("IncDec", node[1], node[2], base), bt
        return node, Type("scalar", bits=32, signed=True)

    def analyze_decl(self, node, is_global=False):
        loc = _get_loc(node)
        # node[1] is the declared type, already a Type built by the parser.
        ty = node[1]
        name = node[2]
        uniq = self.declare(name, ty, loc[0], loc[1], is_global=is_global)
        init = node[3]
        if init is not None and init[0] == "InitList":
            if ty.kind == "array":
                ty = self._complete_type(ty, init, loc)
                self.scopes[-1][name] = (uniq, ty)
            items = [self.annotate_expr(e)[0] for e in init[1]]
            return ("VarDecl", ty, uniq, ("InitList", items))
        if init is not None:
            ie, it = self.annotate_expr(init)
            return ("VarDecl", ty, uniq, ie)
        if ty.kind == "array" and ty.count is None:
            # an incomplete array with no initialiser: give it one element
            ty = Type.array(ty.elem, 1)
            self.scopes[-1][name] = (uniq, ty)
        return ("VarDecl", ty, uniq, None)

    def analyze_stmt(self, node):
        kind = node[0]
        loc = _get_loc(node)
        if kind == "VarDecl":
            return self.analyze_decl(node)
        if kind == "Block":
            self.enter_scope()
            stmts = [self.analyze_stmt(s) for s in node[1]]
            self.exit_scope()
            return ("Block", stmts)
        if kind == "If":
            c, ct = self.annotate_expr(node[1])
            t = self.analyze_stmt(node[2])
            e = self.analyze_stmt(node[3]) if node[3] else None
            return ("If", c, t, e, loc)
        if kind == "While":
            self.loop_depth += 1
            c, ct = self.annotate_expr(node[1])
            b = self.analyze_stmt(node[2])
            self.loop_depth -= 1
            return ("While", c, b, loc)
        if kind == "DoWhile":
            self.loop_depth += 1
            b = self.analyze_stmt(node[1])
            c, ct = self.annotate_expr(node[2])
            self.loop_depth -= 1
            return ("DoWhile", b, c, loc)
        if kind == "For":
            self.enter_scope()
            init = None
            if node[1] is not None:
                if node[1][0] == "VarDecl":
                    init = self.analyze_decl(node[1])
                elif node[1][0] == "VarDecls":
                    # for (int i = 0, j = 0; ...)
                    init = ("VarDecls", [self.analyze_decl(d) for d in node[1][1]])
                else:
                    # simple stmt expr (assignment / inc-dec) in the for-init
                    init, _ = self.annotate_expr(_strip_loc(node[1]))
            cond = None
            if node[2] is not None:
                cond, _ = self.annotate_expr(node[2])
            step = node[3]
            if step is not None:
                step, _ = self.annotate_expr(_strip_loc(step))
            self.loop_depth += 1
            body = self.analyze_stmt(node[4])
            self.loop_depth -= 1
            self.exit_scope()
            return ("For", init, cond, step, body, loc)
        if kind == "Return":
            e = None
            if node[1] is not None:
                e, _ = self.annotate_expr(node[1])
            return ("Return", e, loc)
        if kind == "ExprStmt":
            e, _ = self.annotate_expr(node[1])
            return ("ExprStmt", e, loc)
        if kind == "Break":
            if self.loop_depth == 0:
                raise SemanticError(loc[0], loc[1], "break outside loop")
            return node
        if kind == "Continue":
            if self.loop_depth == 0:
                raise SemanticError(loc[0], loc[1], "continue outside loop")
            return node
        if kind in ("Empty",):
            return node
        if kind == "Printf":
            args = []
            for a in node[2]:
                ae, _ = self.annotate_expr(a)
                args.append(ae)
            return ("Printf", node[1], args, loc)
        if kind == "Scanf":
            return node
        if kind == "Putchar":
            e, _ = self.annotate_expr(node[1])
            return ("Putchar", e, loc)
        return node

    def analyze_func(self, node):
        ret_ty = node[1]
        name = node[2]
        loc = _get_loc(node)
        if name in self.functions:
            raise SemanticError(loc[0], loc[1], "redefinition of %s" % name)
        self.current_func_ret = ret_ty
        self.enter_scope()
        params = []
        for p in node[3]:
            pty = p[0]
            uniq = self.declare(p[1], pty, p[2][0], p[2][1])
            params.append((uniq, pty))
        self.functions[name] = (ret_ty, params)
        body = self.analyze_stmt(node[4])
        self.exit_scope()
        self.current_func_ret = None
        return ("FuncDef", ret_ty, name, params, body, loc)

    def analyze_tu(self, node):
        new_decls = []
        for d in node[1]:
            if d[0] == "FuncDef":
                new_decls.append(self.analyze_func(d))
            elif d[0] == "GlobalVar":
                ty = d[1]
                name = d[2]
                loc = _get_loc(d)
                init = d[3]
                if init is not None and init[0] == "InitList":
                    if ty.kind == "array":
                        ty = self._complete_type(ty, init, loc)
                    items = [self.annotate_expr(e)[0] for e in init[1]]
                    init = ("InitList", items)
                elif init is not None:
                    init, _ = self.annotate_expr(init)
                elif ty.kind == "array" and ty.count is None:
                    ty = Type.array(ty.elem, 1)
                uniq = self.declare(name, ty, loc[0], loc[1], is_global=True)
                new_decls.append(("GlobalVar", ty, uniq, init, loc))
            else:
                new_decls.append(d)
        # require main
        if "main" not in self.functions:
            raise SemanticError(0, 0, "missing main")
        return ("TU", new_decls)


def analyze(src_ast):
    sema = Sema()
    return sema.analyze_tu(src_ast), sema
