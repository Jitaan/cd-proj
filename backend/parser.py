# parser.py - MiniC parser
import re
class ParseError(Exception):
    def __init__(self,line,msg):
        self.line=line; self.msg=msg
        super().__init__("ParseError(%d, %s)"%(line,msg))
def _is_reserved(name): return re.fullmatch(r"t\d+|L\d+",name) is not None
class Parser:
    def __init__(self,tokens):
        self.toks=tokens; self.i=0; self.declared=set()
    def peek(self): return self.toks[self.i]
    def advance(self):
        t=self.toks[self.i]; self.i+=1; return t
    def expect(self,kind,value=None):
        t=self.peek()
        if t[0]!=kind or (value is not None and t[1]!=value):
            raise ParseError(t[2],"expected %r"%(value if value is not None else kind))
        return self.advance()
    def parse(self):
        toks=self.toks
        if (self.peek()[0]=="int" and self.i+1<len(toks) and toks[self.i+1][0]=="ID" and toks[self.i+1][1]=="main"):
            self.expect("int"); self.expect("ID","main"); self.expect("("); self.expect(")")
            return self.block()
        stmts=[]
        while self.peek()[0]!="EOF":
            stmts.append(self.stmt())
        return ("block",stmts)
    def block(self):
        self.expect("{")
        stmts=[]
        while self.peek()[0]!="}":
            if self.peek()[0]=="EOF": raise ParseError(self.peek()[2],"expected }")
            stmts.append(self.stmt())
        self.expect("}")
        return ("block",stmts)
    def stmt(self):
        t=self.peek()
        if t[0]=="int": return self.decl()
        if t[0]=="{": return self.block()
        if t[0]=="if": return self.if_stmt()
        if t[0]=="while": return self.while_stmt()
        if t[0]=="for": return self.for_stmt()
        if t[0] in ("print","printf"): return self.print_stmt()
        if t[0]=="return":
            self.advance(); e=self.expr(); self.expect(";"); return ("return",e)
        if t[0]=="ID":
            s=self.simple(); self.expect(";"); return s
        raise ParseError(t[2],"unexpected token %r"%(t[1],))
    def decl(self):
        self.expect("int")
        t=self.peek()
        if t[0]!="ID": raise ParseError(t[2],"expected identifier")
        name=t[1]
        if _is_reserved(name): raise ParseError(t[2],"reserved name")
        if name in self.declared: raise ParseError(t[2],"redeclared variable %s"%name)
        self.declared.add(name)
        self.advance()
        init=None
        if self.peek()[0]=="=":
            self.advance(); init=self.expr()
        self.expect(";")
        return ("decl",name,init)
    def simple(self):
        t=self.peek()
        if t[0]!="ID": raise ParseError(t[2],"expected identifier")
        name=t[1]
        if name not in self.declared: raise ParseError(t[2],"undeclared variable %s"%name)
        if _is_reserved(name): raise ParseError(t[2],"reserved name")
        self.advance()
        p=self.peek()
        if p[0]=="=":
            self.advance(); e=self.expr(); return ("assign",name,e)
        if p[0]=="+=":
            self.advance(); e=self.expr(); return ("assign",name,("bin","+",("var",name),e))
        if p[0]=="-=":
            self.advance(); e=self.expr(); return ("assign",name,("bin","-",("var",name),e))
        if p[0]=="*=":
            self.advance(); e=self.expr(); return ("assign",name,("bin","*",("var",name),e))
        if p[0]=="++":
            self.advance(); return ("assign",name,("bin","+","var",name) if False else ("assign",name,("bin","+",("var",name),("num",1))))
        if p[0]=="--":
            self.advance(); return ("assign",name,("bin","-",("var",name),("num",1)))
        raise ParseError(p[2],"expected assignment operator")
    def if_stmt(self):
        self.expect("if"); self.expect("("); c=self.expr(); self.expect(")")
        then=self.stmt(); els=None
        if self.peek()[0]=="else":
            self.advance(); els=self.stmt()
        return ("if",c,then,els)
    def while_stmt(self):
        self.expect("while"); self.expect("("); c=self.expr(); self.expect(")"); body=self.stmt()
        return ("while",c,body)
    def for_stmt(self):
        self.expect("for"); self.expect("(")
        if self.peek()[0]=="int":
            init=self.decl()
        else:
            init=self.simple(); self.expect(";")
        cond=self.expr(); self.expect(";")
        step=self.simple(); self.expect(")")
        body=self.stmt()
        return ("for",init,cond,step,body)
    def print_stmt(self):
        if self.peek()[0]=="printf":
            self.advance(); self.expect("(")
            fmt=self.peek()
            if fmt[0]!="STRING": raise ParseError(fmt[2],"expected format string")
            if fmt[1]!='"%d\\n"': raise ParseError(fmt[2],"unsupported format string")
            self.advance(); self.expect(","); e=self.expr(); self.expect(")"); self.expect(";")
            return ("print",e)
        self.advance(); self.expect("("); e=self.expr(); self.expect(")"); self.expect(";")
        return ("print",e)
    def expr(self): return self.or_expr()
    def or_expr(self):
        node=self.and_expr()
        while self.peek()[0]=="||":
            self.advance(); rhs=self.and_expr(); node=("bin","||",node,rhs)
        return node
    def and_expr(self):
        node=self.eq_expr()
        while self.peek()[0]=="&&":
            self.advance(); rhs=self.eq_expr(); node=("bin","&&",node,rhs)
        return node
    def eq_expr(self):
        node=self.rel_expr()
        while self.peek()[0] in ("==","!="):
            op=self.advance()[1]; rhs=self.rel_expr(); node=("bin",op,node,rhs)
        return node
    def rel_expr(self):
        node=self.add_expr()
        while self.peek()[0] in ("<",">","<=",">="):
            op=self.advance()[1]; rhs=self.add_expr(); node=("bin",op,node,rhs)
        return node
    def add_expr(self):
        node=self.mul_expr()
        while self.peek()[0] in ("+","-"):
            op=self.advance()[1]; rhs=self.mul_expr(); node=("bin",op,node,rhs)
        return node
    def mul_expr(self):
        node=self.unary()
        while self.peek()[0] in ("*","/","%"):
            op=self.advance()[1]; rhs=self.unary(); node=("bin",op,node,rhs)
        return node
    def unary(self):
        t=self.peek()
        if t[0] in ("-","!"):
            op=self.advance()[1]; e=self.unary(); return ("un",op,e)
        return self.primary()
    def primary(self):
        t=self.peek()
        if t[0]=="NUM":
            self.advance(); return ("num",int(t[1]))
        if t[0]=="ID":
            name=t[1]
            if name not in self.declared: raise ParseError(t[2],"undeclared variable %s"%name)
            self.advance(); return ("var",name)
        if t[0]=="(":
            self.advance(); e=self.expr(); self.expect(")"); return e
        raise ParseError(t[2],"expected expression")
def parse(source):
    from lexer import tokenize
    toks=tokenize(source)
    p=Parser(toks)
    return p.parse()
def parse_expr(source):
    from lexer import tokenize
    toks=tokenize(source)
    p=Parser(toks)
    names=set(t[1] for t in toks if t[0]=="ID")
    p.declared=names
    return p.expr()
