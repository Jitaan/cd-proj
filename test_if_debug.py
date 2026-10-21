import sys, os
sys.path.insert(0, r'C:\data\cd-proj\backend')
from ir.c_gen import generate_c
from frontend.preprocess import preprocess
from frontend.c_lexer import lex_c
from frontend.c_parser import Parser
from frontend.c_sema import analyze

src = '''
int main() {
    int x = 5;
    int y = 3;
    int z;
    if (x > y) {
        z = x;
    } else {
        z = y;
    }
    printf("%d\n", z);
    return 0;
}
'''
processed = preprocess(src)
toks = lex_c(processed)
p = Parser(toks)
ast = p.parse_translation_unit()
typed_ast, sema = analyze(ast)
prog = generate_c(typed_ast)

fn = prog.main()
print('Function var_types:', fn.var_types)
print('Body:')
for i, ins in enumerate(fn.body):
    print(f'  {i}: {ins}')