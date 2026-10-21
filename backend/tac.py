# tac.py - TAC instruction definition (MiniC)
from collections import namedtuple
import re

# MiniC Instr - compatible with ir.tac.Instr
# Has properties a, b, dst that map to arg1, arg2, result
class Instr(namedtuple("Instr", "op arg1 arg2 result ty args op_relop", defaults=(None, None, None, "i32", (), None))):
    @property
    def a(self): return self.arg1
    @property
    def b(self): return self.arg2
    @property
    def dst(self): return self.result

BINARY_OPS = {"+","-","*","/","%","<",">","<=",">=","==","!=","&&","||","&","|","^","<<",">>","shl","if"}
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
    if op=="if":
        s=set()
        if isinstance(instr.arg1,str): s.add(instr.arg1)
        if isinstance(instr.arg2,str): s.add(instr.arg2)
        return s
    if op in ("print","out_val"):
        s=set()
        if isinstance(instr.a,str): s.add(instr.a)
        return s
    if op in ("copy","neg","not"):
        s=set()
        if isinstance(instr.a,str): s.add(instr.a)
        return s
    if op in BINARY_OPS:
        s=set()
        if isinstance(instr.a,str): s.add(instr.a)
        if isinstance(instr.b,str): s.add(instr.b)
        return s
    if op in ("out_str","return"):
        return set()
    if op == "param":
        s=set()
        if isinstance(instr.arg1,str): s.add(instr.arg1)
        return s
    if op == "call":
        # call uses the params stored by param instructions
        # but those are separate instructions, so call itself doesn't use vars directly
        return set()
    if op == "cast":
        s=set()
        if isinstance(instr.a,str): s.add(instr.a)
        return s
    return set()
def defs(instr):
    if instr.op in ("label","goto","ifFalse","if","print","out_val","out_str"): return None
    return instr.dst
def has_side_effect(instr):
    if instr.op in ("print","out_val","out_str","goto","ifFalse","if","label"): return True
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
    if op=="shl": return a << b
    if op=="<<":
        if b < 0 or b >= 32:
            return None
        return a << b
    if op==">>":
        if b < 0 or b >= 32:
            return None
        return a >> b
    if op=="&": return a & b
    if op=="|": return a | b
    if op=="^": return a ^ b
    if op=="&": return a & b
    if op=="|": return a | b
    if op=="^": return a ^ b
    raise ValueError("unknown op %s"%op)
def eval_unary(op,a,ty="i32"):
    if op=="-": return -a
    if op=="!": return 0 if a!=0 else 1
    if op=="neg": return -a
    if op=="not": return 0 if a!=0 else 1
    raise ValueError("unknown unary %s"%op)
def wrap32(x):
    x=x%(1<<32)
    if x>=(1<<31): x-=(1<<32)
    return x
def _escape_str(s):
    return s.replace('\\', '\\\\').replace('\n', '\\n').replace('\t', '\\t').replace('\r', '\\r').replace('"', '\\"')

def instr_str(i):
    op=i.op
    if op=="label": return "%s:"%i.arg1
    if op=="goto": return "goto %s"%i.arg1
    if op=="ifFalse": return "ifFalse %s goto %s"%(i.arg1,i.arg2)
    if op=="if": return "if %s %s %s goto %s"%(i.arg1, i.op_relop, i.arg2, i.result)
    if op=="print": return "print %s"%i.arg1
    if op=="out_val": return "out_val %s, %s"%(i.arg1,i.arg2)
    if op=="out_str": return 'out_str "%s"'%_escape_str(i.arg1)
    if op=="param":
        if getattr(i, 'ty', None) == "str":
            return 'param "%s"'%_escape_str(i.arg1)
        else:
            return "param %s"%i.arg1
    if op=="call":
        if i.result:
            return "%s = call %s, %d"%(i.result, i.arg1, i.arg2)
        else:
            return "call %s, %d"%(i.arg1, i.arg2)
    if op=="return":
        if i.arg1 is not None:
            return "return %s"%i.arg1
        else:
            return "return"
    if op in ("neg","not"): return "%s = %s %s"%(i.result,op,i.arg1)
    if op=="copy": return "%s = %s"%(i.result,i.arg1)
    if op in BINARY_OPS: return "%s = %s %s %s"%(i.result,i.arg1,op,i.arg2)
    return repr(i)
Instr.__str__=lambda self: instr_str(self)