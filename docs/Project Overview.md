# MiniC TAC Optimizer — Detailed Project Documentation

## 1. Purpose
This project implements a compiler for a small C-like language ("MiniC") that
compiles to Three-Address Code (TAC), optimizes it, and verifies that the
optimized version produces identical output. It includes an AI-assisted pass
selector and a React frontend.

## 2. Architecture
Pipeline:
```
source.c -> lexer -> parser -> tacgen -> advisor -> passes -> interp -> report
```

## 3. Backend modules (in `backend/`)

### lexer.py
Master-regex tokenizer. Tokens are `(type, text, line)`. Skips whitespace,
comments, `#include`. Raises `LexError(line, char)`.

### parser.py
Recursive descent parser over the MiniC grammar. AST is plain tuples. Tracks
declared names in a flat scope. Raises `ParseError(line, msg)`.

### tac.py
`Instr = namedtuple('Instr', 'op a b dst')`. Shared semantics: `eval_op`,
`eval_unary`, `wrap32`. Pretty printer.

### tacgen.py
Syntax-directed translation from AST to TAC. Short-circuits `&&`/`||`.

### interp.py
Interpreter: `run(instrs, max_steps) -> (output_list, dynamic_count)`.
Truncating div/mod, step limit, uninitialized checks.

### blocks.py
Basic blocks, flow graph, liveness analysis. `split_blocks`, `join_blocks`,
`successors`, `liveness`, `reachable`, `predecessors`.

### passes.py
Optimization passes: `propagate_fold`, `alg`, `cse`, `cfg` (branch+unreach+peep),
`dce`. `optimise(instrs, enabled, log=None)` runs fixpoint. `PASSES`, `ORDER`,
`ADVISED`.

### cfgopt.py
`branch` (constant branch folding), `unreach` (unreachable code removal),
`peep` (peephole cleanup), `cfg` (composite).

### advisor.py
Feature extraction (11 features) and `recommend()` using a trained decision
tree. Loads `model.pkl`.

### progen.py
Random MiniC program generator for training data.

### train.py
Builds dataset, trains 3 decision trees (one per pass), saves `model.pkl`.

### service.py
Thin service layer: `run_pipeline`, `compare_modes`, `list_examples`,
`explain_model`. Returns dicts, never raises for user errors.

### api.py
HTTP API (stdlib) exposing service functions on port 8000.

## 4. Frontend (in `frontend/`)
React app (Vite) with dark mode. Calls the API. Features: source editor,
example dropdown, mode selector, Run / Generate TAC only buttons, metrics,
TAC before/after, trace, features.

## 5. How to run
1. `cd backend && python train.py` (once)
2. `cd backend && python api.py`
3. `cd frontend && npm run dev`
4. Open http://localhost:5173

## 6. Tests
```
python -m unittest discover -s tests
```

## 7. Key design decisions
- Hand-written lexer and parser (no external parser generators).
- Standard library only (except scikit-learn for the advisor).
- Passes are pure functions returning new lists.
- Interpreter is the correctness oracle; `main.py`/UI never keep wrong code.
- AI only recommends passes; correctness is verified independently.
