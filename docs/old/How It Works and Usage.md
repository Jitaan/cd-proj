# TAC Optimizer: How It Works and How to Use It

This document explains the compiler pipeline, every component, and how to use
the command-line tool and Python API. It covers both the original mini-language
(legacy mode) and the C front end (C1 + C2).

## 1. Overview

The project is a compiler for a C subset (plus a legacy integer-only mini-language)
that:

1. Preprocesses and parses source code into an AST.
2. Lowers the AST to **Three-Address Code (TAC)**.
3. Builds a **Control Flow Graph (CFG)** per function and runs **liveness analysis**.
4. Applies optimization passes (constant propagation, constant folding, algebraic
   simplification, common subexpression elimination, dead code elimination).
5. Verifies that the optimized code is equivalent to the original (and optionally
   agrees with `gcc`).
6. Reports metrics (instruction counts, weighted cost, dynamic steps).

Entry point: `compile_source(src, mode="c"|"legacy")` (see `compiler.py`).

## 2. Modes

- **C mode** (default for `.c` files): real C subset, multi-function, typed.
- **Legacy mode** (`--legacy` or `.src` files): the original integer-only
  mini-language, unchanged and still fully supported.

## 3. Supported C subset (C1 + C2)

Types: `char, signed char, unsigned char, short, unsigned short, int, unsigned,
long, unsigned long, long long, unsigned long long, void` (void only as return
type or empty param list). Sizes 8/16/32/64. `const` accepted and ignored.
No pointers, arrays, structs, floats, enums, typedefs, switch, goto, labels.

Statements: expression, empty `;`, block, `if/else`, `while`, `do/while`, `for`,
`break`, `continue`, `return`. Declarations anywhere in a block (C99) and in
`for` init.

Expressions: literals (decimal/hex/octal/char with suffixes), full precedence
including casts, ternary `?:`, compound assignments, `++`/`--`, bitwise,
shifts. `&&`, `||`, `?:` are **short-circuit**.

Preprocessor: comments, `#include` (ignored), object-like `#define`/`#undef`,
built-in macros (`INT_MAX`, ...). Function-like macros and conditionals are
unsupported and raise `UnsupportedFeatureError`.

I/O lowered at compile time: `printf` (format literal, subset of specifiers),
`scanf` (only `%d`-style with `&identifier`), `putchar`.

Functions: definitions, prototypes, recursion, mutual recursion, globals with
constant initializers. `main` returns exit code 0..255.

## 4. Project layout

```
project/
  frontend/   tokens.py  lexer.py  ast_nodes.py  parser.py  errors.py
              preprocess.py  c_lexer.py  c_types.py  c_ast.py  c_parser.py  c_sema.py
  ir/         tac.py  tac_generator.py  interpreter.py  cfg.py  liveness.py
              program.py  c_gen.py
  optimizer/  const_prop.py  const_fold.py  algebraic.py  cse.py  dce.py  pipeline.py
  eval/       metrics.py  verify.py  compare.py  gcc_check.py  randgen.py
  examples/   *.src  c/*.c
  cli.py  compiler.py  README.md
  docs/
```

## 5. Pipeline stages

### 5.1 Preprocessor (`frontend/preprocess.py`)

Strips `//` and `/* */` comments (preserving line numbers), handles `#include`,
object-like `#define`/`#undef`, built-in macros. Unsupported directives raise
`UnsupportedFeatureError`.

### 5.2Lexer

- Legacy: `frontend/lexer.py` — `Token`, `LexError`, `lex(source)`.
- C: `frontend/c_lexer.py` — `CToken`, `CLexer`, `lex_c(src)`. Tokens carry
  `line, col`. Integer literals carry a type tag.

### 5.3 Parser

- Legacy: `frontend/parser.py` — recursive descent, `parse(source)`.
- C: `frontend/c_parser.py` — `parse_c(src)`. Precedence climbing, casts,
  dangling else, `for` with declarations, functions/prototypes/globals.

### 5.4 Semantic analysis (`frontend/c_sema.py`)

