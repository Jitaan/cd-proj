# tacgen.py - MiniC TAC generator
import re
from tac import Instr
class TACGenError(Exception): pass
class TACGenerator:
    def __init__(self):
        self.temp_n=0; self.label_n=0; self.instrs=[]
    def new_temp(self):
        self.temp_n+=1; return "t%d"%self.temp_n
    def new_label(self):
        self.label_n+=1; return "L%d"%self.label_n
    def emit(self,i): self.instrs.append(i)
    def _check_name(self,name):
        if re.fullmatch(r"t\d+|L\d+",name): raise TACGenError("reserved")
    def gen(self,node):
        if isinstance(node,list):
            for s in node: self.gen_stmt(s)
            return self.instrs
        if isinstance(node,tuple):
            if node[0]=="block":
                for s in node[1]: self.gen_stmt(s)
                return self.instrs
            if node[0]=="program":
                for s in node[1]: self.gen_stmt(s)
                return self.instrs
        self.gen_stmt(node); return self.instrs
    def gen_stmt(self,node):
        kind=node[0]
        if kind=="decl":
            name=node[1]; self._check_name(name)
            init=node[2]
            if init is None: self.emit(Instr("copy",0,None,name))
            else:
                addr=self.gen_expr(init)
                self.emit(Instr("copy",addr,None,name))
        elif kind=="assign":
            name=node[1]; self._check_name(name)
            addr=self.gen_expr(node[2])
            self.emit(Instr("copy",addr,None,name))
        elif kind=="if":
            c=self.gen_expr(node[1]); then=node[2]; els=node[3]
            if els is None:
                le=self.new_label()
                self.emit(Instr("ifFalse",c,le,None))
                self.gen_stmt(then)
                self.emit(Instr("label",le,None,None))
            else:
                lelse=self.new_label(); lend=self.new_label()
                self.emit(Instr("ifFalse",c,lelse,None))
                self.gen_stmt(then)
                self.emit(Instr("goto",lend,None,None))
                self.emit(Instr("label",lelse,None,None))
                self.gen_stmt(els)
                self.emit(Instr("label",lend,None,None))
        elif kind=="while":
            lstart=self.new_label(); lend=self.new_label()
            self.emit(Instr("label",lstart,None,None))
            c=self.gen_expr(node[1])
            self.emit(Instr("ifFalse",c,lend,None))
            self.gen_stmt(node[2])
            self.emit(Instr("goto",lstart,None,None))
            self.emit(Instr("label",lend,None,None))
        elif kind=="for":
            self.gen_stmt(node[1])
            lstart=self.new_label(); lend=self.new_label()
            self.emit(Instr("label",lstart,None,None))
            c=self.gen_expr(node[2])
            self.emit(Instr("ifFalse",c,lend,None))
            self.gen_stmt(node[4])
            self.gen_stmt(node[3])
            self.emit(Instr("goto",lstart,None,None))
            self.emit(Instr("label",lend,None,None))
        elif kind=="print":
            addr=self.gen_expr(node[1])
            self.emit(Instr("print",addr,None,None))
        elif kind=="block":
            for s in node[1]: self.gen_stmt(s)
        elif kind=="return":
            return
        else:
            raise TACGenError("unknown stmt %s"%kind)
    def gen_expr(self,node):
        kind=node[0]
        if kind=="num": return node[1]
        if kind=="var": return node[1]
        if kind=="un":
            addr=self.gen_expr(node[2]); t=self.new_temp()
            if node[1]=="-": self.emit(Instr("neg",addr,None,t))
            elif node[1]=="!": self.emit(Instr("not",addr,None,t))
            return t
        if kind=="bin":
            op=node[1]; l=node[2]; r=node[3]
            if op=="&&":
                a_addr=self.gen_expr(l); lf=self.new_label(); le=self.new_label(); r_temp=self.new_temp()
                self.emit(Instr("ifFalse",a_addr,lf,None))
                b_addr=self.gen_expr(r)
                self.emit(Instr("ifFalse",b_addr,lf,None))
                self.emit(Instr("copy",1,None,r_temp))
                self.emit(Instr("goto",le,None,None))
                self.emit(Instr("label",lf,None,None))
                self.emit(Instr("copy",0,None,r_temp))
                self.emit(Instr("label",le,None,None))
                return r_temp
            if op=="||":
                a_addr=self.gen_expr(l); lcheck=self.new_label(); lf=self.new_label(); le=self.new_label(); r_temp=self.new_temp()
                self.emit(Instr("ifFalse",a_addr,lcheck,None))
                self.emit(Instr("copy",1,None,r_temp))
                self.emit(Instr("goto",le,None,None))
                self.emit(Instr("label",lcheck,None,None))
                b_addr=self.gen_expr(r)
                self.emit(Instr("ifFalse",b_addr,lf,None))
                self.emit(Instr("copy",1,None,r_temp))
                self.emit(Instr("goto",le,None,None))
                self.emit(Instr("label",lf,None,None))
                self.emit(Instr("copy",0,None,r_temp))
                self.emit(Instr("label",le,None,None))
                return r_temp
            a_addr=self.gen_expr(l); b_addr=self.gen_expr(r); t=self.new_temp()
            self.emit(Instr(op,a_addr,b_addr,t))
            return t
        raise TACGenError("unknown expr %s"%kind)
def generate(ast):
    g=TACGenerator(); return g.gen(ast)
