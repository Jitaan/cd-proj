# interp.py - MiniC TAC interpreter
def run(instrs, max_steps=1_000_000):
    label_map={}
    for idx,ins in enumerate(instrs):
        if ins.op=="label": label_map[ins.a]=idx
    env={}; output=[]; pc=0; steps=0; n=len(instrs)
    while pc<n:
        if steps>max_steps: raise RuntimeError("step limit")
        ins=instrs[pc]
        if ins.op=="label":
            pc+=1; continue
        steps+=1
        if steps>max_steps: raise RuntimeError("step limit")
        op=ins.op
        if op=="copy":
            src=ins.a
            if isinstance(src,str):
                if src not in env: raise RuntimeError("uninitialized")
                val=env[src]
            else: val=src
            env[ins.dst]=val; pc+=1
        elif op in ("neg","not"):
            a=ins.a
            if isinstance(a,str):
                if a not in env: raise RuntimeError("uninitialized")
                a=env[a]
            from tac import eval_unary
            if op=="neg": env[ins.dst]=eval_unary("-",a)
            else: env[ins.dst]=eval_unary("!",a)
            pc+=1
        elif op in ("+","-","*","/","%","<",">","<=",">=","==","!=","&&","||"):
            a=ins.a; b=ins.b
            if isinstance(a,str):
                if a not in env: raise RuntimeError("uninitialized")
                a=env[a]
            if isinstance(b,str):
                if b not in env: raise RuntimeError("uninitialized")
                b=env[b]
            from tac import eval_op
            if op in ("/","%") and b==0: raise RuntimeError("division by zero")
            res=eval_op(op,a,b)
            if res is None: raise RuntimeError("division by zero")
            env[ins.dst]=res; pc+=1
        elif op=="goto": pc=label_map[ins.a]
        elif op=="ifFalse":
            a=ins.a
            if isinstance(a,str):
                if a not in env: raise RuntimeError("uninitialized")
                a=env[a]
            if a==0: pc=label_map[ins.b]
            else: pc+=1
        elif op=="print":
            a=ins.a
            if isinstance(a,str):
                if a not in env: raise RuntimeError("uninitialized")
                a=env[a]
            output.append(a); pc+=1
        else:
            raise RuntimeError("unknown op %s"%op)
    return output,steps
