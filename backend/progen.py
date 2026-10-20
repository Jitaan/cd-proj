# progen.py - random MiniC program generator
import random
_BINOPS=["+","-","*","/","%","<",">","<=",">=","==","!=","&&","||"]
_ARITH=["+","-","*"]
def _expr(rng,vars_,depth=0,const_only=False,reuse=None):
    if reuse and rng.random()<0.25 and reuse:
        return rng.choice(reuse)
    if depth>=3 or (vars_ and rng.random()<0.35):
        if const_only or (not vars_) or rng.random()<0.4:
            return str(rng.randint(0,9))
        return rng.choice(vars_)
    r=rng.random()
    if r<0.15:
        op=rng.choice(["-","!"])
        return "(%s %s)"%(op,_expr(rng,vars_,depth+1,const_only,reuse))
    if r<0.5:
        op=rng.choice(_BINOPS if not const_only else _ARITH)
        left=_expr(rng,vars_,depth+1,const_only,reuse)
        if op in ("/","%"):
            right=str(rng.randint(1,6))
        else:
            right=_expr(rng,vars_,depth+1,const_only,reuse)
        return "(%s %s %s)"%(left,op,right)
    if const_only or (not vars_) or rng.random()<0.4:
        return str(rng.randint(0,9))
    return rng.choice(vars_)
def generate(seed):
    rng=random.Random(seed)
    nvars=rng.randint(3,5)
    vars_=["v%d"%i for i in range(nvars)]
    const_prob=rng.random(); reuse_prob=rng.random(); dead_prob=rng.random()
    lines=[]
    for v in vars_:
        if rng.random()<0.6:
            e=_expr(rng,vars_,0,const_prob>0.5,None)
            lines.append("int %s = %s;"%(v,e))
        else:
            lines.append("int %s;"%v)
    reuse_list=[]
    stmts_target=rng.randint(8,25); stmt_count=0; loop_counter=0
    while stmt_count<stmts_target:
        r=rng.random()
        if r<0.5:
            v=rng.choice(vars_)
            const_only=(rng.random()<const_prob)
            e=_expr(rng,vars_,0,const_only,reuse_list if (rng.random()<reuse_prob) else None)
            if rng.random()<reuse_prob: reuse_list.append(e)
            lines.append("%s = %s;"%(v,e)); stmt_count+=1
        elif r<0.65:
            cond=_expr(rng,vars_,0,False,None)
            v=rng.choice(vars_); e=_expr(rng,vars_,0,const_prob>0.5,None)
            lines.append("if (%s) { %s = %s; }"%(cond,v,e)); stmt_count+=2
        elif r<0.75:
            n=rng.randint(2,6); lc="lc%d"%loop_counter; loop_counter+=1
            lines.append("for (int %s = 0; %s < %d; %s++) { %s = %s + 1; }"%(lc,lc,n,lc,rng.choice(vars_),rng.choice(vars_)))
            stmt_count+=1
        else:
            v=rng.choice(vars_); lines.append("%s += 1;"%v); stmt_count+=1
    nprints=rng.randint(1,3)
    for _ in range(nprints):
        lines.append("print(%s);"%rng.choice(vars_))
    return "\n".join(lines)+"\n"
