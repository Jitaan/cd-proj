# ir/interpreter.py - multi-function interpreter (C1+C2)

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


def run_program(prog, inputs=None, max_steps=1_000_000, max_depth=1000):
    if inputs is None: inputs = []
    from ir.tac import eval_binary, eval_unary, wrap, uses, defs
    from ir.program import default_value, is_array_type
    inp_idx = [0]
    globals_ = {name: (ty, val) for name, (ty, val) in prog.globals.items()}
    gtypes = {name: ty for name, (ty, val) in prog.globals.items()}
    gvals = {}
    for name, (ty, val) in prog.globals.items():
        if is_array_type(ty):
            arr = default_value(ty)
            if isinstance(val, list):
                n = ty.count or 0
                for i in range(min(n, len(val))):
                    arr[i] = val[i]
            gvals[name] = arr
        else:
            gvals[name] = val

    result = RunResult()
    # frame-based execution
    # We'll do iterative with explicit call stack
    # Each frame: {func_name, pc, locals dict, ret_var}
    call_stack = []
    # start main
    main_fn = prog.main()
    if main_fn is None:
        result.error = "no main"
        return result

    def make_frame(fn, args):
        locals_ = {}
        for (pname, pty), aval in zip(fn.params, args):
            locals_[pname] = (pty, aval)
        for v, ty in fn.var_types.items():
            if v not in locals_:
                if is_array_type(ty):
                    locals_[v] = (ty, default_value(ty))
                else:
                    locals_[v] = (ty, None)  # uninitialized
        return {"fn": fn, "pc": 0, "locals": locals_, "ret": None}

    # initialize globals as defined
    frame = make_frame(main_fn, [])
    # bind args? main has no args
    call_stack.append(frame)

    # helper to get value
    def get_val(frame, operand):
        if isinstance(operand, int):
            return operand
        if isinstance(operand, str):
            # check locals first: names may contain dots (scope-unique names)
            if operand in frame["locals"]:
                ty, val = frame["locals"][operand]
                if val is None:
                    raise RuntimeError("undefined_var")
                return val
            # globals
            if operand in gvals:
                return gvals[operand]
            # Identifiers that are not declared are errors; anything else
            # (e.g. a printf format string) is a literal.  fullmatch, not
            # match: `$` would let a trailing newline through and make the
            # format string "ok\n" look like an identifier.
            if re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', operand):
                raise RuntimeError("undefined_var")
            return operand
        return operand

    def set_val(frame, name, val, ty=None):
        if name in frame["locals"]:
            t = frame["locals"][name][0]
            frame["locals"][name] = (t, _wrap_value(val, t))
        elif name in gvals:
            gvals[name] = _wrap_value(val, gtypes[name])
        else:
            frame["locals"][name] = (ty or "i32", val)

    def array_ref(frame, base):
        """Resolve `base` to (type, list) for array accesses. No hardcoded size.

        A base may be a pointer variable whose value is the name of another
        array/variable; follow that indirection.
        """
        if not isinstance(base, str):
            raise RuntimeError("invalid array base")
        seen = set()
        cur = base
        while True:
            if cur in frame["locals"]:
                ty, val = frame["locals"][cur]
            elif cur in gvals:
                ty, val = gtypes[cur], gvals[cur]
            else:
                raise RuntimeError("unknown array '%s'" % base)
            if isinstance(val, str) and val != cur and val not in seen:
                seen.add(cur)
                cur = val
                continue
            if not isinstance(val, list):
                raise RuntimeError("'%s' is not an array" % base)
            return ty, val

    def check_index(ty, arr, index):
        if not isinstance(index, int):
            raise RuntimeError("non-integer array index")
        if index < 0 or index >= len(arr):
            raise RuntimeError("array index %d out of bounds for %s" % (index, ty))
        return index

    steps = 0
    while call_stack:
        frame = call_stack[-1]
        fn = frame["fn"]
        body = fn.body
        if frame["pc"] >= len(body):
            # fall off end
            if fn.name == "main":
                result.exit_code = 0
            call_stack.pop()
            if call_stack:
                # return to caller: set return value? handled by call instr
                pass
            continue
        if len(call_stack) > max_depth:
            result.error = "stack_overflow"
            break
        ins = body[frame["pc"]]
        # label
        if ins.op == "label":
            frame["pc"] += 1
            continue
        steps += 1
        if steps > max_steps:
            result.error = "step_limit"
            break
        result.steps = steps
        # count
        result.op_counts[ins.op] = result.op_counts.get(ins.op, 0) + 1
        result.func_steps[fn.name] = result.func_steps.get(fn.name, 0) + 1

        try:
            if ins.op == "copy":
                v = get_val(frame, ins.arg1)
                set_val(frame, ins.result, v)
                frame["pc"] += 1
            elif ins.op == "addr":
                if isinstance(ins.arg1, str):
                    set_val(frame, ins.result, ins.arg1)
                else:
                    set_val(frame, ins.result, get_val(frame, ins.arg1))
                frame["pc"] += 1
            elif ins.op in ("neg", "not", "bnot"):
                a = get_val(frame, ins.arg1)
                if ins.op == "neg": v = -a
                elif ins.op == "not": v = 0 if a != 0 else 1
                else: v = ~a
                ty = ins.ty or "i32"
                from ir.tac import wrap
                set_val(frame, ins.result, wrap(v, ty))
                frame["pc"] += 1
            elif ins.op in ("+", "-", "*", "/", "%", "<", ">", "<=", ">=", "==", "!=",
                            "&&", "||", "&", "|", "^", "<<", ">>", "shl"):
                a = get_val(frame, ins.arg1)
                b = get_val(frame, ins.arg2)
                from ir.tac import eval_binary
                r, err = eval_binary(ins.op, a, b, ins.ty or "i32")
                if err:
                    result.error = err
                    break
                set_val(frame, ins.result, r)
                frame["pc"] += 1
            elif ins.op == "cast":
                v = get_val(frame, ins.arg1)
                from ir.tac import wrap
                set_val(frame, ins.result, wrap(v, ins.ty or "i32"))
                frame["pc"] += 1
            elif ins.op == "store":
                # store base, index, value (value travels in `result`)
                base_name = ins.arg1
                index = get_val(frame, ins.arg2)
                value = get_val(frame, ins.result)
                arr_ty, arr_val = array_ref(frame, base_name)
                arr_val[check_index(arr_ty, arr_val, index)] = value
                frame["pc"] += 1
            elif ins.op == "load":
                # load base[index] -> result
                base_name = ins.arg1
                index = get_val(frame, ins.arg2)
                arr_ty, arr_val = array_ref(frame, base_name)
                value = arr_val[check_index(arr_ty, arr_val, index)]
                set_val(frame, ins.result, value)
                frame["pc"] += 1
            elif ins.op == "goto":
                # find label in current function body
                target = None
                for idx, x in enumerate(body):
                    if x.op == "label" and x.arg1 == ins.arg1:
                        target = idx
                        break
                frame["pc"] = target
            elif ins.op == "if":
                # if x relop y goto L
                a = get_val(frame, ins.arg1)
                b = get_val(frame, ins.arg2)
                target_label = ins.result
                relop = ins.op_relop
                
                # Evaluate the condition
                if relop == "<":
                    cond = a < b
                elif relop == ">":
                    cond = a > b
                elif relop == "<=":
                    cond = a <= b
                elif relop == ">=":
                    cond = a >= b
                elif relop == "==":
                    cond = a == b
                elif relop == "!=":
                    cond = a != b
                else:
                    raise ValueError("unknown relop %s" % relop)
                
                if cond:
                    target = None
                    for idx, x in enumerate(body):
                        if x.op == "label" and x.arg1 == target_label:
                            target = idx
                            break
                    frame["pc"] = target
                else:
                    frame["pc"] += 1
            elif ins.op == "ifFalse":
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
            elif ins.op == "print":
                v = get_val(frame, ins.arg1)
                result.output.append(v)
                result.stdout += str(v) + "\n"
                frame["pc"] += 1
            elif ins.op == "out_str":
                result.stdout += str(ins.arg1)
                frame["pc"] += 1
            elif ins.op == "out_val":
                v = get_val(frame, ins.arg1)
                spec = ins.arg2 or "d"
                # format
                s = _format_val(v, spec, ins.ty or "i32")
                result.stdout += s
                frame["pc"] += 1
            elif ins.op == "read":
                if inp_idx[0] >= len(inputs):
                    result.error = "input_exhausted"
                    break
                val = inputs[inp_idx[0]]
                inp_idx[0] += 1
                ty = ins.ty or "i32"
                from ir.tac import wrap
                set_val(frame, ins.result, wrap(val, ty))
                frame["pc"] += 1
            elif ins.op == "param":
                # Store param value in frame for later use by call
                if "_params" not in frame:
                    frame["_params"] = []
                val = get_val(frame, ins.arg1)
                frame["_params"].append(val)
                frame["pc"] += 1
            elif ins.op == "call":
                # Use params stored by param instructions
                args = frame.get("_params", [])
                frame["_params"] = []  # Reset for next call
                # find function
                callee = prog.functions.get(ins.arg1)
                if callee is None:
                    # Handle built-in functions like printf
                    if ins.arg1 == "printf":
                        # Handle printf: first arg is format string, rest are args
                        fmt = args[0] if args else ""
                        vals = args[1:] if len(args) > 1 else []
                        # Simple printf handling
                        result.stdout += fmt % tuple(vals) if vals else fmt
                        frame["pc"] += 1
                        continue
                    else:
                        result.error = "undefined function"
                        break
                # push frame for user functions
                callee = prog.functions.get(ins.arg1)
                if callee is not None:
                    new_frame = make_frame(callee, args)
                    call_stack.append(new_frame)
                    frame["_pending_result"] = ins.result
                    frame["_pending_ty"] = ins.ty or (callee.ret_ty or "i32")
                    frame["pc"] += 1
                else:
                    result.error = "undefined function"
                    break
            elif ins.op == "return":
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
                        from ir.tac import wrap
                        set_val(caller, pr, wrap(retval, ty) if retval is not None else 0)
                        del caller["_pending_result"]
                        del caller["_pending_ty"]
            else:
                result.error = "unknown op %s" % ins.op
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


def _wrap_value(val, ty):
    """Store `val` in a slot of type `ty`, wrapping integers to its width."""
    if not isinstance(val, int) or isinstance(val, bool):
        return val
    kind = getattr(ty, "kind", None)
    if kind in ("scalar", "pointer"):
        from ir.tac import wrap
        return wrap(val, ty)
    if kind is None and isinstance(ty, str):
        from ir.tac import wrap
        return wrap(val, ty)
    return val


def _format_val(v, spec, ty):
    # spec like "d", "u", "c", "x", "02d", etc.
    # handle width/zero flag
    from ir.tac import _bits_signed
    bits, _signed = _bits_signed(ty)
    zero = spec.startswith("0")
    # extract width
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
    # default signed decimal
    s = str(v)
    if width:
        s = s.rjust(width, "0" if zero else " ")
    return s

# legacy wrapper
def run(tac, inputs=None, max_steps=100000):
    prog = __import__("ir.program", fromlist=["Program"]).Program.from_legacy(tac)
    r = run_program(prog, inputs or [], max_steps=max_steps)
    return (r.output, r.steps)
