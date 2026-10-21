# frontend/preprocess.py - minimal preprocessor (C1)
import re

class PreprocessError(Exception):
    def __init__(self, line, msg):
        self.line = line
        self.msg = msg
        super().__init__("%d: %s" % (line, msg))

BUILTIN = {
    "INT_MAX": "2147483647", "INT_MIN": "-2147483648", "UINT_MAX": "4294967295",
    "LONG_MAX": "9223372036854775807", "LONG_MIN": "-9223372036854775808",
    "CHAR_BIT": "8", "EOF": "-1",
}

def preprocess(src):
    # strip // and /* */ comments preserving line numbers
    out = []
    i = 0
    n = len(src)
    # handle line by line for directives
    lines = src.split("\n")
    macros = dict(BUILTIN)
    result_lines = []
    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#include"):
            result_lines.append("")  # blank line preserve number
            continue
        if stripped.startswith("#define"):
            parts = stripped.split()
            if len(parts) >= 3 and parts[1].isidentifier():
                macros[parts[1]] = " ".join(parts[2:])
            result_lines.append("")
            continue
        if stripped.startswith("#undef"):
            parts = stripped.split()
            if len(parts) >= 2:
                macros.pop(parts[1], None)
            result_lines.append("")
            continue
        if stripped.startswith("#"):
            raise PreprocessError(line_num, "unsupported directive: %s" % stripped)
        # macro expansion (object-like, simple)
        for name, val in macros.items():
            line = re.sub(r"\b" + re.escape(name) + r"\b", val, line)
        result_lines.append(line)
    text = "\n".join(result_lines)
    # strip comments
    text = re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), text)
    # block comments preserve newlines
    def repl_block(m):
        s = m.group(0)
        return "".join("\n" if c == "\n" else " " for c in s)
    text = re.sub(r"/\*.*?\*/", repl_block, text, flags=re.DOTALL)
    return text
