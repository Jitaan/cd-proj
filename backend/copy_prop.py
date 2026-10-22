# copy_prop.py - Copy Propagation (Compiler Design, BCSE307L)
# Propagates copy instructions forward and eliminates redundant copies

import blocks
import tac


# A store/load/address may clobber any address-taken variable, and a load has
# an unknown value, so copy propagation cannot look across memory operations.
_MEMORY_OPS = (tac.STORE_OPS | tac.LOAD_OPS | tac.ADDRESS_OPS) | {"ptrdiff"}


def _copy_prop_block(block):
    """Propagate copies within a single basic block"""
    env = {}  # var -> source
    out = []
    changes = 0
    
    for ins in block:
        op = ins.op
        before = ins
        
        if op == 'copy':
            src = ins.arg1
            dst = ins.result
            if isinstance(src, int):
                # copy const -> record constant
                env[dst] = src
            elif isinstance(src, str):
                # copy var -> record source (follow chain)
                while src in env and isinstance(env[src], str) and env[src] != src:
                    src = env[src]
                env[dst] = src
            out.append(ins)
            continue

        if op in _MEMORY_OPS:
            env.clear()
            out.append(ins)
            continue
        
        # Replace uses with propagated values
        new_ins = ins
        if op in tac.BINARY_OPS:
            a = env.get(ins.arg1, ins.arg1)
            b = env.get(ins.arg2, ins.arg2)
            if a != ins.arg1 or b != ins.arg2:
                new_ins = ins._replace(arg1=a, arg2=b)
        elif op in ('neg', 'not', 'bnot'):
            a = env.get(ins.arg1, ins.arg1)
            if a != ins.arg1:
                new_ins = ins._replace(arg1=a)
        elif op == 'ifFalse':
            a = env.get(ins.arg1, ins.arg1)
            if a != ins.arg1:
                new_ins = ins._replace(arg1=a)
        elif op in ('print', 'out_val'):
            a = env.get(ins.arg1, ins.arg1)
            if a != ins.arg1:
                new_ins = ins._replace(arg1=a)
        elif op == 'cast':
            a = env.get(ins.arg1, ins.arg1)
            if a != ins.arg1:
                new_ins = ins._replace(arg1=a)
        elif op == 'return':
            if ins.arg1 is not None:
                a = env.get(ins.arg1, ins.arg1)
                if a != ins.arg1:
                    new_ins = ins._replace(arg1=a)
        
        if new_ins != before:
            changes += 1
        
        # Update environment
        dst = tac.defs(new_ins)
        if dst is not None:
            # New definition kills previous propagated value
            if dst in env:
                del env[dst]
            # Also remove any mappings TO this dst
            for k in [k for k, v in env.items() if v == dst]:
                del env[k]
        
        out.append(new_ins)
    
    return out, changes


def copy_prop(instrs):
    """Copy propagation across all basic blocks"""
    blks = blocks.split_blocks(instrs)
    new_blks = []
    total_changes = 0
    
    for b in blks:
        new_b, ch = _copy_prop_block(b)
        new_blks.append(new_b)
        total_changes += ch
    
    return blocks.join_blocks(new_blks), total_changes