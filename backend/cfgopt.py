# cfgopt.py - control-flow cleanup passes (Compiler Design, BCSE307L).
# branch: constant branch folding; unreach: unreachable code removal;
# peep: peephole cleanup; cfg: composite of the three.

import blocks
import tac


def branch(instrs):
    """Fold constant branches. Returns (new_instrs, n_changes)."""
    out = []
    n = 0
    for ins in instrs:
        if ins.op == "ifFalse" and isinstance(ins.a, (int, float)) and not isinstance(ins.a, bool):
            if ins.a == 0:
                out.append(tac.Instr("goto", ins.b, None, None))
                n += 1
            else:
                n += 1
                continue
        else:
            out.append(ins)
    return out, n


def unreach(instrs):
    """Remove unreachable blocks. Returns (new_instrs, n_changes)."""
    blks = blocks.split_blocks(instrs)
    if not blks:
        return list(instrs), 0
    reach = blocks.reachable(blks)
    removed = 0
    new_blks = []
    for i, b in enumerate(blks):
        if i in reach:
            new_blks.append(b)
        else:
            removed += sum(1 for ins in b if ins.op != "label")
    return blocks.join_blocks(new_blks), removed


def peep(instrs):
    """Peephole cleanup, repeated to fixpoint. Returns (new_instrs, n_changes)."""
    cur = list(instrs)
    total = 0
    changed = True
    while changed:
        changed = False
        # rule 1: goto L immediately followed by labels including L -> delete goto
        out = []
        i = 0
        n = len(cur)
        while i < n:
            if cur[i].op == "goto":
                # look ahead for labels
                j = i + 1
                found = False
                while j < n and cur[j].op == "label":
                    if cur[j].a == cur[i].a:
                        found = True
                    j += 1
                if found:
                    total += 1
                    changed = True
                    i += 1
                    continue
            out.append(cur[i])
            i += 1
        cur = out
        # rule 2: self-copy
        out2 = []
        for ins in cur:
            if ins.op == "copy" and ins.a == ins.dst:
                total += 1
                changed = True
                continue
            out2.append(ins)
        cur = out2
        # rule 3: unreferenced labels
        refs = set()
        for ins in cur:
            if ins.op in ("goto", "ifFalse"):
                refs.add(ins.a if ins.op == "goto" else ins.b)
        out3 = []
        for ins in cur:
            if ins.op == "label" and ins.a not in refs:
                total += 1
                changed = True
                continue
            out3.append(ins)
        cur = out3
    return cur, total


def cfg(instrs):
    """Composite: peep(unreach(branch(instrs))). Returns (new_instrs, n_changes)."""
    a, na = branch(instrs)
    b, nb = unreach(a)
    c, nc = peep(b)
    return c, na + nb + nc
