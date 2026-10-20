# frontend/c_types.py - C type system (C1)

class CType:
    def __init__(self, bits, signed, void=False):
        self.bits = bits
        self.signed = signed
        self.void = void
    @property
    def tag(self):
        if self.void: return "void"
        prefix = "i" if self.signed else "u"
        return "%s%d" % (prefix, self.bits)
    def __repr__(self):
        return self.tag

VOID = CType(0, True, void=True)

def _parse_one(specs):
    # specs: list of keyword strings
    unsigned = "unsigned" in specs
    long_count = specs.count("long")
    short = "short" in specs
    char = "char" in specs
    if "void" in specs:
        return VOID
    if char:
        bits = 8
    elif short:
        bits = 16
    elif long_count >= 2:
        bits = 64
    elif long_count == 1:
        bits = 64
    else:
        bits = 32
    signed = not unsigned
    if "signed" in specs:
        signed = True
    if "unsigned" in specs:
        signed = False
    return CType(bits, signed)

def parse_type_specifiers(specs):
    # validate combinations minimally
    allowed = {"char","short","int","long","unsigned","signed","void","const"}
    for s in specs:
        if s not in allowed:
            raise ValueError("illegal type specifier %s" % s)
    if "const" in specs:
        specs = [s for s in specs if s != "const"]
    if not specs:
        raise ValueError("missing type")
    return _parse_one(specs)

def common_type(a, b):
    # usual arithmetic conversions, simplified
    # promote to at least int (32-bit)
    def promote(t):
        if t.bits < 32:
            return CType(32, t.signed)
        return t
    a = promote(a); b = promote(b)
    # if either 64-bit
    if a.bits == 64 or b.bits == 64:
        unsigned = (not a.signed) or (not b.signed)
        # if both 64 and either unsigned -> unsigned
        if a.bits == 64 and b.bits == 64:
            unsigned = (not a.signed) or (not b.signed)
        elif a.bits == 64:
            unsigned = not a.signed
        else:
            unsigned = not b.signed
        return CType(64, not unsigned)
    if not a.signed or not b.signed:
        return CType(32, False)
    return CType(32, True)
