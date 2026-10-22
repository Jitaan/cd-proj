# frontend/c_types.py - C type system (C1 + arrays/pointers)

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
    # Handle array/pointer types first
    from frontend.c_types import is_array_type, is_pointer_type
    
    # If either is array, it decays to pointer in most contexts
    if is_array_type(a) or is_array_type(b):
        # Array decays to pointer, treat as pointer arithmetic
        return a if is_pointer_type(a) else b
    
    # If either is pointer, return pointer type
    if is_pointer_type(a) or is_pointer_type(b):
        return a if is_pointer_type(a) else b
    
    # Both should be CType objects for usual arithmetic conversions
    def promote(t):
        if isinstance(t, tuple):
            # Should not happen for non-array/pointer types
            return CType(32, True)
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

# Array and pointer type helpers
def is_array_type(ty):
    return isinstance(ty, tuple) and ty[0] == "Array"

def is_pointer_type(ty):
    return isinstance(ty, tuple) and ty[0] == "Pointer"

def get_array_info(ty):
    """Returns (size, element_type) for array type"""
    if is_array_type(ty):
        return ty[1], ty[2]
    return None, None

def get_pointer_base(ty):
    """Returns base type for pointer type"""
    if is_pointer_type(ty):
        return ty[1]
    return None

def type_to_tag(ty):
    """Convert type to tag string for TAC"""
    if isinstance(ty, CType):
        return ty.tag
    if isinstance(ty, tuple):
        if ty[0] == "Array":
            return "array%d" % ty[1]
        if ty[0] == "Pointer":
            return "ptr"
    return "i32"
