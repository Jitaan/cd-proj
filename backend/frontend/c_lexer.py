# frontend/c_lexer.py - C lexer (C1)
import re

class CLexError(Exception):
    def __init__(self, line, col, msg):
        self.line = line
        self.col = col
        self.msg = msg
        super().__init__("%d:%d: %s" % (line, col, msg))

KEYWORDS = {"int","char","short","long","unsigned","signed","void","const",
            "if","else","while","do","for","break","continue","return",
            "printf","scanf","putchar"}

OP2 = ["<<=", ">>=", "++", "--", "+=", "-=", "*=", "/=", "%=", "&=", "|=",
       "^=", "<<", ">>", "<=", ">=", "==", "!=", "&&", "||"]
OP1 = ["+", "-", "*", "/", "%", "&", "|", "^", "<", ">", "=", "!", "~",
       "(", ")", "{", "}", ";", ",", "[", "]", "."]

def _type_tag(value, suffix):
    # simplified: decimal -> i32 or i64; hex/octal -> i32/u32/i64; suffixes
    s = suffix.lower()
    if "u" in s:
        unsigned = True
    else:
        unsigned = False
    if "ll" in s:
        bits = 64
    elif "l" in s:
        bits = 64
    else:
        bits = 32
    if unsigned:
        return "u%d" % bits
    return "i%d" % bits

class CToken:
    def __init__(self, kind, value, line, col, ty=None):
        self.kind = kind
        self.value = value
        self.line = line
        self.col = col
        self.ty = ty
    def __repr__(self):
        return "CToken(%s, %r, %d, %d)" % (self.kind, self.value, self.line, self.col)

def lex_c(src):
    tokens = []
    i = 0
    n = len(src)
    line = 1
    col = 1
    while i < n:
        c = src[i]
        if c == "\n":
            i += 1; line += 1; col = 1; continue
        if c in " \t\r":
            i += 1; col += 1; continue
        # operators (longest match)
        matched = False
        for op in sorted(OP2 + OP1, key=len, reverse=True):
            if src.startswith(op, i):
                # ensure not part of identifier
                if op.isalpha():
                    pass
                tokens.append(CToken("OP", op, line, col))
                i += len(op); col += len(op); matched = True; break
        if matched:
            continue
        # identifiers / keywords
        if c.isalpha() or c == "_":
            start = i
            while i < n and (src[i].isalnum() or src[i] == "_"):
                i += 1
            word = src[start:i]
            if re.fullmatch(r"t\d+", word):
                raise CLexError(line, col, "reserved identifier %s" % word)
            if word in KEYWORDS:
                tokens.append(CToken("KEYWORD", word, line, col))
            else:
                tokens.append(CToken("IDENT", word, line, col))
            col += i - start
            continue
        # numbers
        if c.isdigit():
            start = i
            # hex
            if src.startswith("0x", i) or src.startswith("0X", i):
                i += 2
                while i < n and (src[i].isdigit() or src[i] in "abcdefABCDEF"):
                    i += 1
            elif c == "0" and i+1 < n and src[i+1].isdigit():
                while i < n and src[i].isdigit():
                    i += 1
            else:
                while i < n and src[i].isdigit():
                    i += 1
            # suffix
            suffix = ""
            while i < n and (src[i].isalpha()):
                suffix += src[i]; i += 1
            val_str = src[start:i-len(suffix)] if suffix else src[start:i]
            # parse value
            if val_str.startswith("0x") or val_str.startswith("0X"):
                value = int(val_str, 16)
            elif len(val_str) > 1 and val_str.startswith("0"):
                value = int(val_str, 8)
            else:
                value = int(val_str)
            ty = _type_tag(value, suffix)
            tokens.append(CToken("INT_LIT", value, line, col, ty=ty))
            col += i - start
            continue
        # char literal
        if c == "'":
            # read until closing quote (simple)
            j = i + 1
            chars = ""
            while j < n and src[j] != "'":
                if src[j] == "\\":
                    chars += src[j:j+2]; j += 2
                else:
                    chars += src[j]; j += 1
            # compute value
            raw = src[i+1:j]
            if raw.startswith("\\"):
                esc = {"n":10,"t":9,"r":13,"0":0,"\\":92,"'":39}
                value = esc.get(raw[1:], ord(raw[1]) if len(raw)>1 else 0)
            else:
                value = ord(raw) if raw else 0
            tokens.append(CToken("CHAR_LIT", value, line, col, ty="i32"))
            i = j + 1; col += (j + 1 - i + 1) if False else (j - i + 2)
            continue
        # string literal
        if c == '"':
            j = i + 1
            chars = ""
            while j < n and src[j] != '"':
                if src[j] == "\\":
                    if j + 1 < n:
                        esc_char = src[j+1]
                        esc_map = {"n":"\n","t":"\t","r":"\r","0":"\0","\\":"\\",'"':'"'}
                        chars += esc_map.get(esc_char, esc_char)
                        j += 2
                    else:
                        chars += "\\"
                        j += 1
                else:
                    chars += src[j]
                    j += 1
            # Store the processed string with quotes
            tokens.append(CToken("STRING_LIT", '"' + chars + '"', line, col))
            i = j + 1; col += (j - i + 1)
            continue
        raise CLexError(line, col, "unexpected character %r" % c)
    tokens.append(CToken("EOF", None, line, col))
    return tokens
