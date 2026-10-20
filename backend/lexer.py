# Module 1: Lexer - regular-expression based tokeniser (Compiler Design, BCSE307L).
import re
class LexError(Exception):
    def __init__(self, line, char):
        self.line = line; self.char = char
        if char == ".":
            super().__init__("unsupported floating-point literal at line %d" % line)
        else:
            super().__init__("LexError(%d, %r)" % (line, char))
TOKEN_SPECS = [
    ("SKIP_WS", r"[ \t\r\n]+"),
    ("SKIP_COMMENT_SL", r"//[^\n]*"),
    ("SKIP_COMMENT_ML", r"/\*.*?\*/"),
    ("SKIP_INCLUDE", r"#include[^\n]*"),
    ("NUM", r"\d+"),
    ("STRING", r'"[^"]*"'),
    ("OP", r"\+\+|--|\+=|-=|\*=|==|!=|<=|>=|&&|\|\||[+\-*/%<>=!]"),
    ("LPAREN", r"\("), ("RPAREN", r"\)"), ("LBRACE", r"\{"), ("RBRACE", r"\}"),
    ("SEMI", r";"), ("COMMA", r","),
    ("ID", r"[A-Za-z_][A-Za-z0-9_]*"),
]
_KEYWORDS = {"int","if","else","while","for","print","printf","return"}
def _build_master():
    parts = ["(?P<%s>%s)" % (t,p) for t,p in TOKEN_SPECS]
    return re.compile("|".join(parts), re.DOTALL)
_MASTER = _build_master()
def tokenize(source):
    tokens=[]; line=1; pos=0; n=len(source)
    while pos<n:
        m=_MASTER.match(source,pos)
        if not m: raise LexError(line, source[pos])
        pos=m.end()
        newlines=m.group(0).count("\n")
        kind=m.lastgroup; text=m.group(0)
        if kind=="SKIP_WS" or kind.startswith("SKIP_"):
            line+=newlines; continue
        if kind=="ID" and text in _KEYWORDS:
            kind=text
        if kind not in ("NUM","ID","STRING","EOF") and not kind.startswith("SKIP"):
            kind=text
        tokens.append((kind,text,line))
        line+=newlines
    tokens.append(("EOF","",line))
    return tokens
def lex(source): return tokenize(source)
class Lexer:
    def tokenize(self,source): return tokenize(source)
Lexer=Lexer
