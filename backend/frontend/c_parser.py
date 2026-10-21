# frontend/c_parser.py - C parser (C1, scalar + main)
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from c_lexer import lex_c, CToken, CLexError
from preprocess import PreprocessError

class CParseError(Exception):
    def __init__(self, line, col, msg):
        self.line = line; self.col = col; self.msg = msg
        super().__init__("%d:%d: %s" % (line, col, msg))

class Parser:
    def __init__(self, toks):
        self.toks = toks; self.i = 0
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
            if self.peek().kind == "KEYWORD" and self.peek().value in ("struct","enum","typedef","switch","goto"):
                raise CParseError(self.peek().line, self.peek().col, "unsupported feature: %s" % self.peek().value)
            # function or global
            decls.append(self.parse_top_level())
        return ("TU", decls)

    def parse_top_level(self):
        # type + name
        ty = self.parse_type()
        name_tok = self.expect("IDENT")
        name_loc = self._loc(name_tok)
        if self.peek().kind == "OP" and self.peek().value == "(":
            # function
            self.advance()
            params = []
            if not (self.peek().kind == "OP" and self.peek().value == ")"):
                params.append(self.parse_param())
                while self.peek().kind == "OP" and self.peek().value == ",":
                    self.advance()
                    params.append(self.parse_param())
            self.expect("OP", ")")
            if self.peek().kind == "OP" and self.peek().value == ";":
                self.advance()
                return ("FuncDecl", ty, name_tok.value, params, name_loc)
            body = self.parse_block()
            return ("FuncDef", ty, name_tok.value, params, body, name_loc)
        # global var
        init = None
        if self.peek().kind == "OP" and self.peek().value == "=":
            self.advance()
            init = self.parse_expr()
        self.expect("OP", ";")
        return ("GlobalVar", ty, name_tok.value, init, name_loc)

    def parse_type(self):
        specs = []
        while self.peek().kind == "KEYWORD" and self.peek().value in ("const","char","short","int","long","unsigned","signed","void"):
            specs.append(self.advance().value)
        if not specs:
            raise CParseError(self.peek().line, self.peek().col, "expected type")
        return ("Type", specs)

    def parse_param(self):
        ty = self.parse_type()
        name = self.expect("IDENT").value
        name_loc = self._loc(self.toks[self.i-1])
        return (ty, name, name_loc)

    def parse_block(self):
        self.expect("OP", "{")
        stmts = []
        while not (self.peek().kind == "OP" and self.peek().value == "}"):
            if self.peek().kind == "EOF":
                raise CParseError(self.peek().line, self.peek().col, "expected }")
            stmts.append(self.parse_stmt_or_decl())
        self.expect("OP", "}")
        return ("Block", stmts)

    def parse_stmt_or_decl(self):
        # declaration if next is type keyword
        if self.peek().kind == "KEYWORD" and self.peek().value in ("const","char","short","int","long","unsigned","signed","void"):
            return self.parse_decl()
        return self.parse_stmt()

    def parse_decl(self):
        ty = self.parse_type()
        name = self.expect("IDENT").value
        name_loc = self._loc(self.toks[self.i-1])
        init = None
        if self.peek().kind == "OP" and self.peek().value == "=":
            self.advance()
            init = self.parse_expr()
        # multiple declarators not supported
        self.expect("OP", ";")
        return ("VarDecl", ty, name, init, name_loc)

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
            if not (self.peek().kind == "OP" and self.peek().value == ";"):
                if self.peek().kind == "KEYWORD" and self.peek().value in ("const","char","short","int","long","unsigned","signed","void"):
                    init = self.parse_decl()
                else:
                    init = self.parse_simple_stmt()
                    self.expect("OP", ";")
            else:
                self.expect("OP", ";")
            cond = None
            if not (self.peek().kind == "OP" and self.peek().value == ";"):
                cond = self.parse_expr()
            self.expect("OP", ";")
            step = None
            if not (self.peek().kind == "OP" and self.peek().value == ")"):
                step = self.parse_simple_stmt()
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
    def parse_expr(self):
        return self.parse_ternary()

    def parse_ternary(self):
        cond = self.parse_logical_or()
        if self.peek().kind == "OP" and self.peek().value == "?":
            self.advance()
            t = self.parse_expr()
            self.expect("OP", ":")
            f = self.parse_ternary()
            return ("Ternary", cond, t, f)
        return cond

    def parse_logical_or(self):
        node = self.parse_logical_and()
        while self.peek().kind == "OP" and self.peek().value == "||":
            self.advance()
            node = ("BinOp", "||", node, self.parse_logical_and())
        return node

    def parse_logical_and(self):
        node = self.parse_bitwise_or()
        while self.peek().kind == "OP" and self.peek().value == "&&":
            self.advance()
            node = ("BinOp", "&&", node, self.parse_bitwise_or())
        return node

    def parse_bitwise_or(self):
        node = self.parse_bitwise_xor()
        while self.peek().kind == "OP" and self.peek().value == "|":
            self.advance()
            node = ("BinOp", "|", node, self.parse_bitwise_xor())
        return node

    def parse_bitwise_xor(self):
        node = self.parse_bitwise_and()
        while self.peek().kind == "OP" and self.peek().value == "^":
            self.advance()
            node = ("BinOp", "^", node, self.parse_bitwise_and())
        return node

    def parse_bitwise_and(self):
        node = self.parse_equality()
        while self.peek().kind == "OP" and self.peek().value == "&":
            self.advance()
            node = ("BinOp", "&", node, self.parse_equality())
        return node

    def parse_equality(self):
        node = self.parse_relational()
        while self.peek().kind == "OP" and self.peek().value in ("==", "!="):
            op = self.advance().value
            node = ("BinOp", op, node, self.parse_relational())
        return node

    def parse_relational(self):
        node = self.parse_shift()
        while self.peek().kind == "OP" and self.peek().value in ("<", ">", "<=", ">="):
            op = self.advance().value
            node = ("BinOp", op, node, self.parse_shift())
        return node

    def parse_shift(self):
        node = self.parse_additive()
        while self.peek().kind == "OP" and self.peek().value in ("<<", ">>"):
            op = self.advance().value
            node = ("BinOp", op, node, self.parse_additive())
        return node

    def parse_additive(self):
        node = self.parse_multiplicative()
        while self.peek().kind == "OP" and self.peek().value in ("+", "-"):
            op = self.advance().value
            node = ("BinOp", op, node, self.parse_multiplicative())
        return node

    def parse_multiplicative(self):
        node = self.parse_cast()
        while self.peek().kind == "OP" and self.peek().value in ("*", "/", "%"):
            op = self.advance().value
            node = ("BinOp", op, node, self.parse_cast())
        return node

    def parse_cast(self):
        if self.peek().kind == "OP" and self.peek().value == "(":
            # could be cast or parenthesized expr
            saved = self.i
            self.advance()
            if self.peek().kind == "KEYWORD" and self.peek().value in ("char","short","int","long","unsigned","signed","void","const"):
                ty = self.parse_type()
                self.expect("OP", ")")
                e = self.parse_cast()
                return ("Cast", ty, e)
            self.i = saved
        return self.parse_unary()

    def parse_unary(self):
        t = self.peek()
        if t.kind == "OP" and t.value in ("-", "!", "~", "++", "--"):
            op = self.advance().value
            if op in ("++", "--"):
                if self.peek().kind != "IDENT":
                    raise CParseError(t.line, t.col, "expected identifier")
                name = self.advance().value
                name_loc = self._loc(self.toks[self.i-1])
                return ("IncDec", op, True, name, name_loc)
            e = self.parse_cast()
            return ("Unary", op, e)
        if t.kind == "KEYWORD" and t.value in ("sizeof",):
            raise CParseError(t.line, t.col, "unsupported: sizeof")
        return self.parse_postfix()

    def parse_postfix(self):
        node = self.parse_primary()
        while True:
            if self.peek().kind == "OP" and self.peek().value == "++":
                self.advance()
                node = ("IncDec", "++", False, node)
            elif self.peek().kind == "OP" and self.peek().value == "--":
                self.advance()
                node = ("IncDec", "--", False, node)
            else:
                break
        return node

    def parse_primary(self):
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
                self.advance()
                args = []
                if not (self.peek().kind == "OP" and self.peek().value == ")"):
                    args.append(self.parse_expr())
                    while self.peek().kind == "OP" and self.peek().value == ",":
                        self.advance()
                        args.append(self.parse_expr())
                self.expect("OP", ")")
                return ("Call", name, args, name_loc)
            return ("Ident", name, name_loc)
        if t.kind == "STRING_LIT":
            self.advance()
            return ("StringLit", t.value)
        if t.kind == "OP" and t.value == "(":
            self.advance()
            e = self.parse_expr()
            self.expect("OP", ")")
            return e
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