# cond_jump.py - Convert ifFalse to proper conditional jumps (Compiler Design, BCSE307L)
# Converts: ifFalse t goto L  ->  if x relop y goto L
# Also handles: while conditions, for conditions, etc.

import tac


def _cond_jump(instrs):
    """Convert ifFalse of comparison results to proper conditional jumps"""
    out = []
    changes = 0
    
    for i, ins in enumerate(instrs):
        if ins.op == "ifFalse":
            cond_var = ins.arg1
            target = ins.arg2
            
            # Case 1: Condition is a constant directly (e.g., ifFalse 1 goto L)
            if isinstance(cond_var, int):
                if cond_var == 0:
                    # Always false - replace with goto
                    out.append(tac.Instr("goto", target, None, None))
                    changes += 1
                else:
                    # Always true - fall through (no jump needed)
                    changes += 1
                continue
            
            # Case 2: Condition is a temp variable (e.g., ifFalse t1 goto L)
            if isinstance(cond_var, str) and cond_var.startswith('t'):
                # Search backwards for the definition
                for j in range(i-1, -1, -1):
                    prev = instrs[j]
                    if prev.result == cond_var:
                        if prev.op in ("<", ">", "<=", ">=", "==", "!="):
                            # Found the comparison! Convert to proper conditional jump
                            new_ins = tac.Instr("if", prev.arg1, prev.op, prev.arg2, target)
                            out.append(new_ins)
                            changes += 1
                            break
                        elif prev.op in ("&&", "||"):
                            # Logical ops - keep as ifFalse for now
                            out.append(ins)
                            break
                        elif prev.op == "copy" and isinstance(prev.arg1, int):
                            # Constant condition (folded comparison)
                            if prev.arg1 == 0:
                                # Always false - replace with goto
                                out.append(tac.Instr("goto", target, None, None))
                            else:
                                # Always true - just fall through (no jump needed)
                                pass
                            changes += 1
                            break
                else:
                    out.append(ins)
            else:
                out.append(ins)
        else:
            out.append(ins)
    
    return out, changes


def cond_jump(instrs, ctx=None):
    """Main entry point"""
    cur = list(instrs)
    total_changes = 0
    changed = True
    while changed:
        changed = False
        new, ch = _cond_jump(cur)
        if ch > 0:
            changed = True
            total_changes += ch
        cur = new
    return cur, total_changes