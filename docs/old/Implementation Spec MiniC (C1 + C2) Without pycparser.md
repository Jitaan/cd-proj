# Implementation Spec: MiniC Front End and Function Support (C1 + C2)

This spec extends the existing project (`cdproj`) so it compiles a **subset of real C**, using a **hand-written lexer and parser** (no pycparser). Follow it literally. MUST means a test must enforce it. Phases 1 to 5 of the original spec are already implemented; this spec lists only what changes.

## 0. Goals and ground rules

1. **Real C programs in the supported subset must compile, run in the interpreter, and give the same stdout and exit code as `gcc -O0 -fwrapv`.** gcc is the ground truth.
2. Anything outside the subset MUST raise `UnsupportedFeatureError(feature, line, col)`. Never silently mis-compile.
3. **Legacy mode stays alive.** The old mini-language, its parser, generator and tests are untouched and stay green. New code goes in new files. Entry point `compile_source(src, mode="c"|"legacy")`.
4. Python 3.10+, standard library only, pytest. gcc is required only by the differential tests (skip them with a clear message if `gcc` is not on PATH).
5. Source and original TAC are never mutated. Passes return new lists.
6. Each milestone (Section 9) must be green before the next begins.

## 1. Supported C subset

### 1.1 Types

`char, signed char, unsigned char, short, unsigned short, int, unsigned (int), long, unsigned long, long long, unsigned long long, void` (void only as a return type or an empty parameter list).

Sizes: char 8, short 16, int 32, long 64, long long 64. Canonical TAC type tags: `i8 i16 i32 i64 u8 u16 u32 u64`. Plain `char` is signed. `const` is accepted and ignored. `bool`, `float`, `double`, `enum`, `struct`, `union`, `typedef`, pointers, arrays: unsupported.

### 1.2 Declarations and statements

- Declarations with multiple declarators and initializers: `int a = 1, b, c = a + 2;`. Declarations may appear anywhere in a block (C99), and in the first clause of `for`.
- Block scoping with shadowing.
- Statements: expression statement, empty `;`, block, `if/else`, `while`, `do/while`, `for`, `break`, `continue`, `return`.
- Unsupported: `switch`, `goto`, labels, `static`, `extern`, `register`, `volatile`, `inline`, `sizeof`, comma operator (except in `for` clauses), compound literals, variable-length arrays.

### 1.3 Expressions

- Literals: decimal, hex (`0x1F`), octal (`017`), char (`'a'`, `'\\n'`, `'\\0'`, `'\\''`), suffixes `u`, `l`, `ul`, `ll`, `ull` (case-insensitive). String literals are allowed **only** as the format argument of `printf`/`scanf`.
- Operators by precedence (high to low): postfix `++ -- ()` call; unary `+ - ! ~ ++ --` and cast `(type)`; `* / %`; `+ -`; `<< >>`; `< <= > >=`; `== !=`; `&`; `^`; `|`; `&&`; `||`; `?:` (right-assoc); assignment `= += -= *= /= %= &= |= ^= <<= >>=` (right-assoc).
- `&&`, `||` and `?:` MUST **short-circuit**.
- Assignment, `++`, `--` are expressions with values. Prefix returns the new value, postfix the old.

### 1.4 Preprocessor (minimal, `frontend/preprocess.py`)

- Strip `//` and `/* */` comments, preserving line numbers.
- `#include <...>` and `#include "..."`: accepted and ignored.
- Object-like `#define NAME tokens` and `#undef NAME`, expanded at token level (recursion depth guard of 16, no expansion inside string literals).
- Built-in macros: `INT_MAX INT_MIN UINT_MAX LONG_MAX LONG_MIN CHAR_BIT EOF`.
- Function-like macros, `#if`, `#ifdef`, `#ifndef`, `#else`, `#endif`, `#pragma`, `#error`: `UnsupportedFeatureError`.

### 1.5 I/O (lowered at compile time, no libc)