Scopes, unique renaming (shadowing), type checking, builtins (printf/scanf/
putchar), function prototypes. Raises `SemanticError` / `UnsupportedFeatureError`.

### 5.5 Types (`frontend/c_types.py`)

`CType(bits, signed)` with `.tag` (`i8..i64`, `u8..u64`). Usual arithmetic
conversions, promotion to at least `int`.

### 5.6 TAC (`ir/tac.py`)

`Instr(op, arg1, arg2, result, ty="i32", args=())` is frozen.

Ops (additions over legacy): `& | ^ << >>`, `bnot`, `cast`, `call`, `return`,
`out_str`, `out_val`.

`ty` is the result type (arithmetic/bitwise/cast/copy/read) or the operand
type (comparisons decide signed vs unsigned). Result of comparisons is 0/1.

Helpers: `wrap(x, ty)`, `wrap32` (alias), `eval_binary(op, a, b, ty)` and
`eval_unary(op, a, ty)` return `(value, error)` where error is `div_by_zero`,
`div_overflow`, `bad_shift`, or None. `uses`, `defs`, `has_side_effect` are
driven by a per-op table (`uses(call)` = vars in `args`).

### 5.7 TAC generator

- Legacy: `ir/tac_generator.py` — `TACGenerator.generate(program)`.
- C: `ir/c_gen.py` — `CGenerator.generate(tu) -> Program`. Per-function temp/
  label counters. Inserts `cast` instructions on type mismatches. Lowers
  `printf`/`scanf`/`putchar` to `out_str`/`out_val`/`read`. Short-circuits
  `&&`, `||`, `?:`. Handles compound assignments and `++`/`--`.

### 5.8 Interpreter (`ir/interpreter.py`)

- `run(tac, ...)` — legacy wrapper.
- `run_program(prog, inputs, max_steps, max_depth)` — multi-function with frames,
  recursion, globals, `out_str`/`out_val` formatting, exit code 0..255.

`RunResult(output, stdout, exit_code, steps, op_counts, func_steps, error)`.

Errors: `div_by_zero`, `div_overflow`, `bad_shift`, `undefined_var`,
`step_limit`, `stack_overflow`, `input_exhausted`.

### 5.9 Program structure (`ir/program.py`)

`Function(name, params, ret_ty, body, var_types)` and
`Program(functions, globals)`. `Program.from_legacy(tac)` wraps flat TAC.

### 5.10 CFG and liveness

- `ir/cfg.py`: `build_cfg`, `flatten`, `to_dot`. `return` ends a block (no
  successors); leader created after it. `flatten(build_cfg(t)) == t`.
- `ir/liveness.py`: `analyze(cfg, exit_live, globals_set)`; `live_out_per_instr`.
  C mode passes globals as `exit_live`; `call`/`return` implicitly use all
  globals.

### 5.11 Pass context (`PassContext`)

`PassContext(globals, var_types)` passed to every pass. Legacy passes `ctx=None`
(no globals, all `i32`).

## 6. Optimization passes (`optimizer/`)

Pure functions returning new lists. Signatures: `pass(body, ctx=None)`.

| Pass | Key rules |
|------|-----------|
| Constant propagation | Deletes env entries mapping to/from a global at `call`; copy propagation only when types match; never rewrites `call` arg1, `out_str` arg1, `out_val` arg2. |
| Constant folding | Uses `eval_binary/eval_unary` with `ty`; does not fold on error; folds `cast` of constants and constant branches. |
| Algebraic simplification | Respects `ty`; skips `x-x`/`x*0` when `x` is a call result. |
| CSE | Key includes `ty`; `call` invalidates globals; never CSEs a call; `cast` is CSE-able. |
| DCE | Never removes `call`, `return`, `out_str`, `out_val`, `read`, jumps, labels; globals never dead; nulls dead call results. |

`pipeline.py`: `run_pipeline(target, pass_names, ...)` accepts a `list[Instr]`
(legacy) or a `Program` (optimizes each function independently, prunes
`var_types`). `PipelineResult(tac, applied, per_pass_counts, program)`.

