# frontend/c_sema.py - semantic analysis (C1, scalar + main + arrays/pointers)
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from c_types import parse_type_specifiers, common_type, CType, VOID, is_array_type, is_pointer_type, get_array_info, get_pointer_base, type_to_tag

class SemanticError(Exception):
    def __init__(self, line, col, msg):
        self.line = line; self.col = col; self.msg = msg
        super().__init__("%d:%d: %s" % (line, col, msg))

class UnsupportedFeatureError(Exception):
    def __init__(self, feature, line, col):
        self.feature = feature; self.line = line; self.col = col
        super().__init__("%d:%d: unsupported: %s" % (line, col, feature))

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

    def annotate_expr(self, node):
        kind = node[0]
        loc = _get_loc(node)
        if kind == "IntLit":
            ty = _tag_to_ctype(node[2])
            return node, ty
        if kind == "CharLit":
            return node, CType(32, True)
        if kind == "Ident":
            uniq, ty = self.lookup(node[1], loc[0], loc[1])
            # rewrite node to unique
            new = ("Ident", uniq)
            return new, ty
        if kind == "StringLit":
            return node, None
        if kind == "Cast":
            specs = node[1][1]
            ty = parse_type_specifiers(specs)
            e, et = self.annotate_expr(node[2])
            return ("Cast", ty, e), ty
        if kind == "Unary":
            e, et = self.annotate_expr(node[2])
            op = node[1]
            if op == "!":
                return ("Unary", op, e), CType(32, True)
            if op == "*":
                # dereference
                if is_pointer_type(et):
                    base_ty = get_pointer_base(et)
                    return ("Unary", op, e), base_ty
                raise SemanticError(loc[0], loc[1], "dereference of non-pointer")
            if op == "&":
                # address-of
                if is_array_type(et):
                    # array decays to pointer
                    base_ty = get_array_info(et)[1]
                    return ("Unary", op, e), ("Pointer", base_ty)
                if isinstance(et, CType):
                    return ("Unary", op, e), ("Pointer", et)
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
                lty = CType(32, True)
            rhs, rty = self.annotate_expr(node[3])
            return ("Assign", op, lhs, rhs), (rty or lty or CType(32, True))
        if kind == "BinOp":
            l, lt = self.annotate_expr(node[2])
            r, rt = self.annotate_expr(node[3])
            if lt is None or rt is None:
                return ("BinOp", node[1], l, r), CType(32, True)
            if node[1] in ("&&", "||"):
                return ("BinOp", node[1], l, r), CType(32, True)
            if node[1] in ("<<", ">>"):
                return ("BinOp", node[1], l, r), lt
            if node[1] in ("<", ">", "<=", ">=", "==", "!="):
                return ("BinOp", node[1], l, r), CType(32, True)
            ct = common_type(lt, rt)
            return ("BinOp", node[1], l, r), ct
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
            if name not in self.functions:
                # builtin
                pass
            args = []
            argtypes = []
            for a in node[2]:
                an, at = self.annotate_expr(a)
                args.append(an)
                argtypes.append(at)
            return ("Call", name, args), CType(32, True)
        if kind == "Index":
            # array subscript: base[index]
            base, bt = self.annotate_expr(node[1])
            idx, it = self.annotate_expr(node[2])
            if is_array_type(bt):
                elem_ty = get_array_info(bt)[1]
                return ("Index", base, idx), elem_ty
            if is_pointer_type(bt):
                # pointer arithmetic
                base_ty = get_pointer_base(bt)
                return ("Index", base, idx), base_ty
            raise SemanticError(loc[0], loc[1], "subscripted value is not an array or pointer")
        if kind == "Arrow":
            # ptr->member
            base, bt = self.annotate_expr(node[1])
            member = node[2]
            # For now, just treat as base type
            if is_pointer_type(bt):
                base_ty = get_pointer_base(bt)
                return ("Arrow", base, member), base_ty
            raise SemanticError(loc[0], loc[1], "arrow on non-pointer")
        return node, CType(32, True)

    def analyze_decl(self, node, is_global=False):
        loc = _get_loc(node)
        # node[1] is the type from parser, which can be:
        # - ("Type", specs) for basic types
        # - ("Array", size, base_type) for arrays
        # - ("Pointer", base_type) for pointers
        # We use it directly as the type
        ty = node[1]
        name = node[2]
        uniq = self.declare(name, ty, loc[0], loc[1], is_global=is_global)
        init = node[3]
        if init is not None:
            ie, it = self.annotate_expr(init)
            node = ("VarDecl", ty, uniq, ie)
        else:
            node = ("VarDecl", ty, uniq, None)
        return node

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
        ty = node[1]
        ret_ty = parse_type_specifiers(ty[1])
        name = node[2]
        loc = _get_loc(node)
        if name in self.functions:
            raise SemanticError(loc[0], loc[1], "redefinition of %s" % name)
        self.functions[name] = (ret_ty, node[3])
        # params
        self.current_func_ret = ret_ty
        self.enter_scope()
        params = []
        for p in node[3]:
            pty = parse_type_specifiers(p[0][1])
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
                ty = parse_type_specifiers(d[1][1])
                name = d[2]
                loc = _get_loc(d)
                uniq = self.declare(name, ty, loc[0], loc[1], is_global=True)
                init = d[3]
                if init is not None:
                    ie, _ = self.annotate_expr(init)
                    new_decls.append(("GlobalVar", ty, uniq, ie, loc))
                else:
                    new_decls.append(("GlobalVar", ty, uniq, None, loc))
            else:
                new_decls.append(d)
        # require main
        if "main" not in self.functions:
            raise SemanticError(0, 0, "missing main")
        return ("TU", new_decls)

def _tag_to_ctype(tag):
    from c_types import CType
    if tag.startswith("i"):
        return CType(int(tag[1:]), True)
    if tag.startswith("u"):
        return CType(int(tag[1:]), False)
    return CType(32, True)

def analyze(src_ast):
    sema = Sema()
    return sema.analyze_tu(src_ast), sema