- `printf("fmt", args...)`: format MUST be a literal. Supported specifiers: `%d %i %u %c %x %X %ld %lu %lld %llu %%`, with optional `0` flag and width (e.g. `%02d`, `%5d`). The front end splits the format into `out_str` and `out_val` instructions. Argument count must match the specifier count, else `SemanticError`. `printf` as a statement only (its return value cannot be used).
- `putchar(c)` -> `out_val c, "c"`.
- `scanf("%d", &x)`: statement only, format made of `%d %u %ld %c`-style specifiers separated by spaces, each argument a plain `&identifier`. Lowered to `read` instructions. This is the **only** place `&` is allowed.
- Anything else from libc (`malloc`, `strlen`, `abs`, ...) is an undeclared function error.

### 1.6 Functions (C2)

- Definitions with typed parameters, `void` or integer return, `int f(void)` and `int f()`.
- Prototypes (forward declarations), recursion, mutual recursion via prototypes.
- Global variables of integer type with constant-expression initializers (default 0).
- `main` is the entry. Only `int main(void)` and `int main()` are supported. Falling off the end of `main` returns 0. Exit code = main's return value masked to 0..255 (like a shell).
- Calls evaluate arguments **left to right** (document it; test programs must not depend on order, because gcc differs).

## 2. Pipeline and file layout

```
source.c -> preprocess -> c_lexer -> c_parser -> c_ast -> c_sema -> c_gen -> Program (functions of TAC)
```

New files (existing files are listed only when they change):

```
frontend/  preprocess.py  c_lexer.py  c_ast.py  c_types.py  c_parser.py  c_sema.py  errors.py
ir/        program.py  c_gen.py                       (new)
           tac.py  interpreter.py  cfg.py  liveness.py  (changed)
optimizer/ all passes + pipeline.py                   (changed)
eval/      metrics.py  verify.py  compare.py  gcc_check.py  randgen.py   (changed / new)
examples/c/  *.c  *.in  *.out                         (new, generated from gcc)
tests/     test_preprocess.py test_c_lexer.py test_c_parser.py test_c_sema.py test_c_gen.py
           test_calls.py test_c_passes.py test_gcc_diff.py
cli.py     (changed)
```

`frontend/errors.py` defines `LexError, ParseError, SemanticError, UnsupportedFeatureError`, each with `line, col`, all printed as `file:line:col: error: message`.

## 3. Changes to the IR (`ir/tac.py`, `ir/program.py`)

### 3.1 Instr gets two new fields

```python
@dataclass(frozen=True)
class Instr:
    op: str
    arg1: int | str | None = None
    arg2: int | str | None = None
    result: str | None = None
    ty: str = "i32"            # type tag, see below
    args: tuple = ()           # call arguments only
```

Defaults keep every legacy instruction valid.

**Meaning of `ty`:** for arithmetic, bitwise, shifts, `neg`, `not`, `~`, `copy`, `cast`, `read`: the **result type** (the value is wrapped to it). For comparison ops: the **operand type** (decides signed vs unsigned compare), while the result is always 0 or 1.

**Values are always stored in canonical range of their type.** The generator inserts conversions, so every binary instruction sees both operands already in `ty`. Therefore the interpreter needs no per-variable types.

### 3.2 Op table additions

| op | Form | Notes |
| --- | --- | --- |
| `& \| ^ << >>` | `result = arg1 op arg2` | new binary ops. `>>` is arithmetic for signed `ty`, logical for unsigned |
| `bnot` | `result = ~arg1` | unary |
| `cast` | `result = (ty) arg1` | wraps arg1 into `ty` |
| `call` | `result = call arg1(args...)` | `arg1` = function name (NOT a variable), `args` = tuple of operands, `result` may be None for void or ignored |
| `return` | `return arg1` | `arg1` None for void |
| `out_str` | `out_str arg1` | `arg1` is a Python str literal (NOT a variable) |
| `out_val` | `out_val arg1, arg2` | `arg1` operand, `arg2` format spec string such as `"d"`, `"u"`, `"c"`, `"x"`, `"02d"` (NOT a variable) |

