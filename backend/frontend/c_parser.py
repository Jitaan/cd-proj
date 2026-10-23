# frontend/c_parser.py - C parser (C1, scalar + main + arrays/pointers)
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from c_lexer import lex_c, CToken, CLexError
from preprocess import PreprocessError
from frontend.c_types import Type, parse_type_specifiers, layout_record

# Keywords that can begin a type specifier.
_TYPE_START = ("const", "char", "short", "int", "long", "unsigned", "signed",
               "void", "struct", "union")
_SCALAR_SPECS = ("const", "char", "short", "int", "long", "unsigned", "signed", "void")

class CParseError(Exception):
    def __init__(self, line, col, msg):
        self.line = line; self.col = col; self.msg = msg
        super().__init__("%d:%d: %s" % (line, col, msg))

class Parser:
    def __init__(self, toks):
        self.toks = toks; self.i = 0
        self.record_tags = {}  # tag name -> Type (record)
    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else self.toks[-1]
    def advance(self):
        t = self.peek(); self.i += 1; return t
    def expect(self, kind, value=None):
        t = self.peek()
        if t.kind != kind or (value is not None and t.value != value):
            raise CParseError(t.line, t.col, "expected %s" % (value or kind))
        return self.advance()

    def _loc(self, tok):
        return (tok.line, tok.col)

    def parse_translation_unit(self):
        decls = []
        while self.peek().kind != "EOF":
            if self.peek().kind == "KEYWORD" and self.peek().value in ("enum","typedef","switch","goto"):
                raise CParseError(self.peek().line, self.peek().col, "unsupported feature: %s" % self.peek().value)
            # function or one or more global variables
            d = self.parse_top_level()
            if isinstance(d, list):
                decls.extend(d)
            else:
                decls.append(d)
        return ("TU", decls)

    def parse_top_level(self):
        # type + name
        ty = self.parse_type()
        # a bare struct/union definition with no declarator: `struct P { ... };`
        if self.peek().kind == "OP" and self.peek().value == ";":
            self.advance()
            return []
        is_func = (self.peek().kind == "IDENT"
                   and self.i + 1 < len(self.toks)
                   and self.toks[self.i + 1].kind == "OP"
                   and self.toks[self.i + 1].value == "(")
        if is_func:
            name_tok = self.advance()
            # function
            self.expect("OP", "(")
            params = []
            if not (self.peek().kind == "OP" and self.peek().value == ")"):
                params.append(self.parse_param())
                while self.peek().kind == "OP" and self.peek().value == ",":
                    self.advance()
                    params.append(self.parse_param())
            self.expect("OP", ")")
            if self.peek().kind == "OP" and self.peek().value == ";":
                self.advance()
                return ("FuncDecl", ty, name_tok.value, params)
            body = self.parse_block()
            return ("FuncDef", ty, name_tok.value, params, body)
        # global variables, possibly comma separated: int a, b = 2, c;
        decls = []
        while True:
            dty, name, name_loc = self.parse_declarator(ty)
            init = None
            if self.peek().kind == "OP" and self.peek().value == "=":
                self.advance()
                init = self._parse_init()
            decls.append(("GlobalVar", dty, name, init, name_loc))
            if self.peek().kind == "OP" and self.peek().value == ",":
                self.advance()
                continue
            break
        self.expect("OP", ";")
        return decls

    def parse_type(self):
        if self.peek().kind == "KEYWORD" and self.peek().value in ("struct", "union"):
            return self.parse_struct_or_union_specifier()
        specs = []
        while self.peek().kind == "KEYWORD" and self.peek().value in _SCALAR_SPECS:
            specs.append(self.advance().value)
        if not specs:
            raise CParseError(self.peek().line, self.peek().col, "expected type")
        return parse_type_specifiers(specs)

    def parse_struct_or_union_specifier(self):
        """Parse a `struct`/`union` type specifier (with or without a body).

        Definitions are laid out with natural alignment.  A tag is registered
        before its members are parsed so a struct may refer to itself through a
        pointer (`struct Node { int v; struct Node *next; }`).
        """
        kw_tok = self.advance()
        is_union = (kw_tok.value == "union")
        tag = None
        if self.peek().kind == "IDENT":
            tag = self.advance().value
        if self.peek().kind == "OP" and self.peek().value == "{":
            rec = self.record_tags.get(tag) if tag is not None else None
            if rec is None:
                rec = Type("record", name=tag, is_union=is_union)
                if tag is not None:
                    self.record_tags[tag] = rec
            self.advance()  # {
            pairs = self._parse_members()
            self.expect("OP", "}")
            layout = layout_record(tag, pairs, is_union=is_union)
            rec.members = layout.members
            rec._size = layout._size
            rec._align = layout._align
            return rec
        if tag is None:
            raise CParseError(kw_tok.line, kw_tok.col, "expected struct/union tag or body")
        rec = self.record_tags.get(tag)
        if rec is None:
            # forward declaration (completed later)
            rec = Type("record", name=tag, is_union=is_union)
            self.record_tags[tag] = rec
        return rec

    def _parse_members(self):
        """Parse a struct/union member list into (name, Type) pairs."""
        pairs = []
        while not (self.peek().kind == "OP" and self.peek().value == "}"):
            if self.peek().kind == "EOF":
                raise CParseError(self.peek().line, self.peek().col, "expected }")
            base = self.parse_type()
            while True:
                mty, mname, _mloc = self.parse_declarator(base)
                pairs.append((mname, mty))
                if self.peek().kind == "OP" and self.peek().value == ",":
                    self.advance()
                    continue
                break
            self.expect("OP", ";")
        return pairs

    def _parse_array_suffixes(self):
        """Parse the `[n]` suffixes of a declarator, outermost first."""
        sizes = []
        while self.peek().kind == "OP" and self.peek().value == "[":
            self.advance()
            if self.peek().kind == "INT_LIT":
                sizes.append(self.advance().value)
            else:
                # `[]`, or a size that is not a literal: incomplete for now
                sizes.append(None)
            self.expect("OP", "]")
        return sizes

    def _parse_declarator(self):
        """Parse a declarator.

        Returns (name, loc, wrap) where `wrap(base_type)` builds the declared
        type.  A pointer prefix binds looser than an array suffix, so
        `int *a[10]` is an array of ten pointers, and a parenthesised
        declarator such as `int (*p)[10]` is a pointer to an array.
        """
        ptrs = 0
        while self.peek().kind == "OP" and self.peek().value == "*":
            self.advance()
            ptrs += 1
        if self.peek().kind == "OP" and self.peek().value == "(":
            self.advance()
            name, loc, inner = self._parse_declarator()
            self.expect("OP", ")")
            sizes = self._parse_array_suffixes()
            def wrap(base, inner=inner, sizes=sizes):
                t = base
                for n in reversed(sizes):
                    t = Type.array(t, n)
                return inner(t)
            return name, loc, wrap
        if self.peek().kind != "IDENT":
            raise CParseError(self.peek().line, self.peek().col, "expected identifier")
        name = self.advance().value
        loc = self._loc(self.toks[self.i-1])
        sizes = self._parse_array_suffixes()
        def wrap(base, ptrs=ptrs, sizes=sizes):
            t = base
            for _ in range(ptrs):
                t = Type.pointer(t)
            for n in reversed(sizes):
                t = Type.array(t, n)
            return t
        return name, loc, wrap

    def parse_declarator(self, base_type):
        name, loc, wrap = self._parse_declarator()
        return (wrap(base_type), name, loc)

    def parse_param(self):
        ty = self.parse_type()
        name, loc, wrap = self._parse_declarator()
        pty = wrap(ty)
        # An array parameter decays to a pointer to its element type.
        if pty.kind == "array":
            pty = Type.pointer(pty.elem)
        return (pty, name, loc)

    def _parse_init(self):
        """Parse the initialiser of a declaration: an expression or a list."""
        if self.peek().kind == "OP" and self.peek().value == "{":
            self.advance()
            items = []
            if not (self.peek().kind == "OP" and self.peek().value == "}"):
                items.append(self.parse_expr())
                while self.peek().kind == "OP" and self.peek().value == ",":
                    self.advance()
                    if self.peek().kind == "OP" and self.peek().value == "}":
                        break
                    items.append(self.parse_expr())
            self.expect("OP", "}")
            return ("InitList", items)
        return self.parse_expr()

    def parse_block(self):
        self.expect("OP", "{")
        stmts = []
        while not (self.peek().kind == "OP" and self.peek().value == "}"):
            if self.peek().kind == "EOF":
                raise CParseError(self.peek().line, self.peek().col, "expected }")
            st = self.parse_stmt_or_decl()
            if isinstance(st, list):
                stmts.extend(st)
            else:
                stmts.append(st)
        self.expect("OP", "}")
        return ("Block", stmts)

    def parse_stmt_or_decl(self):
        # declaration if next is type keyword
        if self.peek().kind == "KEYWORD" and self.peek().value in _TYPE_START:
            return self.parse_decl()
        return self.parse_stmt()

    def parse_decl(self, consume_semicolon=True):
        """Parse a declaration with one or more comma-separated declarators.

        Returns a list of ("VarDecl", ty, name, init, loc) nodes; callers that
        place declarations in a statement list should splice the list.
        """
        base_ty = self.parse_type()
        decls = []
        if self.peek().kind == "OP" and self.peek().value == ";":
            # a type with no declarators (e.g. a bare struct definition)
            if consume_semicolon:
                self.advance()
            return decls
        while True:
            ty, name, name_loc = self.parse_declarator(base_ty)
            init = None
            if self.peek().kind == "OP" and self.peek().value == "=":
                self.advance()
                init = self._parse_init()
            decls.append(("VarDecl", ty, name, init, name_loc))
            if self.peek().kind == "OP" and self.peek().value == ",":
                self.advance()
                continue
            break
        if consume_semicolon:
            self.expect("OP", ";")
        return decls

    def parse_stmt(self):
        t = self.peek()
        stmt_loc = self._loc(t)
        if t.kind == "OP" and t.value == "{":
            return self.parse_block()
        if t.kind == "KEYWORD" and t.value == "if":
            self.advance()
            self.expect("OP", "(")
            cond = self.parse_expr()
            self.expect("OP", ")")
            then = self.parse_stmt()
            els = None
            if self.peek().kind == "KEYWORD" and self.peek().value == "else":
                self.advance()
                els = self.parse_stmt()
            return ("If", cond, then, els, stmt_loc)
        if t.kind == "KEYWORD" and t.value == "while":
            self.advance()
            self.expect("OP", "(")
            cond = self.parse_expr()
            self.expect("OP", ")")
            body = self.parse_stmt()
            return ("While", cond, body, stmt_loc)
        if t.kind == "KEYWORD" and t.value == "do":
            self.advance()
            body = self.parse_stmt()
            self.expect("KEYWORD", "while")
            self.expect("OP", "(")
            cond = self.parse_expr()
            self.expect("OP", ")")
            self.expect("OP", ";")
            return ("DoWhile", body, cond, stmt_loc)
        if t.kind == "KEYWORD" and t.value == "for":
            self.advance()
            self.expect("OP", "(")
            init = None
            # parse init
            if not (self.peek().kind == "OP" and self.peek().value == ";"):
                if self.peek().kind == "KEYWORD" and self.peek().value in _TYPE_START:
                    decls = self.parse_decl(consume_semicolon=False)
                    init = decls[0] if len(decls) == 1 else ("VarDecls", decls)
                else:
                    init = self.parse_simple_stmt()
                self.expect("OP", ";")
            else:
                self.expect("OP", ";")
            # parse condition
            cond = None
            if not (self.peek().kind == "OP" and self.peek().value == ";"):
                # Find the semicolon that ends the condition (at paren depth 0)
                cond_end = self.i
                paren_depth = 0
                while cond_end < len(self.toks):
                    tok = self.toks[cond_end]
                    if tok.kind == "OP" and tok.value == "(":
                        paren_depth += 1
                    elif tok.kind == "OP" and tok.value == ")":
                        paren_depth -= 1
                    elif tok.kind == "OP" and tok.value == ";" and paren_depth == 0:
                        break
                    cond_end += 1
                # Parse condition from current position to cond_end (exclusive)
                saved_toks = self.toks
                self.toks = self.toks[:cond_end]
                cond = self.parse_expr()
                self.toks = saved_toks
                self.i = cond_end  # Position at the semicolon
            else:
                cond = None
            self.expect("OP", ";")
            # parse step
            step = None
            if not (self.peek().kind == "OP" and self.peek().value == ")"):
                step = self.parse_expr()
            self.expect("OP", ")")
            body = self.parse_stmt()
            return ("For", init, cond, step, body, stmt_loc)
        if t.kind == "KEYWORD" and t.value == "break":
            self.advance(); self.expect("OP", ";"); return ("Break", stmt_loc)
        if t.kind == "KEYWORD" and t.value == "continue":
            self.advance(); self.expect("OP", ";"); return ("Continue", stmt_loc)
        if t.kind == "KEYWORD" and t.value == "return":
            self.advance()
            e = None
            if not (self.peek().kind == "OP" and self.peek().value == ";"):
                e = self.parse_expr()
            self.expect("OP", ";")
            return ("Return", e, stmt_loc)
        if t.kind == "KEYWORD" and t.value in ("printf","scanf","putchar"):
            return self.parse_io_stmt()
        # assignment statement
        if self.peek().kind == "IDENT" and self.i+1 < len(self.toks) and self.toks[self.i+1].kind == "OP" and self.toks[self.i+1].value in ("=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", "++", "--"):
            ss = self.parse_simple_stmt()
            self.expect("OP", ";")
            return ("ExprStmt", ss, stmt_loc)
        # expression statement
        if self.peek().kind == "OP" and self.peek().value == ";":
            self.advance()
            return ("Empty", stmt_loc)
        e = self.parse_expr()
        self.expect("OP", ";")
        return ("ExprStmt", e, stmt_loc)

    def parse_simple_stmt(self):
        # assignment or inc/dec (no trailing ;)
        # Parse a general lvalue expression followed by assignment operator
        if self.peek().kind == "OP" and self.peek().value in ("*", "&"):
            # Pointer dereference or address-of as lvalue
            op = self.advance().value
            expr = self.parse_simple_stmt()  # recursive for *p++ etc
            if self.peek().kind == "OP" and self.peek().value in ("=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="):
                op = self.advance().value
                e = self.parse_expr()
                return ("UnaryAssign", op, expr, op, e)
            if self.peek().kind == "OP" and self.peek().value in ("++", "--"):
                op = self.advance().value
                return ("UnaryIncDec", op, False, expr)
            raise CParseError(self.peek().line, self.peek().col, "expected assignment after unary")
        if self.peek().kind != "IDENT":
            raise CParseError(self.peek().line, self.peek().col, "expected identifier")
        name = self.advance().value
        name_loc = self._loc(self.toks[self.i-1])
        if self.peek().kind == "OP" and self.peek().value in ("=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="):
            op = self.advance().value
            e = self.parse_expr()
            return ("Assign", op, name, e, name_loc)
        if self.peek().kind == "OP" and self.peek().value in ("++", "--"):
            op = self.advance().value
            return ("IncDec", op, False, name, name_loc)
        # Check for array subscript or member access on the identifier
        if self.peek().kind == "OP" and self.peek().value in ("[", "->", "."):
            # This is a complex lvalue, parse as expression and check for assignment
            # Re-parse as expression and check for assignment
            self.i -= 1  # backtrack to re-parse as expression
            expr = self.parse_expr()
            if self.peek().kind == "OP" and self.peek().value in ("=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="):
                op = self.advance().value
                e = self.parse_expr()
                return ("Assign", op, expr, e)
        raise CParseError(self.peek().line, self.peek().col, "expected assignment")

    def parse_io_stmt(self):
        kw = self.advance().value
        kw_loc = self._loc(self.toks[self.i-1])
        self.expect("OP", "(")
        if kw == "printf":
            fmt = self.expect("STRING_LIT").value
            args = []
            while self.peek().kind == "OP" and self.peek().value == ",":
                self.advance()
                args.append(self.parse_expr())
            self.expect("OP", ")")
            self.expect("OP", ";")
            return ("Printf", fmt, args, kw_loc)
        if kw == "scanf":
            fmt = self.expect("STRING_LIT").value
            args = []
            while self.peek().kind == "OP" and self.peek().value == ",":
                self.advance()
                # expect &ident
                if not (self.peek().kind == "OP" and self.peek().value == "&"):
                    raise CParseError(self.peek().line, self.peek().col, "expected &")
                self.advance()
                args.append(self.expect("IDENT").value)
            self.expect("OP", ")")
            self.expect("OP", ";")
            return ("Scanf", fmt, args, kw_loc)
        if kw == "putchar":
            e = self.parse_expr()
            self.expect("OP", ")")
            self.expect("OP", ";")
            return ("Putchar", e, kw_loc)

    # expressions with precedence climbing
    def parse_expr(self, stop_tokens=None):
        return self.parse_assignment(stop_tokens)

    def parse_assignment(self, stop_tokens=None):
        # Assignment has the lowest precedence (right-associative)
        left = self.parse_ternary(stop_tokens)
        if self.peek().kind == "OP" and self.peek().value in ("=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="):
            op = self.advance().value
            right = self.parse_assignment(stop_tokens)
            return ("Assign", op, left, right)
        return left

    def parse_ternary(self, stop_tokens=None):
        cond = self.parse_logical_or(stop_tokens)
        if self.peek().kind == "OP" and self.peek().value == "?":
            self.advance()
            t = self.parse_expr(stop_tokens)
            self.expect("OP", ":")
            f = self.parse_ternary(stop_tokens)
            return ("Ternary", cond, t, f)
        return cond

    def parse_logical_or(self, stop_tokens=None):
        node = self.parse_logical_and(stop_tokens)
        while self.peek().kind == "OP" and self.peek().value == "||":
            self.advance()
            node = ("BinOp", "||", node, self.parse_logical_and(stop_tokens))
        return node

    def parse_logical_and(self, stop_tokens=None):
        node = self.parse_bitwise_or(stop_tokens)
        while self.peek().kind == "OP" and self.peek().value == "&&":
            self.advance()
            node = ("BinOp", "&&", node, self.parse_bitwise_or(stop_tokens))
        return node

    def parse_bitwise_or(self, stop_tokens=None):
        node = self.parse_bitwise_xor(stop_tokens)
        while self.peek().kind == "OP" and self.peek().value == "|":
            self.advance()
            node = ("BinOp", "|", node, self.parse_bitwise_xor(stop_tokens))
        return node

    def parse_bitwise_xor(self, stop_tokens=None):
        node = self.parse_bitwise_and(stop_tokens)
        while self.peek().kind == "OP" and self.peek().value == "^":
            self.advance()
            node = ("BinOp", "^", node, self.parse_bitwise_and(stop_tokens))
        return node

    def parse_bitwise_and(self, stop_tokens=None):
        node = self.parse_equality(stop_tokens)
        while self.peek().kind == "OP" and self.peek().value == "&":
            self.advance()
            node = ("BinOp", "&", node, self.parse_equality(stop_tokens))
        return node

    def parse_equality(self, stop_tokens=None):
        node = self.parse_relational(stop_tokens)
        while self.peek().kind == "OP" and self.peek().value in ("==", "!="):
            op = self.advance().value
            node = ("BinOp", op, node, self.parse_relational(stop_tokens))
        return node

    def parse_relational(self, stop_tokens=None):
        node = self.parse_shift(stop_tokens)
        while self.peek().kind == "OP" and self.peek().value in ("<", ">", "<=", ">="):
            op = self.advance().value
            node = ("BinOp", op, node, self.parse_shift(stop_tokens))
        return node

    def parse_shift(self, stop_tokens=None):
        node = self.parse_additive(stop_tokens)
        while self.peek().kind == "OP" and self.peek().value in ("<<", ">>"):
            op = self.advance().value
            node = ("BinOp", op, node, self.parse_additive(stop_tokens))
        return node

    def parse_additive(self, stop_tokens=None):
        node = self.parse_multiplicative(stop_tokens)
        while self.peek().kind == "OP" and self.peek().value in ("+", "-"):
            op = self.advance().value
            node = ("BinOp", op, node, self.parse_multiplicative(stop_tokens))
        return node

    def parse_multiplicative(self, stop_tokens=None):
        node = self.parse_cast(stop_tokens)
        while self.peek().kind == "OP" and self.peek().value in ("*", "/", "%"):
            op = self.advance().value
            node = ("BinOp", op, node, self.parse_cast(stop_tokens))
        return node

    def parse_cast(self, stop_tokens=None):
        if self.peek().kind == "OP" and self.peek().value == "(":
            # could be cast or parenthesized expr
            saved = self.i
            self.advance()
            if self.peek().kind == "KEYWORD" and self.peek().value in _TYPE_START:
                ty = self.parse_type()
                self.expect("OP", ")")
                e = self.parse_cast(stop_tokens)
                return ("Cast", ty, e)
            self.i = saved
        return self.parse_unary_expr(stop_tokens)

    def parse_unary_expr(self, stop_tokens=None):
        # Unary expressions: postfix expressions and unary operators
        # Postfix has higher precedence than unary operators
        if self.peek().kind == "OP" and self.peek().value in ("-", "!", "~", "++", "--", "*", "&"):
            op = self.advance().value
            if op in ("++", "--"):
                e = self.parse_unary_expr(stop_tokens)
                return ("IncDec", op, True, e)
            e = self.parse_cast(stop_tokens)
            if op == "-":
                return ("Unary", "-", e)
            elif op == "!":
                return ("Unary", "!", e)
            elif op == "~":
                return ("Unary", "~", e)
            elif op == "*":
                return ("Unary", "*", e)  # dereference
            elif op == "&":
                return ("Unary", "&", e)  # address-of
            return ("Unary", op, e)
        else:
            return self.parse_postfix_expr(stop_tokens)

    def parse_postfix_expr(self, stop_tokens=None):
        # Postfix expressions: primary followed by [], (), ., ->, ++, --
        node = self.parse_primary(stop_tokens)
        while True:
            if self.peek().kind == "OP" and self.peek().value == "[":
                # Array subscript: base[index]
                self.advance()  # consume [
                idx = self.parse_expr(stop_tokens)
                self.expect("OP", "]")
                node = ("Index", node, idx)
            elif self.peek().kind == "OP" and self.peek().value == "(":
                # Function call: func(args)
                self.advance()  # consume (
                args = []
                if not (self.peek().kind == "OP" and self.peek().value == ")"):
                    args.append(self.parse_expr(stop_tokens))
                    while self.peek().kind == "OP" and self.peek().value == ",":
                        self.advance()
                        args.append(self.parse_expr(stop_tokens))
                self.expect("OP", ")")
                node = ("Call", node[1] if node[0] == "Ident" else node, args)
            elif self.peek().kind == "OP" and self.peek().value == ".":
                # Member access: obj.member
                self.advance()  # consume .
                member = self.expect("IDENT").value
                node = ("Member", node, member)
            elif self.peek().kind == "OP" and self.peek().value == "->":
                # Pointer member access: ptr->member
                self.advance()
                member = self.expect("IDENT").value
                node = ("Arrow", node, member)
            elif self.peek().kind == "OP" and self.peek().value in ("++", "--"):
                # Postfix increment/decrement: i++, i--
                op = self.advance().value
                node = ("IncDec", op, False, node)
            else:
                break
        return node

    def parse_primary(self, stop_tokens=None):
        t = self.peek()
        if t.kind == "INT_LIT":
            self.advance()
            return ("IntLit", t.value, t.ty)
        if t.kind == "CHAR_LIT":
            self.advance()
            return ("CharLit", t.value)
        if t.kind == "IDENT":
            name = self.advance().value
            name_loc = self._loc(self.toks[self.i-1])
            if self.peek().kind == "OP" and self.peek().value == "(":
                # Function call
                self.advance()
                args = []
                if not (self.peek().kind == "OP" and self.peek().value == ")"):
                    args.append(self.parse_expr(stop_tokens))
                    while self.peek().kind == "OP" and self.peek().value == ",":
                        self.advance()
                        args.append(self.parse_expr(stop_tokens))
                self.expect("OP", ")")
                return ("Call", name, args, name_loc)
            return ("Ident", name, name_loc)
        if t.kind == "STRING_LIT":
            self.advance()
            return ("StringLit", t.value)
        if t.kind == "OP" and t.value == "(":
            self.advance()
            e = self.parse_expr(stop_tokens)
            self.expect("OP", ")")
            return e
        # Check for statement terminators
        if t.kind == "OP" and t.value in (";", ")", ",", "}"):
            if stop_tokens and t.kind in stop_tokens and t.value in stop_tokens[t.kind]:
                return ("EndOfExpr",)
            raise CParseError(t.line, t.col, "unexpected token %r" % (t.value,))
        raise CParseError(t.line, t.col, "unexpected token %r" % (t.value,))


def parse_c(src):
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from c_lexer import lex_c
    from preprocess import preprocess
    try:
        processed = preprocess(src)
    except PreprocessError as e:
        raise CParseError(e.line, 1, e.msg)
    toks = lex_c(processed)
    p = Parser(toks)
    return p.parse_translation_unit()