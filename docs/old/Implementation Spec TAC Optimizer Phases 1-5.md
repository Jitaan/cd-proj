# Implementation Spec: TAC Optimizer, Phases 1 to 5

This spec is for a coding model working in a harness. Follow it literally. Where it says MUST, tests must enforce it. The AI advisor (Phase 6) and UI (Phase 7) are out of scope here, but this spec leaves hooks for them.

## 0. Goal and ground rules

Build a compiler pipeline for a small C-like language:

```
Source -> Lexer -> Parser (AST) -> TAC Generator -> CFG + Liveness -> Optimization passes -> Metrics + Verification
```

**Rules**

1. Language: Python 3.10+. Standard library only for the core (`dataclasses`, `re`, `random`, `argparse`). Test with `pytest`. No other dependencies.
2. Source code is never mutated. TAC from the generator is the **original TAC** and is never mutated. Every optimization pass takes a TAC list and returns a **new** list.
3. Correctness beats optimization. If unsure whether a transform is safe, do not apply it.
4. Each milestone (Section 9) must have passing tests before moving to the next.
5. Every module has a docstring and type hints. Keep functions small and pure where possible.

## 1. Project layout

```
project/
  frontend/   tokens.py  lexer.py  ast_nodes.py  parser.py
  ir/         tac.py  tac_generator.py  interpreter.py  cfg.py  liveness.py
  optimizer/  const_prop.py  const_fold.py  algebraic.py  cse.py  dce.py  pipeline.py
  eval/       metrics.py  verify.py  compare.py
  examples/   *.src   (at least 15 sample programs)
  tests/      test_lexer.py test_parser.py test_tac_gen.py test_interpreter.py
              test_cfg.py test_liveness.py test_passes.py test_metrics.py test_equivalence.py
  cli.py      (thin command-line entry point)
  README.md
```

## 2. Phase 1: Front end

### 2.1 Language definition

A C-like subset. **Integer-only.**

**Grammar (EBNF)**

```
program    := [ "int" "main" "(" ")" ] block  |  stmt*
block      := "{" stmt* "}"
stmt       := decl | assign | read | print | if | while | for | block
decl       := "int" IDENT [ "=" expr ] ";"
assign     := IDENT "=" expr ";"
read       := "read" IDENT ";"
print      := "print" expr ";"
if         := "if" "(" expr ")" stmt [ "else" stmt ]
while      := "while" "(" expr ")" stmt
for        := "for" "(" assign_noterm ";" expr ";" assign_noterm ")" stmt
expr       := or_expr
or_expr    := and_expr  ( "||" and_expr )*
and_expr   := eq_expr   ( "&&" eq_expr )*
eq_expr    := rel_expr  ( ("==" | "!=") rel_expr )*
rel_expr   := add_expr  ( ("<" | ">" | "<=" | ">=") add_expr )*
add_expr   := mul_expr  ( ("+" | "-") mul_expr )*
mul_expr   := unary     ( ("*" | "/" | "%") unary )*
unary      := ("-" | "!") unary | primary
primary    := NUMBER | IDENT | "(" expr ")"
```

**Semantics**