Existing ops (`copy`, `label`, `goto`, `if_false`, `if_true`, `read`, `print`, arithmetic, comparisons) are unchanged. In C mode, `&&` and `||` binary ops are never emitted (they remain for legacy mode).

**`uses()` and `defs()` MUST be driven by a per-op table** stating which fields are operands, since `arg1` is sometimes a function name, a string, or a label. `uses(call)` = the variable names in `args`. `defs(call)` = `result`. A bug here silently breaks every pass.

### 3.3 Shared semantics (single source of truth in `tac.py`)

- `wrap(x, ty)`: reduce to the canonical range of `ty` (two's complement for signed). Keep `wrap32` as an alias for legacy.
- `eval_binary(op, a, b, ty)` and `eval_unary(op, a, ty)` return `(value, error)` where error is None or one of: `div_by_zero`, `div_overflow` (`INT_MIN / -1`), `bad_shift` (shift count negative or >= bit width). Division and modulo truncate toward zero. Unsigned types use unsigned division and comparison. The folder and the interpreter both call these.

### 3.4 Program structure (`ir/program.py`)

```python
@dataclass
class Function:
    name: str
    params: list[tuple[str, str]]       # (unique name, ty)
    ret_ty: str | None                  # None for void
    body: list[Instr]
    var_types: dict[str, str]           # every param, local and temp -> ty

@dataclass
class Program:
    functions: dict[str, Function]
    globals: dict[str, tuple[str, int]] # name -> (ty, initial value)
    # helper: all_instrs(), main()
```

Legacy compatibility: `Program.from_legacy(tac)` wraps a flat TAC list into a `Program` with one function `main`, all types `i32`, no globals.

## 4. Front end details

### 4.1 `c_lexer.py`

- Tokens with `line, col`: `KEYWORD, IDENT, INT_LIT (value, type tag), CHAR_LIT, STRING_LIT, OP, PUNCT, EOF`.
- Longest-match operators: `<<= >>= ++ -- += -= *= /= %= &= |= ^= <<= >>= << >> <= >= == != && ||`.
- Reject identifiers matching `_t[0-9]+` (reserved for compiler temporaries). Other identifiers, including a leading underscore, are fine.
- Integer literal typing (C rules, simplified): decimal without suffix is `i32` if it fits, else `i64`; hex and octal unsuffixed fit `i32`, then `u32`, then `i64`; `u` suffix gives unsigned; `l`/`ll` give 64-bit. Literal too large for u64: error.

### 4.2 `c_types.py`

- `parse_type_specifiers(list_of_keywords) -> CType` covering the legal combinations (`unsigned`, `unsigned int`, `long int`, `long long`, `signed char`, ...). Illegal combos: `SemanticError`.
- `CType(bits, signed)` with `.tag` (`"i32"`, `"u8"`, ...). `VOID` sentinel.
- **Usual arithmetic conversions** (`common_type(a, b)`), simplified: promote each operand to at least `int` (so char and short become `i32`); if either is 64-bit, result is 64-bit and unsigned if the 64-bit operand is unsigned (or both are 64-bit and either is unsigned); else if either is `u32`, result is `u32`; else `i32`.
- Shifts: result type is the promoted **left** operand only. `!`, comparisons, `&&`, `||` yield `i32`.

### 4.3 `c_ast.py` and `c_parser.py`

Nodes (each with `line`, `col`): `TranslationUnit`, `FuncDef`, `FuncDecl` (prototype), `GlobalVar`, `Block`, `VarDecl(ctype, name, init)`, `ExprStmt`, `If`, `While`, `DoWhile`, `For(init, cond, step, body)`, `Break`, `Continue`, `Return`, `Empty`, `BinOp`, `UnaryOp`, `Assign(op, target, value)`, `IncDec(op, prefix, target)`, `Ternary`, `Cast`, `Call(name, args)`, `IntLit`, `CharLit`, `Ident`, `StringLit`.

Parser: hand-written recursive descent, precedence climbing for the binary levels, one function per level. Rules:

- A statement or declaration starts as a declaration iff the next token is a type keyword or `const`.
- `(` followed by a type keyword begins a cast, otherwise a parenthesized expression.
- Unsupported keywords raise `UnsupportedFeatureError` **at the keyword**, with the feature name (`"switch"`, `"struct"`, `"pointer"` when `*` appears in a declarator, `"array"` when `[` appears in a declarator, etc.).
- `for` is NOT desugared (`continue` must jump to the step clause). Keep the `For` node.
- Dangling else binds to the nearest `if`. Expect-token errors name the expected token.
- Assignment targets must be identifiers (checked in sema).

### 4.4 `c_sema.py` (scopes, naming, type checking)

Produces an annotated tree (every expression node gets `.ctype`) and does:

- **Scope resolution with unique naming.** Maintain a scope stack. Each declared local or parameter gets a unique name: the source name if unused so far in this function **and not a global**, otherwise `name.1`, `name.2`, ... Every `Ident` is rewritten to its unique name or marked global. This lets all later stages treat names as unique.
- Errors: undeclared identifier, redeclaration in the same scope, assignment to a non-lvalue, `break`/`continue` outside a loop, call to an undeclared function, wrong argument count, void value used in an expression, `return` with a value in a void function or without a value in a non-void function, redefinition of a function, prototype/definition mismatch, missing `main`.
- Warnings (collected, not fatal): non-void function that can fall off the end.
- Global initializers must be constant expressions: fold them with `eval_binary` in sema.
- Use-before-initialization is **not** diagnosed (it is UB in C), the interpreter raises `undefined_var` at runtime.

## 5. Code generation (`ir/c_gen.py`)

Class `CGenerator` with `generate(tu) -> Program`. One `Function` per `FuncDef`, with its own temp and label counters (`_t1`, `L1`, reset per function, so a function's TAC is deterministic and independent).

- **No pre-folding.** `2 * 3` emits `_t1 = 2 * 3`, so the original TAC is an honest baseline. Literal conversion is the one exception: converting an `IntLit` to another integer type retypes the literal (`wrap(value, target)`) with no instruction.
- Expression visitor returns `(operand, ctype)`. Inserts a `cast` (or retyped literal) whenever the operand's type differs from the needed type: binary operands (common type), assignment, call arguments (to the parameter type), return value (to the return type). Record every temp's type in `var_types`.
- Assignment `a = e`: compute into a temp (or the converted operand), then `a = copy t` with `ty` = a's type.
- Compound assignment `a += e` lowers to `t = a + e` (in the common type), then cast and copy to `a`. `a` is evaluated once (it is an identifier, so no side effects).
- `++x` / `x--` etc. lower to add/sub of 1 plus copy. Postfix yields a copy of the old value taken first.
- **Short circuit:**

```
a && b  ->  if_false a goto Lf ; if_false b goto Lf ; r = copy 1 ; goto Le ; Lf: ; r = copy 0 ; Le:
a || b  ->  if_true a goto Lt ; if_true b goto Lt ; r = copy 0 ; goto Le ; Lt: ; r = copy 1 ; Le:
c ? x : y -> if_false c goto Lelse ; r = x ; goto Le ; Lelse: ; r = y ; Le:   (r has the common type)
```

- Control flow uses the legacy patterns. Maintain a **loop stack** of `(continue_label, break_label)`:
  - `while`: `Ls: cond; if_false c goto Le; body; goto Ls; Le:` (continue -> Ls)
  - `do/while`: `Ls: body; Lc: cond; if_true c goto Ls; Le:` (continue -> Lc)
  - `for`: `init; Ls: cond; if_false c goto Le; body; Lc: step; goto Ls; Le:` (continue -> Lc). An empty condition means always true.
- `printf`: for each format segment emit `out_str "text"` and for each specifier `out_val operand, spec` (operand cast to the specifier's type: `%d` to `i32`, `%u` to `u32`, `%ld` to `i64`, `%c` to `i32` then low 8 bits when printed). Merge adjacent text into one `out_str`.
- `scanf("%d", &x)`: `read x` with `ty` of x. A `%c` consumes one input value too (inputs are integers, see Section 6).
- `return e` -> convert to ret type, `return operand`. A function whose body can fall off the end gets an implicit `return 0` (non-void) or `return` (void) appended.
- Calls: evaluate arguments left to right into operands, converted to parameter types, then `result = call f(args)` (result typed to the return type). A call statement with unused result still emits `result = None`.
- Globals are referenced by their name directly. Function-local names never collide with globals (sema renaming).

## 6. Interpreter changes (`ir/interpreter.py`)

```python
def run_program(prog: Program, inputs: list[int] = [], max_steps=1_000_000, max_depth=1000) -> RunResult
def run(tac, inputs=[], max_steps=100_000) -> RunResult   # legacy wrapper: Program.from_legacy
```

```python
@dataclass
class RunResult:
    output: list[int]        # legacy print values
    stdout: str              # all out_str / out_val / legacy print text
    exit_code: int | None
    steps: int
    op_counts: dict[str, int]
    func_steps: dict[str, int]
    error: str | None        # div_by_zero, div_overflow, bad_shift, undefined_var,
                             # step_limit, stack_overflow, input_exhausted
```

- Globals dict initialized from `Program.globals`. Each call creates a new frame (locals dict); parameters are bound by position. `max_depth` guards recursion (`stack_overflow`).
- Legacy `print x` appends `x` to `output` and `f"{x}\\n"` to `stdout`.
- `out_val` formatting: `d i` signed decimal, `u` unsigned decimal, `x` / `X` hex of the value masked to the instruction's type width (for `u32`: 32 bits, for negatives printed by `%x` use the `u32` mask), `c` the character `chr(value & 0xFF)`, width and `0` flag handled like C.
- `read` consumes the next integer from `inputs`, wrapped to the instruction's `ty`. Empty -> `input_exhausted`.
- Labels cost 0 steps. `call` and `return` cost 1 step each. `steps` is global across all frames.
- Falling off `main` yields exit code 0. A runtime error stops execution and returns partial output with `error` set.

## 7. Analysis and optimizer changes

### 7.1 CFG and liveness (per function)

- `build_cfg(body)` is called per function. `return` ends a block and the block has **no successors** (it is an exit block). A leader is also created after a `return`. `flatten(build_cfg(t)) == t` still MUST hold.
- `liveness(cfg, ctx)` takes an `exit_live` set. For C mode `exit_live` = all global names. Additionally, **a `call` implicitly uses all globals** and **a `return` implicitly uses all globals** (the callee or caller may read them), so global assignments are never dead.
- `PassContext(globals: set[str], var_types: dict[str, str])` is passed to every pass. Legacy calls pass `ctx=None`, meaning no globals and all `i32`.

### 7.2 Pass signature and pipeline

```python
def some_pass(body: list[Instr], ctx: PassContext | None = None) -> list[Instr]
def run_pipeline(target, pass_names, to_fixpoint=False, max_iters=10)
```

`target` is a `list[Instr]` (legacy) or a `Program` (then each function is optimized independently and a new `Program` is returned, with `var_types` pruned of removed names). `PipelineResult` also reports per-function counts.

### 7.3 Pass rules (additions to the original rules)

- **const\_prop:** at a `call`, delete every `env` entry that maps **to or from a global**. Constant propagation records `env[x] = wrap(c, type_of(x))`. **Copy** propagation (`x = copy y`) is only allowed when `type_of(x) == type_of(y)`, otherwise skip it. Never rewrite `call` arg1 (the function name), `out_str` arg1, or `out_val` arg2 (spec). Operands inside `args` and `out_val` arg1 are propagated normally.
- **const\_fold:** uses `eval_binary(op, a, b, ty)`. If it returns an error, DO NOT fold (div by zero, `INT_MIN / -1`, bad shift). Fold `cast` of a constant. Fold branch conditions as before.
- **algebraic:** all rewrites must respect `ty` (for example `x * 2 -> x + x` stays in `ty`, `x << 1` only when the shift is valid for the width). Do not rewrite `x - x` or `x * 0` when `x` could be a call result with side effects (the call itself stays, only the arithmetic is rewritten).
- **cse:** the key is `(op, a, b, ty)`. At a `call`, invalidate every available expression that mentions a global operand or whose holder is a global. Never treat a `call` as a CSE-able expression. `cast` is CSE-able.
- **dce:** never removes `call`, `return`, `out_str`, `out_val`, `read`, jumps, or labels. Assignments to globals are never removed. Division, modulo, and shifts with variable counts stay (they can raise errors). A `call` whose result is dead stays, with `result` set to None. Fixed point iteration as before.
- **All passes:** work per function, per basic block for the local ones. `call` is a barrier for global-related state only, since locals cannot be modified by a callee (no pointers in this subset). Preserve `ty` and `args` on every rewritten instruction.
- **Stretch (only after everything else is green):** `purity` analysis (a function that writes no globals, does no I/O, and calls only pure functions) allowing CSE of calls and DCE of dead pure calls; a small inliner for non-recursive leaf functions.

## 8. Evaluation changes

- **`metrics.py`:** extra costs in `COSTS`: `call` 5, `return` 1, `cast` 1, `bnot` 1, `& | ^ << >>` 1, `out_str` 2, `out_val` 2. `compute_metrics(program, inputs)` returns totals and per-function static counts. Dynamic metrics come from `RunResult.op_counts` and `func_steps`.
- **`verify.py`:** `verify_equivalent` compares `stdout`, `exit_code`, and the `error` category (inconclusive on `step_limit`, as before). `generate_inputs` handles programs with `read` by counting reads in `main` plus callees (use a generous vector length of 8 and edge values).
- **`gcc_check.py`:** `gcc_run(c_path, inputs) -> (stdout, exit_code)` using `gcc -O0 -fwrapv -std=c99 -w`, running with `inputs` joined by newlines on stdin, 5 second timeout, temp directory cleanup. `have_gcc()` for skipping.
- **`compare.py`:** accepts a Program, the same open `configs` dict, plus an optional `gcc` column showing the gcc agreement of the **original** TAC. Phase 6 will add an `"ai"` config with no changes here.
- **`cli.py`:** `.c` files use C mode by default. `--legacy` for the mini-language, `--dump-ast`, `--show-tac` (per function), `--per-function` metrics, `--check-gcc`.

## 9. Milestones

| # | Deliverable | Gate |
| --- | --- | --- |
| C0 | `Instr.ty/args`, `Program`, `uses/defs` op table, `run_program`, per-function CFG with `return`, `PassContext`, pipeline over Programs | **All existing tests still green**. New tests with hand-built Programs: a call, recursion (factorial), a global counter, `stack_overflow` |
| C1a | `preprocess`, `c_lexer`, `c_types` | test\_preprocess, test\_c\_lexer (literals, suffixes, operators, macros, error positions) |
| C1b | `c_ast`, `c_parser`, `c_sema` for scalar code (no functions except `main`) | test\_c\_parser (precedence, casts, dangling else, `for` with declaration), test\_c\_sema (scopes, shadow renaming, each error case), every unsupported feature raises `UnsupportedFeatureError` |
| C1c | `c_gen` scalar, `printf`/`scanf`/`putchar` lowering | 10+ examples in `examples/c/` whose **original-TAC interpreter output equals gcc** |
| C2a | Functions: prototypes, params, returns, recursion, globals in parser, sema, gen, interpreter | factorial, fibonacci, gcd, mutual recursion (`is_even`/`is_odd`), void function modifying a global: all match gcc |
| C2b | Pass updates (Section 7.3), types in folding, call barriers | per-pass tests incl. negatives below, then every single pass and every subset of `ALL_FIXED` verified on every example |
| C2c | Metrics, verify, compare, gcc\_check, CLI, README (supported subset table, limitations, UB notes) | Full `pytest` green. `python cli.py examples/c/X.c --all --check-gcc` shows `verified: True` and gcc agreement for each example |

## 10. Examples (`examples/c/`, at least 22)

Each `NAME.c` has an optional `NAME.in` (whitespace separated inputs) and a `NAME.out` golden file **generated once by gcc**.

Scalar: `sum_to_n`, `prime_check`, `collatz_steps`, `digit_sum`, `reverse_number`, `power_loop`, `bit_tricks` (shifts, masks, `~`), `unsigned_wrap`, `char_arith`, `ternary_chain`, `short_circuit_guard` (`y != 0 && x / y > 1`), `nested_loops`, `break_continue`, `do_while`, `loop_invariant`, `repeated_subexpr`, `dead_assignments`, `const_heavy`, `macro_constants`, `compound_ops` (`+= <<= ++ --`).

Functions: `factorial_rec`, `fibonacci_rec`, `gcd_iter_and_rec`, `power_fn`, `is_even_odd_mutual`, `global_counter` (call modifies a global between two identical expressions: the CSE negative test), `call_in_loop`, `void_print_fn`, `shadowing`, `main_returns_code`.

Also add a small `randgen.py` extension that emits random C programs (scalar ops, loops, one helper function), seeded, no UB, usable for fuzzing the passes and later as Phase 6 training data.

## 11. Required negative tests (each is a dedicated test)

1. CSE across a call that modifies a global (`g_counter`).
2. Constant propagation of a global across a call.
3. DCE of an assignment to a global that is only read by a later call.
4. DCE of a `call` whose result is unused.
5. Copy propagation between variables of different types (`char c = i;`).
6. Folding `INT_MIN / -1`, `x / 0`, `1 << 40` (must remain as instructions).
7. Unsigned comparison vs signed comparison (`(unsigned)-1 > 0`).
8. Short-circuit: `p && 10 / p` with `p = 0` must not trap, in the original and in every optimized version.
9. `continue` inside `for` still executes the step clause.
10. Shadowed variable (`x` in an inner block) is not confused with the outer `x` by any pass.
11. Printf output unchanged by every pass, including `%x` of negative values and `%c`.
12. `x = x + 1` is never recorded as an available expression.

## 12. Pitfalls checklist

- `uses/defs` reading a function name, string, or spec as a variable (Section 3.2).
- Python floor division or modulo instead of C truncation, for signed **and** unsigned.
- Forgetting to wrap after every instruction, or wrapping with the wrong width for `char` and `short` (promotion makes arithmetic `i32`, only the store back to the variable narrows).
- Missing `ty` on rewritten instructions in a pass (defaults silently become `i32`).
- Treating C `&&`, `||`, `?:` as eager.
- `continue` in `for` jumping to the condition instead of the step.
- Evaluating `a` twice in `a += e` when sema or gen hoists side effects (identifiers have none, but keep it single).
- Test programs with UB or unspecified behavior (uninitialized reads, argument evaluation order, signed shifts past the width, `INT_MIN / -1`). The differential tests will fail for the wrong reason.
- Shadow renaming forgetting parameters or the `for` init scope.
- Recursion: temps and variables must be per frame, not shared.
- Reading gcc output for programs that need `scanf` without feeding stdin.

## 13. Out of scope (C3 and beyond)

Pointers, arrays, strings beyond `printf` formats, `struct`, `enum`, `typedef`, floating point, `switch`, `goto`, function pointers, function-like macros, conditional preprocessing, library calls other than `printf`, `scanf`, `putchar`.

Design hooks left for C3: `Instr` is frozen and typed, `Program` is per-function, `PassContext` is the place to add an alias set (address-taken variables), and the op table in `tac.py` is the one place to add `addr`, `load`, `store`.
