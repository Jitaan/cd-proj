# AI-Assisted TAC Optimizer (MiniC)

Pipeline: `source -> lexer -> parser (AST) -> tacgen (TAC) -> advisor -> passes -> interp (verify) -> report`

Run:
```
python main.py examples/const_fold.c
python main.py examples/const_fold.c --passes all
python main.py --benchmark examples/
python train.py
```

Modules: lexer.py, parser.py, tac.py, tacgen.py, interp.py, blocks.py, passes.py, advisor.py, progen.py, train.py, main.py.

ASCII pipeline:
```
source.c
  | lexer.py
  v
tokens
  | parser.py
  v
AST
  | tacgen.py
  v
TAC  ->  advisor.py (features + decision tree)  ->  passes.py (fold/cse/dce)  ->  interp.py (verify)  ->  report
```
