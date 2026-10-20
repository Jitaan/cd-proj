# tac.py - TAC instruction definition (MiniC)
from collections import namedtuple
Instr = namedtuple("Instr", "op a b dst")
BINARY_OPS = {"+","+","-","*","/","%","<",">","<=",">=","==","!=","&&","||"}
UNARY_OPS = {"neg","not"}
def is_const(x): return isinstance(x,int) and not isinstance(x,bool)
def is_var(x): return isinstance(x,str)
def is_temp(x): return isinstance(x,str) and __import__("re").fullmatch(r"t\d+",x) is not None
def uses(instr):
    op=instr.op
    if op in ("label","goto"): return set()
    if op=="ifFalse":
        s=set()
        if isinstance(instr.a,str): s.add(instr.a)
        return s
    if op=="print":
        s=set()
        if isinstance(instr.a,str): s.add(instr.a)
        return s
    if op=="copy":
        s=set()
        if isinstance(instr.a,str): s.add(instr.a)
        return s
    if op in ("neg","not"):
        s=set()
        if isinstance(instr.a,str): s.add(instr.a)
        return s
    if op in BINARY_OPS:
        s=set()
        if isinstance(instr.a,str): s.add(instr.a)
        if isinstance(instr.b,str): s.add(instr.b)
        return s
    return set()
def defs(instr):
    if instr.op in ("label","goto","ifFalse","print"): return None
    return instr.dst
def has_side_effect(instr):
    if instr.op in ("print","goto","ifFalse","label"): return True
    if instr.op in ("/","%"): return True
    return False
def eval_op(op,a,b):
    if op=="+": return a+b
    if op=="-": return a-b
    if op=="*": return a*b
    if op=="/":
        if b==0: return None
        q=abs(a)//abs(b)
        if (a<0)!=(b<0): q=-q
        return q
    if op=="%":
        if b==0: return None
        q=eval_op("/",a,b)
        return a-q*b
    if op=="<": return 1 if a<b else 0
    if op==">": return 1 if a>b else 0
    if op=="<=": return 1 if a<=b else 0
    if op==">=": return 1 if a>=b else 0
    if op=="==": return 1 if a==b else 0
    if op=="!=": return 1 if a!=b else 0
    if op=="&&": return 1 if (a!=0 and b!=0) else 0
    if op=="||": return 1 if (a!=0 or b!=0) else 0
    raise ValueError("unknown op %s"%op)
def eval_unary(op,a):
    if op=="-": return -a
    if op=="!": return 0 if a!=0 else 1
    if op=="neg": return -a
    if op=="not": return 0 if a!=0 else 1
    raise ValueError("unknown unary %s"%op)
def wrap32(x):
    x=x%(1<<32)
    if x>=(1<<31): x-=(1<<32)
    return x
def instr_str(i):
    op=i.op
    if op=="label": return "%s:"%i.a
    if op=="goto": return "goto %s"%i.a
    if op=="ifFalse": return "ifFalse %s goto %s"%(i.a,i.b)
    if op=="print": return "print %s"%i.a
    if op in ("neg","not"): return "%s = %s %s"%(i.dst,op,i.a)
    if op=="copy": return "%s = %s"%(i.dst,i.a)
    if op in BINARY_OPS: return "%s = %s %s %s"%(i.dst,i.a,op,i.b)
    return repr(i)
Instr.__str__=lambda self: instr_str(self)
