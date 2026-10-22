# ir/interpreter.py - multi-function interpreter (address-based memory model)
#
# Variables live in a flat, byte-addressed memory.  Each variable (global or
# local) is given a base address by a bump allocator; the per-frame symbol
# table maps a name to (base_address, Type).  Values are read/written through
# that address, which is what makes real pointers (integers) possible.
#
# Temporaries (`tN`, a namespace the lexer reserves) are plain Python values:
# their address is never taken, so they do not need storage.

import re
from dataclasses import dataclass


@dataclass
class RunResult:
    output: list = None
    stdout: str = ""
    exit_code: int = None
    steps: int = 0
    op_counts: dict = None
    func_steps: dict = None
    error: str = None

    def __post_init__(self):
        if self.output is None: self.output = []
        if self.op_counts is None: self.op_counts = {}
        if self.func_steps is None: self.func_steps = {}


_TEMP_RE = re.compile(r"t\d+")
_IDENT_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def _is_temp(name):
    return isinstance(name, str) and _TEMP_RE.fullmatch(name) is not None


def _ty_size(ty):
    """Byte width of a value of type `ty` (Type object or legacy tag)."""
    from frontend.c_types import Type
    if isinstance(ty, Type):
        if ty.kind == "pointer":
            return 8
        if ty.kind == "void":
            return 1
        if ty.kind in ("array", "record"):
            return max(1, ty.size_bytes)
        return max(1, ty.size_bytes)
    if isinstance(ty, str):
        if ty == "ptr":
            return 8
        if len(ty) >= 2 and ty[0] in "iu" and ty[1:].isdigit():
            return max(1, int(ty[1:]) // 8)
    return 4


def _ty_signed(ty):
    from frontend.c_types import Type
    if isinstance(ty, Type):
        if ty.kind == "scalar":
            return ty.signed
        if ty.kind == "pointer":
            return False
        return True
    if isinstance(ty, str) and len(ty) >= 2 and ty[0] in "iu":
        return ty[0] == "i"
    return True


def _align_up(n, a):
    if a <= 1:
        return n
    return (n + a - 1) // a * a


def run_program(prog, inputs=None, max_steps=1_000_000, max_depth=1000):
    if inputs is None: inputs = []
    from frontend.c_types import Type
    from ir.tac import eval_binary, wrap

    inp_idx = [0]
    result = RunResult()

    # -- flat memory + allocator -------------------------------------
    mem = {}
    bump = [4096]

    def alloc(size, align=1):
        base = _align_up(bump[0], max(1, align))
        bump[0] = base + max(1, size)
        return base

    def _size_align(ty):
        if isinstance(ty, Type):
            return max(1, ty.size_bytes), max(1, ty.align)
        return _ty_size(ty), 1

    def read_obj(addr, ty):
        size = _ty_size(ty)
        v = 0
        for i in range(size):
            v |= mem.get(addr + i, 0) << (8 * i)
        if _ty_signed(ty) and v >= (1 << (size * 8 - 1)):
            v -= (1 << (size * 8))
        return v

    def write_obj(addr, val, ty):
        if not isinstance(val, int) or isinstance(val, bool):
            val = int(val) if isinstance(val, bool) else 0
        size = _ty_size(ty)
        v = val & ((1 << (size * 8)) - 1)
        for i in range(size):
            mem[addr + i] = (v >> (8 * i)) & 0xFF

    def write_value(addr, ty, val):
        """Initialise a variable (possibly an aggregate) at `addr`."""
        if isinstance(ty, Type) and ty.kind == "array":
            es = ty.elem
            step = max(1, es.size_bytes)
            for i in range(ty.count or 0):
                item = val[i] if isinstance(val, list) and i < len(val) else 0
                write_value(addr + i * step, es, item)
        elif isinstance(ty, Type) and ty.kind == "record":
            return  # zero-initialised; member offsets handled by codegen
        else:
            write_obj(addr, val if isinstance(val, int) else 0, ty)

    # -- globals -----------------------------------------------------
    gsyms = {}
    for name, (ty, val) in prog.globals.items():
        size, align = _size_align(ty)
        base = alloc(size, align)
        gsyms[name] = (base, ty)
        write_value(base, ty, val)

    # -- frames ------------------------------------------------------
    call_stack = []
    main_fn = prog.main()
    if main_fn is None:
        result.error = "no main"
        return result

    def make_frame(fn, args):
        syms = {}
        uninit = set()
        for (pname, pty), aval in zip(fn.params, args):
            size, align = _size_align(pty)
            base = alloc(size, align)
            syms[pname] = (base, pty)
            if isinstance(aval, int):
                write_obj(base, aval, pty)
        for v, ty in fn.var_types.items():
            if _is_temp(v) or v in syms:
                continue
            size, align = _size_align(ty)
            base = alloc(size, align)
            syms[v] = (base, ty)
            if not (isinstance(ty, Type) and ty.kind in ("array", "record")):
                uninit.add(v)
        return {"fn": fn, "pc": 0, "syms": syms, "temps": {}, "uninit": uninit,
                "ret": None, "_params": []}

    def sym_base(frame, name):
        if name in frame["syms"]:
            return frame["syms"][name][0]
        if name in gsyms:
            return gsyms[name][0]
        return None

    def get_val(frame, operand):
        if isinstance(operand, int):
            return operand
        if isinstance(operand, str):
            if _is_temp(operand):
                if operand not in frame["temps"]:
                    raise RuntimeError("undefined_var")
                return frame["temps"][operand]
            if operand in frame["syms"]:
                base, ty = frame["syms"][operand]
            elif operand in gsyms:
                base, ty = gsyms[operand]
            else:
                # anything that is not a declared name is a literal (e.g. a
                # printf format string); a bare identifier is an error.
                if _IDENT_RE.fullmatch(operand):
                    raise RuntimeError("undefined_var")
                return operand
            if isinstance(ty, Type) and ty.kind in ("array", "record"):
                return base  # arrays/records decay to their address
            if operand in frame["uninit"]:
                raise RuntimeError("undefined_var")
            return read_obj(base, ty)
        return operand

    def set_val(frame, name, val, ty=None):
        if _is_temp(name) or (name not in frame["syms"] and name not in gsyms):
            frame["temps"][name] = val
            return
        if name in frame["syms"]:
            base, t = frame["syms"][name]
        else:
            base, t = gsyms[name]
        write_obj(base, val, t)
        frame["uninit"].discard(name)

    # start main
    call_stack.append(make_frame(main_fn, []))

    steps = 0
    while call_stack:
        frame = call_stack[-1]
        fn = frame["fn"]
        body = fn.body
        if frame["pc"] >= len(body):
            if fn.name == "main":
                result.exit_code = 0
            call_stack.pop()
            continue
        if len(call_stack) > max_depth:
            result.error = "stack_overflow"
            break
        ins = body[frame["pc"]]
        if ins.op == "label":
            frame["pc"] += 1
            continue
        steps += 1
        if steps > max_steps:
            result.error = "step_limit"
            break
        result.steps = steps
        result.op_counts[ins.op] = result.op_counts.get(ins.op, 0) + 1
        result.func_steps[fn.name] = result.func_steps.get(fn.name, 0) + 1

        try:
            op = ins.op
            if op == "copy":
                set_val(frame, ins.result, get_val(frame, ins.arg1))
                frame["pc"] += 1
            elif op == "addr":
                base = sym_base(frame, ins.arg1)
                if base is None:
                    raise RuntimeError("address of unknown '%s'" % ins.arg1)
                set_val(frame, ins.result, base)
                frame["pc"] += 1
            elif op in ("neg", "not", "bnot"):
                a = get_val(frame, ins.arg1)
                if op == "neg": v = wrap(-a, ins.ty or "i32")
                elif op == "not": v = 0 if a != 0 else 1
                else: v = wrap(~a, ins.ty or "i32")
                set_val(frame, ins.result, v)
                frame["pc"] += 1
            elif op in ("+", "-", "*", "/", "%", "<", ">", "<=", ">=", "==", "!=",
                        "&&", "||", "&", "|", "^", "<<", ">>", "shl"):
                a = get_val(frame, ins.arg1)
                b = get_val(frame, ins.arg2)
                r, err = eval_binary(op, a, b, ins.ty or "i32")
                if err:
                    result.error = err
                    break
                set_val(frame, ins.result, r)
                frame["pc"] += 1
            elif op == "cast":
                set_val(frame, ins.result, wrap(get_val(frame, ins.arg1), ins.ty or "i32"))
                frame["pc"] += 1
            elif op == "load":
                base = get_val(frame, ins.arg1)
                idx = get_val(frame, ins.arg2)
                addr = base + idx * _ty_size(ins.ty)
                set_val(frame, ins.result, read_obj(addr, ins.ty))
                frame["pc"] += 1
            elif op == "store":
                base = get_val(frame, ins.arg1)
                idx = get_val(frame, ins.arg2)
                write_obj(base + idx * _ty_size(ins.ty), get_val(frame, ins.result), ins.ty)
                frame["pc"] += 1
            elif op == "loadoff":
                addr = get_val(frame, ins.arg1) + get_val(frame, ins.arg2)
                set_val(frame, ins.result, read_obj(addr, ins.ty))
                frame["pc"] += 1
            elif op == "storeoff":
                addr = get_val(frame, ins.arg1) + get_val(frame, ins.arg2)
                write_obj(addr, get_val(frame, ins.result), ins.ty)
                frame["pc"] += 1
            elif op == "addoff":
                set_val(frame, ins.result, get_val(frame, ins.arg1) + get_val(frame, ins.arg2))
                frame["pc"] += 1
            elif op == "indexadd":
                scale = (ins.args or (1,))[0]
                v = get_val(frame, ins.arg1) + get_val(frame, ins.arg2) * scale
                set_val(frame, ins.result, v)
                frame["pc"] += 1
            elif op == "ptrdiff":
                scale = (ins.args or (1,))[0] or 1
                v = (get_val(frame, ins.arg1) - get_val(frame, ins.arg2)) // scale
                set_val(frame, ins.result, v)
                frame["pc"] += 1
            elif op == "blkcopy":
                n = (ins.args or (0,))[0]
                dst = get_val(frame, ins.arg1)
                src = get_val(frame, ins.arg2)
                for i in range(n):
                    mem[dst + i] = mem.get(src + i, 0)
                frame["pc"] += 1
            elif op == "goto":
                target = None
                for idx, x in enumerate(body):
                    if x.op == "label" and x.arg1 == ins.arg1:
                        target = idx
                        break
                frame["pc"] = target
            elif op == "if":
                a = get_val(frame, ins.arg1)
                b = get_val(frame, ins.arg2)
                target_label = ins.result
                relop = ins.op_relop
                if relop == "<": cond = a < b
                elif relop == ">": cond = a > b
                elif relop == "<=": cond = a <= b
                elif relop == ">=": cond = a >= b
                elif relop == "==": cond = a == b
                elif relop == "!=": cond = a != b
                else: raise ValueError("unknown relop %s" % relop)
                if cond:
                    target = None
                    for idx, x in enumerate(body):
                        if x.op == "label" and x.arg1 == target_label:
                            target = idx
                            break
                    frame["pc"] = target
                else:
                    frame["pc"] += 1
            elif op == "ifFalse":
                c = get_val(frame, ins.arg1)
                if c == 0:
                    target = None
                    for idx, x in enumerate(body):
                        if x.op == "label" and x.arg1 == ins.arg2:
                            target = idx
                            break
                    frame["pc"] = target
                else:
                    frame["pc"] += 1
            elif op == "print":
                v = get_val(frame, ins.arg1)
                result.output.append(v)
                result.stdout += str(v) + "\n"
                frame["pc"] += 1
            elif op == "out_str":
                result.stdout += str(ins.arg1)
                frame["pc"] += 1
            elif op == "out_val":
                v = get_val(frame, ins.arg1)
                result.stdout += _format_val(v, ins.arg2 or "d", ins.ty or "i32")
                frame["pc"] += 1
            elif op == "read":
                if inp_idx[0] >= len(inputs):
                    result.error = "input_exhausted"
                    break
                val = inputs[inp_idx[0]]
                inp_idx[0] += 1
                set_val(frame, ins.result, wrap(val, ins.ty or "i32"))
                frame["pc"] += 1
            elif op == "param":
                frame["_params"].append(get_val(frame, ins.arg1))
                frame["pc"] += 1
            elif op == "call":
                args = frame.get("_params", [])
                frame["_params"] = []
                callee = prog.functions.get(ins.arg1)
                if callee is None:
                    if ins.arg1 == "printf":
                        fmt = args[0] if args else ""
                        vals = args[1:] if len(args) > 1 else []
                        result.stdout += fmt % tuple(vals) if vals else fmt
                        frame["pc"] += 1
                        continue
                    result.error = "undefined function"
                    break
                new_frame = make_frame(callee, args)
                call_stack.append(new_frame)
                frame["_pending_result"] = ins.result
                frame["_pending_ty"] = ins.ty or (callee.ret_ty or "i32")
                frame["pc"] += 1
            elif op == "return":
                retval = None
                if ins.arg1 is not None:
                    retval = get_val(frame, ins.arg1)
                frame["ret"] = retval
                call_stack.pop()
                if call_stack:
                    caller = call_stack[-1]
                    pr = caller.get("_pending_result")
                    if pr:
                        ty = caller.get("_pending_ty", "i32")
                        set_val(caller, pr, wrap(retval, ty) if retval is not None else 0)
                        del caller["_pending_result"]
                        del caller["_pending_ty"]
            else:
                result.error = "unknown op %s" % op
                break
        except RuntimeError as e:
            result.error = str(e)
            break
        except Exception as e:
            result.error = str(e)
            break

    if result.exit_code is None and not result.error:
        result.exit_code = 0
    result.steps = steps
    return result


def _format_val(v, spec, ty):
    # spec like "d", "u", "c", "x", "02d", etc.
    from ir.tac import _bits_signed
    bits, _signed = _bits_signed(ty)
    zero = spec.startswith("0")
    width_str = "".join(ch for ch in spec if ch.isdigit())
    width = int(width_str) if width_str else 0
    base_spec = "".join(ch for ch in spec if not ch.isdigit())
    if base_spec == "c":
        ch = chr(v & 0xFF)
        if width:
            return ch.rjust(width)
        return ch
    if base_spec in ("x", "X"):
        mask = (1 << bits) - 1
        val = v & mask
        s = format(val, "x" if base_spec == "x" else "X")
        if width:
            s = s.rjust(width, "0" if zero else " ")
        return s
    if base_spec == "u":
        mask = (1 << bits) - 1
        val = v & mask
        s = str(val)
        if width:
            s = s.rjust(width, "0" if zero else " ")
        return s
    s = str(v)
    if width:
        s = s.rjust(width, "0" if zero else " ")
    return s


# legacy wrapper
def run(tac, inputs=None, max_steps=100000):
    prog = __import__("ir.program", fromlist=["Program"]).Program.from_legacy(tac)
    r = run_program(prog, inputs or [], max_steps=max_steps)
    return (r.output, r.steps)
