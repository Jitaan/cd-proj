# frontend/c_types.py - the C type system.
#
# Every C type handled by this compiler is a `Type` object: the parser builds
# them, the semantic analyser checks them, the code generator lowers them and
# the IR carries them.  Earlier versions of this file kept three parallel
# representations alive (a parser tuple tree, a `CType` class and IR string
# tags); they disagreed with each other often enough to cause real bugs, so
# there is now exactly one.

from frontend.errors import SemanticError


PTR_SIZE = 8          # a pointer value is an address, stored in 8 bytes
MAX_ALIGN = 8


class Member:
    """One field of a struct or union."""

    __slots__ = ("name", "type", "offset")

    def __init__(self, name, type, offset=0):
        self.name = name
        self.type = type
        self.offset = offset

    def __repr__(self):
        return "Member(%r, %s, %d)" % (self.name, self.type, self.offset)


class Type:
    """A C type.

    ``kind`` is one of:

    ``scalar``   integer type, described by ``bits`` and ``signed``
    ``void``     the type of a function that returns nothing
    ``array``    ``count`` elements of type ``elem``
    ``pointer``  pointer to ``pointee``
    ``record``   struct or union; ``members`` carry their byte offsets
    """

    __slots__ = ("kind", "bits", "signed", "elem", "count", "pointee",
                 "name", "members", "is_union", "_size", "_align")

    def __init__(self, kind, bits=32, signed=True, elem=None, count=0,
                 pointee=None, name=None, members=None, is_union=False):
        self.kind = kind
        self.bits = bits
        self.signed = signed
        self.elem = elem
        self.count = count
        self.pointee = pointee
        self.name = name
        self.members = list(members) if members else []
        self.is_union = is_union
        self._size = 0
        self._align = 1

    # -- constructors -------------------------------------------------
    @staticmethod
    def scalar(bits=32, signed=True):
        return Type("scalar", bits=bits, signed=signed)

    @staticmethod
    def void():
        return Type("void")

    @staticmethod
    def array(elem, count):
        return Type("array", elem=elem, count=count)

    @staticmethod
    def pointer(pointee):
        return Type("pointer", pointee=pointee)

    # -- predicates ---------------------------------------------------
    @property
    def is_scalar(self):
        return self.kind == "scalar"

    @property
    def is_void(self):
        return self.kind == "void"

    @property
    def is_array(self):
        return self.kind == "array"

    @property
    def is_pointer(self):
        return self.kind == "pointer"

    @property
    def is_record(self):
        return self.kind == "record"

    @property
    def is_aggregate(self):
        return self.kind in ("array", "record")

    # -- layout -------------------------------------------------------
    @property
    def size_bytes(self):
        if self.kind == "scalar":
            return max(1, self.bits // 8)
        if self.kind == "void":
            return 0
        if self.kind == "array":
            return self.elem.size_bytes * self.count
        if self.kind == "pointer":
            return PTR_SIZE
        return self._size

    @property
    def align(self):
        if self.kind == "scalar":
            return min(max(1, self.bits // 8), MAX_ALIGN)
        if self.kind == "void":
            return 1
        if self.kind == "array":
            return self.elem.align
        if self.kind == "pointer":
            return PTR_SIZE
        return self._align

    @property
    def tag(self):
        """A short display name, e.g. "i32", "ptr", "array10"."""
        if self.kind == "scalar":
            return ("i" if self.signed else "u") + str(self.bits)
        if self.kind == "void":
            return "void"
        if self.kind == "pointer":
            return "ptr"
        if self.kind == "array":
            return "array%d" % self.count
        return "rec:%s" % (self.name or "?")

    def decay(self):
        """The type an expression of this type decays to (array -> pointer)."""
        if self.kind == "array":
            return Type.pointer(self.elem)
        return self

    # -- protocol -----------------------------------------------------
    def __eq__(self, other):
        if not isinstance(other, Type):
            return NotImplemented
        if self.kind != other.kind:
            return False
        if self.kind == "scalar":
            return self.bits == other.bits and self.signed == other.signed
        if self.kind == "array":
            return self.count == other.count and self.elem == other.elem
        if self.kind == "pointer":
            return self.pointee == other.pointee
        if self.kind == "record":
            return (self.name == other.name
                    and self.is_union == other.is_union
                    and len(self.members) == len(other.members)
                    and all(a.name == b.name and a.offset == b.offset
                            and a.type == b.type
                            for a, b in zip(self.members, other.members)))
        return True

    def __hash__(self):
        if self.kind == "scalar":
            return hash((self.kind, self.bits, self.signed))
        if self.kind == "array":
            return hash((self.kind, self.count, self.elem))
        if self.kind == "pointer":
            return hash((self.kind, self.pointee))
        if self.kind == "record":
            return hash((self.kind, self.name, self.is_union))
        return hash(self.kind)

    def __str__(self):
        return self.tag

    def __repr__(self):
        return "Type(%s)" % self.tag


VOID = Type("void")
INT = Type("scalar", bits=32, signed=True)
UINT = Type("scalar", bits=32, signed=False)
CHAR = Type("scalar", bits=8, signed=True)


def _align_up(n, a):
    if a <= 1:
        return n
    return (n + a - 1) // a * a


def layout_record(name, member_types, is_union=False):
    """Build a record type from a list of ``(member_name, Type)`` pairs.

    Struct members are laid out in order with natural alignment and padding;
    union members all start at offset 0 and the union is as large as its
    biggest member.
    """
    members = []
    offset = 0
    max_align = 1
    max_size = 0
    for mname, mtype in member_types:
        a = mtype.align
        if a > max_align:
            max_align = a
        if is_union:
            members.append(Member(mname, mtype, 0))
            if mtype.size_bytes > max_size:
                max_size = mtype.size_bytes
        else:
            offset = _align_up(offset, a)
            members.append(Member(mname, mtype, offset))
            offset += mtype.size_bytes
    size = max_size if is_union else offset
    t = Type("record", name=name, members=members, is_union=is_union)
    t._size = _align_up(size, max_align)
    t._align = max_align
    return t


def member_of(record_ty, name, line=0, col=0):
    """Look up a member of a record type; raise SemanticError if absent."""
    if record_ty is None or record_ty.kind != "record":
        raise SemanticError(line, col, "member access on non-record type")
    for m in record_ty.members:
        if m.name == name:
            return m
    raise SemanticError(line, col, "no member %r in %s" % (name, record_ty.tag))


def parse_type_specifiers(specs):
    """Build a Type from a list of C type-specifier keywords."""
    allowed = {"char", "short", "int", "long", "unsigned", "signed", "void", "const"}
    for s in specs:
        if s not in allowed:
            raise SemanticError(0, 0, "illegal type specifier %s" % s)
    specs = [s for s in specs if s != "const"]
    if not specs:
        raise SemanticError(0, 0, "missing type")
    if "void" in specs:
        return VOID
    if "char" in specs:
        bits = 8
    elif "short" in specs:
        bits = 16
    elif specs.count("long") >= 1:
        bits = 64
    else:
        bits = 32
    return Type("scalar", bits=bits, signed="unsigned" not in specs)


def type_from_tag(tag):
    """Rebuild a Type from a tag string (the lexer's literal tags, or Type.tag)."""
    if isinstance(tag, Type):
        return tag
    if not isinstance(tag, str):
        return INT
    if tag == "void":
        return VOID
    if tag == "ptr":
        return Type.pointer(INT)
    if tag.startswith("array"):
        try:
            n = int(tag[5:].split(":")[0])
        except ValueError:
            n = 0
        return Type.array(INT, n)
    if len(tag) >= 2 and tag[0] in "iu" and tag[1:].isdigit():
        return Type("scalar", bits=int(tag[1:]), signed=(tag[0] == "i"))
    return INT


def _promote(t):
    """Integer promotion: anything narrower than int becomes int."""
    if t.bits < 32:
        return Type("scalar", bits=32, signed=t.signed)
    return t


def common_type(a, b):
    """The usual arithmetic conversions, over Type objects."""
    if a is None:
        return b
    if b is None:
        return a
    if not isinstance(a, Type):
        a = type_from_tag(a)
    if not isinstance(b, Type):
        b = type_from_tag(b)
    if a.kind == "pointer" or b.kind == "pointer":
        return a if a.kind == "pointer" else b
    if a.kind == "array":
        return a.decay()
    if b.kind == "array":
        return b.decay()
    if a.kind == "record":
        return a
    if b.kind == "record":
        return b
    if a.kind == "void" or b.kind == "void":
        return VOID
    a = _promote(a)
    b = _promote(b)
    if a.bits == 64 or b.bits == 64:
        return Type("scalar", bits=64, signed=(a.signed and b.signed))
    if not a.signed or not b.signed:
        return Type("scalar", bits=32, signed=False)
    return Type("scalar", bits=32, signed=True)