Registry and sequences: `PASSES`, `NONE`, `ALL_FIXED`.

## 7. Evaluation (`eval/`)

### 7.1 Metrics (`eval/metrics.py`)

`COSTS` extended: `call` 5, `return` 1, `cast` 1, `bnot` 1, `& | ^ << >>` 1,
`out_str` 2, `out_val` 2. `compute_metrics(target, inputs)` (list or Program)
returns totals + `per_function`. `reduction_percent`.

### 7.2 Verification (`eval/verify.py`)

`verify_equivalent(original, optimized, input_sets)` compares `output`/`error`
(legacy) or `stdout`/`exit_code`/`error` (C). `step_limit` is inconclusive.

`generate_inputs(tac, n=20, seed=0)` — deterministic vectors; for C, counts
reads across all functions.

### 7.3 gcc differential (`eval/gcc_check.py`)

`have_gcc()`, `gcc_run(c_path, inputs) -> (stdout, exit_code)` using
`gcc -O0 -fwrapv -std=c99 -w`.

### 7.4 Comparison (`eval/compare.py`)

`compare(source, configs, inputs)` (legacy) and
`compare_program(prog, configs, inputs)` (C). `to_table()`, `to_dict()`.

## 8. Command-line usage

```
python cli.py FILE [--legacy] [--passes p1,p2,...] [--all] [--inputs 1,2,3]
                   [--show-tac] [--dump-ast] [--cfg-dot out.dot]
                   [--per-function] [--check-gcc]
```

- `.c` files use C mode by default; `.src` use legacy. `--legacy` forces legacy.
- Prints metrics table; exit code nonzero if verification fails.

Examples:

```
python cli.py examples/demo.src --all
python cli.py tmp.c --all --check-gcc
python cli.py examples/while_accumulator.src --cfg-dot cfg.dot
```

## 9. Python API

Legacy:
```python
from frontend.parser import parse
from ir.tac_generator import TACGenerator
from optimizer.pipeline import run_pipeline, ALL_FIXED
from eval.verify import verify_equivalent, generate_inputs

source = open("examples/demo.src").read()
tac = TACGenerator().generate(parse(source))
result = run_pipeline(tac, ALL_FIXED, to_fixpoint=True)
vr = verify_equivalent(tac, result.tac, generate_inputs(tac))
print("equivalent:", vr.ok)
```

C:
```python
from compiler import compile_source
from optimizer.pipeline import run_pipeline, ALL_FIXED
from eval.verify import verify_equivalent, generate_inputs

prog = compile_source(open("examples/c/factorial_rec.c").read(), mode="c")
result = run_pipeline(prog, ALL_FIXED, to_fixpoint=True)
vr = verify_equivalent(prog, result.program, generate_inputs(prog))
print("equivalent:", vr.ok, "exit:", run_program(result.program).exit_code)
```

## 10. Testing

```
pytest
```

Final gates:
- `pytest` fully green.
- `python cli.py examples/<each>.src --all` prints `verified: True`.
- `python cli.py examples/c/<each>.c --all --check-gcc` shows gcc agreement
  (when gcc is available).

## 11. Known pitfalls (verified)

- `uses/defs` must not read function names, strings, or specs as variables.
- C truncation for signed and unsigned; `wrap` with correct width.
- `ty` must be preserved on every rewritten instruction.
- C `&&`, `||`, `?:` are short-circuit.
- `continue` in `for` jumps to the step clause.
- Compound assignment evaluates its target once.
- Shadow renaming must cover params and `for` init scope.
- Recursion needs per-frame locals/temps.
- No UB in test programs (uninitialized reads, eval order, out-of-range shifts).
- `scanf` needs stdin fed in differential tests.

## 12. Out of scope (C3+)

Pointers, arrays, strings beyond printf formats, structs, enums, typedefs,
floating point, switch, goto, function pointers, function-like macros,
conditional preprocessing, other libc calls. Hooks left: typed frozen `Instr`,
per-function `Program`, `PassContext` for alias sets, op table in `tac.py`.
