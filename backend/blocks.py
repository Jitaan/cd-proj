# Module 5: Basic blocks, flow graph, liveness (Compiler Design, BCSE307L).
# Splits TAC into basic blocks, builds successor edges, runs backward liveness.
# Liveness at program exit is empty because only print output is observable.

import tac


def split_blocks(instrs):
    if not instrs:
        return []
    leaders = {0}
    for i, ins in enumerate(instrs):
        if ins.op == "label":
            leaders.add(i)
        if i > 0 and instrs[i - 1].op in ("goto", "ifFalse"):
            leaders.add(i)
    leaders = sorted(leaders)
    blocks = []
    for idx, l in enumerate(leaders):
        end = leaders[idx + 1] if idx + 1 < len(leaders) else len(instrs)
        blocks.append(list(instrs[l:end]))
    return blocks


def join_blocks(blocks):
    out = []
    for b in blocks:
        out.extend(b)
    return out


def _label_to_index(blocks, label):
    for i, b in enumerate(blocks):
        if b and b[0].op == "label" and b[0].a == label:
            return i
    return None


def successors(blocks, i=None):
    if i is None:
        # support successors(i, blocks) convention
        pass
    # normalize argument order
    if isinstance(blocks, int) and not isinstance(i, int):
        blocks, i = i, blocks
    if i is None:
        # single int passed? cannot
        raise TypeError("successors requires blocks and index")
    if i >= len(blocks) or not blocks[i]:
        return []
    last = blocks[i][-1]
    if last.op == "goto":
        j = _label_to_index(blocks, last.a)
        return [j] if j is not None else []
    if last.op == "ifFalse":
        res = []
        j = _label_to_index(blocks, last.b)
        if j is not None:
            res.append(j)
        if i + 1 < len(blocks):
            res.append(i + 1)
        return res
    if i + 1 < len(blocks):
        return [i + 1]
    return []

def predecessors(blocks):
    preds = [[] for _ in blocks]
    for i in range(len(blocks)):
        for j in successors(blocks, i):
            if 0 <= j < len(blocks):
                preds[j].append(i)
    return preds


def reachable(blocks):
    if not blocks:
        return set()
    seen = set()
    stack = [0]
    while stack:
        i = stack.pop()
        if i in seen:
            continue
        if i < 0 or i >= len(blocks):
            continue
        seen.add(i)
        for j in successors(blocks, i):
            if j not in seen:
                stack.append(j)
    return seen


def _block_use_def(block):
    use = set()
    defn = set()
    for ins in block:
        for v in tac.uses(ins):
            if v not in defn:
                use.add(v)
        d = tac.defs(ins)
        if d is not None:
            defn.add(d)
    return use, defn


def liveness(blocks):
    n = len(blocks)
    uses = [None] * n
    defs = [None] * n
    for i in range(n):
        u, d = _block_use_def(blocks[i])
        uses[i] = u
        defs[i] = d
    succ = [successors(blocks, i) for i in range(n)]
    live_in = [set() for _ in range(n)]
    live_out = [set() for _ in range(n)]
    changed = True
    while changed:
        changed = False
        for i in range(n):
            new_out = set()
            for s in succ[i]:
                new_out |= live_in[s]
            new_in = uses[i] | (new_out - defs[i])
            if new_out != live_out[i] or new_in != live_in[i]:
                live_out[i] = new_out
                live_in[i] = new_in
                changed = True
    return live_in, live_out


uses = tac.uses
defs = tac.defs