- All values are Python `int` conceptually, but wrap to **32-bit signed** (two's complement) after every arithmetic result, to mimic C. Put the wrap in one shared function `wrap32(x)` in `ir/tac.py` used by both the interpreter and constant folding.
- `/` and `%` truncate toward zero (C semantics, **not** Python floor semantics). Division or modulo by zero is a runtime error in the interpreter.
- Comparisons and `!` yield `0` or `1`. Any nonzero value is true in conditions.
- `&&` and `||` are **not** short-circuit in this language (simplifies TAC). Document this in the README.
- Using a variable before assignment or `read` is a semantic error at generation time (simple def-before-use check on straight-line order is enough; undefined at runtime in the interpreter raises an error).
- `for` is **desugared in the parser** to `{ init; while (cond) { body; step } }`. No `For` AST node reaches the TAC generator.
- `int main()` wrapper is optional and ignored apart from parsing the block.
- Comments: `//` to end of line. Whitespace insignificant.

**Identifier rule:** identifiers match `[A-Za-z][A-Za-z0-9_]*`. They MUST NOT start with an underscore. Compiler temporaries are named `_t1, _t2, ...` and labels `L1, L2, ...`, so there can be no collisions.

### 2.2 Lexer (`frontend/lexer.py`)

- `Token(type, value, line, col)` dataclass.
- Token types: `NUMBER, IDENT, KEYWORD, OP, LPAREN, RPAREN, LBRACE, RBRACE, SEMI, EOF`.
- Keywords: `int main read print if else while for`.
- Multi-character operators (`<= >= == != && ||`) take priority over single-character ones.
- Raise `LexError(message, line, col)` on illegal characters.
- Skip comments and whitespace.

### 2.3 AST (`frontend/ast_nodes.py`)

Dataclasses: `Program(body)`, `Block(stmts)`, `Decl(name, init|None)`, `Assign(name, expr)`, `Read(name)`, `Print(expr)`, `If(cond, then, else_|None)`, `While(cond, body)`, `BinOp(op, left, right)`, `UnaryOp(op, operand)`, `Num(value)`, `Var(name)`. Each node stores `line`.

### 2.4 Parser (`frontend/parser.py`)

- Hand-written recursive descent, one function per grammar rule, precedence climbing via the layered expression rules above.
- All binary operators left-associative.
- Dangling else binds to the nearest `if`.
- Raise `ParseError(message, line, col)` with the expected token in the message.
- Provide `pretty_print(ast)` for debugging.

**Phase 1 acceptance**

- Lexer and parser tests for every grammar rule, precedence (`2+3*4`, `(2+3)*4`, `a-b-c`), the dangling else, the `for` desugaring, and at least 5 error cases (missing semicolon, unbalanced paren, bad character, etc.).
- All files in `examples/` parse.

## 3. Phase 2: TAC generation and interpreter

### 3.1 TAC representation (`ir/tac.py`)

Operands are either `int` (constant) or `str` (variable or temporary name).

```python
@dataclass(frozen=True)
class Instr:
    op: str                 # see table
    arg1: int | str | None = None
    arg2: int | str | None = None
    result: str | None = None   # destination var, or label name for label/goto/if_*
```

Frozen so passes can't mutate in place.

| op | Form | Meaning |
| --- | --- | --- |
| `+ - * / % < > <= >= == != && \|\|` | `result = arg1 op arg2` | binary |
| `neg`, `not` | `result = op arg1` | unary |
| `copy` | `result = arg1` | assignment or move |
| `label` | `result` = label name | jump target |
| `goto` | `result` = label name | unconditional jump |
| `if_false` | `arg1` = condition, `result` = label | jump if arg1 == 0 |
| `if_true` | `arg1` = condition, `result` = label | jump if arg1 != 0 |
| `read` | `result = read()` | take next input value |
| `print` | `arg1` | append value to output |

Provide `Instr.__str__` for readable output, e.g. `_t1 = 2 * 3`, `x = _t1`, `if_false _t2 goto L1`, `L1:`, `print x`.

Helpers in `tac.py`: `is_const(x)`, `is_var(x)`, `is_temp(x)`, `BINARY_OPS`, `UNARY_OPS`, `uses(instr) -> set[str]` (variables read), `defs(instr) -> str|None` (variable written), `has_side_effect(instr)` (true for `print`, `read`, `goto`, `if_*`, `label`, and division/modulo, see Section 5.5), `wrap32`, and `eval_binary(op, a, b)` / `eval_unary(op, a)` shared by interpreter and folder.

### 3.2 TAC generator (`ir/tac_generator.py`)

- Single class `TACGenerator` with `new_temp()` and `new_label()` counters, `generate(program) -> list[Instr]`.
- Expression visitor returns the operand holding the result (an int constant, a variable name, or a fresh temp). Do not pre-fold anything: `2 * 3` MUST emit `_t1 = 2 * 3`, so the original TAC is an honest unoptimized baseline.
- Assignment `a = expr` emits the expression code, then `copy`. To keep the baseline honest and simple: always compute into a temp then `copy` into the variable (`_t2 = _t1 + x` then `a = _t2`).
- Control flow:
  - `if (c) A else B` -> `cond code; if_false c goto Lelse; A; goto Lend; Lelse:; B; Lend:`
  - `if (c) A` -> `cond code; if_false c goto Lend; A; Lend:`
  - `while (c) B` -> `Lstart:; cond code; if_false c goto Lend; B; goto Lstart; Lend:`
- `read x` -> `read x`, `print e` -> eval `e`, then `print operand`.
- `Decl` without init emits nothing (just registers the name), with init behaves like assignment.
- Perform the def-before-use check and raise `SemanticError` otherwise.

### 3.3 Interpreter (`ir/interpreter.py`)

This is the **ground truth for correctness**. Build it before any optimizer.

```python
@dataclass
class RunResult:
    output: list[int]
    steps: int                 # dynamic instruction count (labels cost 0 steps)
    op_counts: dict[str, int]  # dynamic count per op, for weighted cost
    error: str | None          # None, "div_by_zero", "undefined_var", "step_limit", "input_exhausted"

def run(tac: list[Instr], inputs: list[int] = [], max_steps: int = 100_000) -> RunResult
```

- Pre-scan labels into a `label -> index` map. Program counter loop. Variables in a dict.
- Uses `wrap32`, C-style truncating division.
- On error, stop and return the partial output with `error` set (errors are part of observable behavior and compared in verification).
- `max_steps` guards infinite loops.

**Phase 2 acceptance**

- Golden tests: for each example program, the interpreter output equals a hand-computed expected output stored in `examples/expected/NAME.out` (or inlined in the test).
- Interpreter tests for: truncating division (`-7 / 2 == -3`, `-7 % 2 == -1`), 32-bit wraparound (`2147483647 + 1 == -2147483648`), div by zero, step limit, `read` consumption, loops, nested if.
- Generator tests that assert exact TAC text for 5 small programs, including one with `if/else` and one with `while`.
- Re-running the generator twice yields identical TAC (deterministic naming).

## 4. Phase 3: Analysis infrastructure

### 4.1 Basic blocks and CFG (`ir/cfg.py`)

- `BasicBlock(id, instrs, succs, preds)`; `CFG(blocks, entry, exit_ids)`.
- **Leaders:** the first instruction; any instruction that is a jump target (`label`); any instruction directly after a `goto`, `if_false`, or `if_true`.
- A block ends before the next leader or after a jump instruction.
- Edges: fallthrough to the next block (unless the block ends with `goto`); a jump edge to the target label's block; conditional jumps have both edges.
- `build_cfg(tac) -> CFG` and `flatten(cfg) -> list[Instr]` which reassembles blocks **in original order** into a TAC list. `flatten(build_cfg(t)) == t` MUST hold (property test over all examples).
- Optional: `to_dot(cfg) -> str` for Graphviz output.

### 4.2 Liveness analysis (`ir/liveness.py`)

Standard backward iterative dataflow on the CFG.

- Per block: `use[B]` (read before any write in B), `def[B]` (written in B).
- `live_out[B] = union(live_in[S] for S in succ(B))`, `live_in[B] = use[B] | (live_out[B] - def[B])`. Iterate to a fixed point using a worklist.
- Expose `live_out_per_instr(block, live_out_of_block) -> list[set[str]]`: the live set after each instruction in the block, computed by walking the block backward. DCE needs this.
- Treat `print`, `read`, jumps, and conditionals as using their `uses()` operands normally.

**Phase 3 acceptance**

- CFG tests for: straight-line code (1 block), if/else (4 blocks, diamond), while (loop back edge), nested loops.
- Round-trip property `flatten(build_cfg(t)) == t` on every example.
- Liveness tests on hand-worked examples, including a variable live across a loop back edge and a variable assigned but dead.

## 5. Phase 4: Optimization passes

### 5.1 Common contract (`optimizer/*.py`)

```python
def some_pass(tac: list[Instr]) -> list[Instr]   # pure: returns a new list, never mutates input
```

- Passes build the CFG internally, transform blocks, and flatten.
- **Local passes** (propagation, folding, algebraic, CSE) work **per basic block only**. State resets at every block start. This makes them safe with loops and branches without global dataflow.
- Each pass MUST preserve the observable behavior (output list and error) for all inputs.
- Registry in `pipeline.py`:

```python
PASSES = {
  "constant_propagation": const_prop,
  "constant_folding": const_fold,
  "algebraic": algebraic_simplify,
  "cse": cse,
  "dce": dce,
}
```

### 5.2 Constant and copy propagation (`const_prop.py`)

- Per block, keep `env: dict[str, int|str]` mapping a variable to a known constant, or to another variable it is a copy of.
- On `x = copy c` (constant) record `env[x] = c`. On `x = copy y` record `env[x] = env.get(y, y)` (copy propagation).
- Rewrite operands of each instruction using `env`.
- **Invalidation:** when a variable `v` is redefined, delete `env[v]` and delete every entry whose value is `v` (copies of `v`). `read` also defines its result.
- Do not propagate into `label`, and do not alter the target names of jumps.

### 5.3 Constant folding (`const_fold.py`)

- For a binary instruction with both operands constant, replace with `copy result, value` using `eval_binary` (shared `wrap32`, truncating division).
- Unary with constant operand likewise.
- **Do not fold** `/` or `%` when the divisor is 0. Leave the instruction so runtime behavior (error) is preserved.
- Fold conditional branches with constant conditions: `if_false 0 goto L` -> `goto L`; `if_false 1 goto L` -> removed. (The now-unreachable code is left in place unless unreachable-block removal, Section 5.7, is implemented.)

### 5.4 Algebraic simplification (`algebraic.py`) (optional, do after the core four)

`x+0, 0+x, x-0 -> x`; `x*1, 1*x, x/1 -> x`; `x*0, 0*x -> 0`; `x-x -> 0`; `x*2 -> x+x` (cost-model-visible strength reduction). Apply only when the result is exactly equal in this language's semantics. Do not apply `x/x -> 1` (x may be 0). Each rewrite produces a `copy`.

### 5.5 Common subexpression elimination (`cse.py`)

- Per block, table `avail: dict[(op, a, b), str]` mapping an expression to the variable that holds its value.
- For `r = a op b`: normalize commutative ops (`+ * == != && ||`) by sorting operands. If key is in `avail`, replace with `r = copy avail[key]`. Otherwise add after emitting.
- **Invalidation (the most common bug):** when variable `v` is defined, remove every `avail` entry where `v` appears as an operand **or** is the holder variable. Do this **before** recording the new instruction's own expression. Also handle the case where the instruction's result equals one of its own operands (`x = x + 1` must not be recorded as available).
- Division/modulo may be reused through CSE (same inputs, same error), that is safe. But never **remove** a division whose result is unused (see DCE).

### 5.6 Dead code elimination (`dce.py`)

- Uses global liveness (Section 4.2).
- For each block, walk instructions backward with the live set after each instruction. Remove an instruction if it defines a variable that is **not live afterward** and it has **no side effect**.
- **Side-effect instructions are never removed:** `print`, `read`, `goto`, `if_*`, `label`, and `/` or `%` instructions (their divide-by-zero error is observable). Simplest rule: removable ops are `copy`, `neg`, `not`, and binary ops other than `/` `%`.
- Iterate DCE to a fixed point (removing one instruction can kill another).
- Observable behavior is the `print` output stream and errors, so assignments to variables never subsequently used for output are dead.

### 5.7 Optional extras (stretch)

- Unreachable block removal (after folding constant branches).
- Jump-to-next-instruction removal and unused label removal (do this **last** in any pipeline so it doesn't break CFG assumptions).

### 5.8 Pipeline (`pipeline.py`)

```python
def run_pipeline(tac, pass_names: list[str], to_fixpoint: bool = False, max_iters: int = 10) -> PipelineResult

@dataclass
class PipelineResult:
    tac: list[Instr]
    applied: list[str]
    per_pass_counts: list[tuple[str, int]]   # (pass name, instruction count after that pass)
```

- Runs the named passes in order. With `to_fixpoint=True`, repeats the whole sequence until the TAC stops changing or `max_iters`.
- Unknown pass name -> `KeyError` with a helpful message.
- Predefined sequences exported as constants: `NONE = []`, `ALL_FIXED = ["constant_propagation", "constant_folding", "algebraic", "cse", "dce"]`. The Phase 6 advisor will produce lists of pass names that feed `run_pipeline`; no pipeline change needed then.

**Phase 4 acceptance**

- Per-pass unit tests with before/after TAC for: positive cases, and **negative cases that must NOT be optimized**: CSE after operand reassignment, propagation across a loop back edge, folding division by zero, DCE of a `print` or `read`, DCE of a variable live in a later block.
- Pass-interaction test: propagation + folding + DCE reduce `a = 4*5; d = a + 1; print d` to a single `print 21` (plus any retained copy the model documents).
- Idempotence check: running the full fixed-point pipeline twice equals running it once.
- Equivalence verification (Section 7) passes for every pass individually and every sequence in `ALL_FIXED` on every example.

## 6. Phase 5a: Metrics (`eval/metrics.py`)

```python
@dataclass
class Metrics:
    static_count: int         # instructions excluding labels
    weighted_cost: int        # static, using the cost table
    dynamic_count: int        # steps executed on given inputs (from interpreter)
    dynamic_cost: int         # weighted by op_counts
    temp_count: int           # distinct temporaries used
```

**Cost table** (single constant dict `COSTS`, easy to change):

| op | cost |
| --- | --- |
| `copy`, `neg`, `not`, `print`, `read` | 1 |
| `+ - < > <= >= == != && \|\|` | 1 |
| `*` | 3 |
| `/ %` | 5 |
| `goto`, `if_false`, `if_true` | 2 |
| `label` | 0 |

- `compute_metrics(tac, inputs) -> Metrics`. Dynamic metrics use the interpreter, so inputs are required for programs with `read`.
- `reduction_percent(before, after)` helper (guard against divide-by-zero).

## 7. Phase 5b: Verification (`eval/verify.py`)

```python
def verify_equivalent(original, optimized, input_sets: list[list[int]], max_steps=100_000) -> VerifyResult
```

- For each input set, run both with the interpreter. They MUST have identical `output` **and** identical `error` category. If the original hit `step_limit`, compare on outputs up to the limit and mark as inconclusive rather than failed.
- `generate_inputs(tac, n=20, seed=0)` -> deterministic list of input vectors: count the `read` instructions to determine vector length, include edge values (`0, 1, -1, 2147483647, -2147483648`) plus seeded random values in `[-100, 100]`.
- Return `VerifyResult(ok: bool, failures: list[(input, expected, actual)])`.
- This function is the safety net: the harness must call it for every pass in every test.

## 8. Phase 5c: Comparison (`eval/compare.py`) and CLI

```python
def compare(source: str, configs: dict[str, list[str]], inputs) -> ComparisonReport
```

- Compiles the source once to original TAC, then for each named config (e.g. `{"none": [], "all_fixed": ALL_FIXED}`) runs the pipeline, computes metrics, and verifies equivalence.
- Report holds, per config: optimized TAC, `Metrics`, `reduction_percent` for static count, weighted cost, dynamic count, and `verified: bool`.
- Phase 6 will add an `"ai"` config to this dict, so keep `configs` an open dict.
- `ComparisonReport.to_table() -> str` produces an aligned plain-text table, and `to_dict()` for JSON.

**CLI (`cli.py`)** with argparse:

```
python cli.py FILE.src [--passes p1,p2,...] [--all] [--inputs 1,2,3] [--show-tac] [--cfg-dot out.dot]
```

Prints the original TAC, optimized TAC, and the comparison table. Exit code non-zero if verification fails.

## 9. Milestones (execute in order)

| # | Deliverable | Gate (tests that must pass) |
| --- | --- | --- |
| M1 | Lexer, AST, parser, `examples/` | test\_lexer, test\_parser |
| M2 | TAC, generator, interpreter | test\_tac\_gen, test\_interpreter, golden outputs |
| M3 | CFG, liveness | test\_cfg, test\_liveness, round-trip property |
| M4a | const\_prop, const\_fold | per-pass tests + equivalence |
| M4b | cse, dce | per-pass tests + equivalence |
| M4c | pipeline, registry, fixpoint (algebraic optional) | test\_passes, idempotence |
| M5 | metrics, verify, compare, CLI | test\_metrics, test\_equivalence over all examples and all pass subsets |

Final gate: `pytest` is fully green, and `python cli.py examples/<each>.src --all` prints a table with `verified: True` for every example.

## 10. Required example programs (`examples/`)

At least 15 files covering: constant-heavy arithmetic; repeated subexpressions; dead assignments; a chain that needs propagation then folding then DCE; reassigned operands that block CSE (negative case); `if/else` diamond; `while` loop with accumulator; nested loop; loop-invariant repeated expression; division by a constant zero (must not fold); `read`-driven programs; a `for` loop; operator precedence stress; the demo program:

```c
int main() {
  int a = 4 * 5;
  int b = x + y;   // use read x; read y; before this line
  int c = x + y;
  int d = a + 1;
  print c;
}
```

## 11. Testing strategy summary

1. **Unit tests** per module (lexer, parser, generator, CFG, liveness, each pass, metrics).
2. **Golden tests:** fixed expected outputs for example programs.
3. **Differential testing (the key one):** for every example, every individual pass and every prefix/subset of `ALL_FIXED`, assert `verify_equivalent(original, optimized, generate_inputs(...))` is ok.
4. **Property tests (optional):** a small random straight-line program generator for fuzzing the passes against the interpreter. Seeded, so failures are reproducible. This generator is reused for Phase 6 training data, so write it as `eval/randgen.py` if time allows.
5. **Negative tests:** each documented pitfall in Sections 5.3, 5.5, 5.6 has a dedicated test.

## 12. Known pitfalls checklist (the model must verify each)

- CSE entry not invalidated after operand or holder reassignment.
- `x = x + 1` recorded as an available expression.
- Constant/copy propagation surviving past a redefinition of the source variable.
- Propagation or CSE state leaking across basic block boundaries (loops break).
- Folding `/ 0`; Python floor division instead of C truncation; missing 32-bit wrap.
- DCE removing `print`, `read`, jumps, or a division that could error.
- DCE using only local (per-block) liveness instead of global.
- Mutating the original TAC list in place.
- User identifiers colliding with temp names (solved by the underscore rule).
- Infinite loop in the interpreter without `max_steps`.

## 13. Out of scope for this spec

AI advisor and feature extraction (Phase 6), Streamlit UI and report (Phase 7), global optimizations (global CSE, loop-invariant code motion, SSA), functions, arrays, pointers, floats.

The only hooks required for later phases: the `PASSES` registry with string names, `run_pipeline(tac, pass_names)`, an open `configs` dict in `compare`, and a seeded random program generator if time allows.
