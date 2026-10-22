# service.py - thin service layer for the UI (Compiler Design, BCSE307L).
# No printing, no sys.exit. One function run_pipeline() does everything.

import os
import difflib

import advisor
import blocks
import passes
from lexer import tokenize, LexError
from parser import parse, ParseError
from tacgen import generate
from interp import run as run_tac


def _count_nonlabel(instrs):
    return sum(1 for i in instrs if i.op != "label")


def list_examples():
    out = {}
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "examples")
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".c"):
                out[fn] = open(os.path.join(d, fn)).read()
    return out


def explain_model():
    try:
        import pickle
        base = os.path.dirname(os.path.abspath(__file__))
        m = pickle.load(open(os.path.join(base, "model.pkl"), "rb"))
    except Exception:
        return {}
    out = {}
    for p in passes.ADVISED:
        clf = m.get(p, None)
        if isinstance(clf, int):
            out[p] = "constant predictor: %d" % clf
        else:
            try:
                from sklearn.tree import export_text
                out[p] = export_text(clf, feature_names=m.get("features", []))
            except Exception:
                out[p] = str(clf)
    return out


def _run_one(source, mode, passes_list=None):
    result = {
        "ok": True,
        "error": None,
        "tokens": [],
        "ast": "",
        "typed_ast": "",
        "tac_before": [],
        "tac_after": [],
        "features": {},
        "recommended": [],
        "predictions": {},
        "passes_run": [],
        "trace": [],
        "metrics": {"static_before": 0, "static_after": 0,
                    "dynamic_before": 0, "dynamic_after": 0},
        "output_before": [],
        "output_after": [],
        "match": False,
    }
    # size guard
    if len(source) > 20000 or source.count("\n") > 300:
        result["ok"] = False
        result["error"] = {"stage": "lex", "line": None, "col": None,
                           "msg": "source too large (max 300 lines / 20000 chars)"}
        return result
    # lex
    try:
        toks = tokenize(source)
    except LexError as e:
        result["ok"] = False
        result["error"] = {"stage": "lex", "line": getattr(e, "line", None), "col": getattr(e, "col", None), "msg": str(e)}
        return result
    result["tokens"] = [(t[0], t[1], t[2]) for t in toks]
    # parse
    try:
        from parser import parse
        ast = parse(source)
    except Exception as e:
        result["ok"] = False
        result["error"] = {"stage": "parse", "line": getattr(e, "line", None), "col": getattr(e, "col", None), "msg": str(e)}
        result["tokens"] = [(t[0], t[1], t[2]) for t in toks]
        return result
    result["ast"] = str(ast)
    result["typed_ast"] = str(ast)  # no separate typed AST in this project
    # tacgen
    try:
        tac_before = generate(ast)
    except Exception as e:
        result["ok"] = False
        result["error"] = {"stage": "sema", "line": getattr(e, "line", None), "col": getattr(e, "col", None), "msg": str(e)}
        return result
    result["tac_before"] = [str(i) for i in tac_before]
    # run original
    try:
        out_before, dyn_before = run_tac(tac_before)
    except Exception as e:
        result["ok"] = False
        result["error"] = {"stage": "runtime", "line": None, "col": None, "msg": str(e)}
        result["tac_before"] = [str(i) for i in tac_before]
        return result
    result["output_before"] = [str(x) for x in out_before]
    # advisor
    recommended = []
    predictions = {}
    try:
        recommended, expl = advisor.recommend(tac_before)
        predictions = expl.get("predictions", {})
        result["features"] = expl.get("features", {})
    except Exception as e:
        # model missing -> error in ai mode handled below; still continue
        if mode == "ai":
            result["ok"] = False
            result["error"] = {"stage": "advisor", "line": None, "col": None, "msg": str(e)}
            return result
    result["recommended"] = sorted(recommended)
    # decide passes to run
    if mode == "ai":
        enabled = set(recommended)
    elif mode == "all":
        enabled = set(passes.ADVISED)
    elif mode in ("none", "tac"):
        enabled = set()
    elif mode == "custom":
        enabled = set(passes_list or [])
    else:
        enabled = set()
    result["passes_run"] = sorted(enabled)
    # optimise
    log = []
    try:
        tac_after = passes.optimise(tac_before, enabled, log=log)
    except Exception as e:
        result["ok"] = False
        result["error"] = {"stage": "optimize", "line": None, "col": None, "msg": str(e)}
        return result
    result["tac_after"] = [str(i) for i in tac_after]
    result["trace"] = list(log)
    # run optimized
    try:
        out_after, dyn_after = run_tac(tac_after)
    except Exception as e:
        result["ok"] = False
        result["error"] = {"stage": "runtime", "line": None, "col": None, "msg": str(e)}
        result["output_after"] = []
        result["match"] = False
        return result
    result["output_after"] = [str(x) for x in out_after]
    result["match"] = (out_before == out_after)
    result["metrics"] = {
        "static_before": _count_nonlabel(tac_before),
        "static_after": _count_nonlabel(tac_after),
        "dynamic_before": dyn_before,
        "dynamic_after": dyn_after,
    }
    if not result["match"]:
        result["ok"] = False
        result["error"] = {"stage": "verify", "line": None, "col": None,
                           "msg": "outputs differ"}
    return result


def _run_c(source, mode, passes_list):
    result = {"ok": True, "error": None, "tokens": [], "ast": "", "typed_ast": "",
              "tac_before": [], "tac_after": [], "features": {}, "recommended": [],
              "predictions": {}, "passes_run": [], "trace": [],
              "metrics": {"static_before": 0, "static_after": 0,
                          "dynamic_before": 0, "dynamic_after": 0},
              "output_before": [], "output_after": [], "match": False}
    # size guard
    if len(source) > 20000 or source.count("\n") > 300:
        result["ok"] = False
        result["error"] = {"stage": "lex", "line": None,
                           "msg": "source too large (max 300 lines / 20000 chars)"}
        return result
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "frontend"))
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "ir"))
        from preprocess import preprocess, PreprocessError
        from c_lexer import lex_c, CLexError
        from c_parser import Parser, CParseError
        from c_sema import analyze, SemanticError
        from ir.c_gen import generate_c
        from ir.interpreter import run_program
        from ir.program import Program
        
        # preprocess
        try:
            processed = preprocess(source)
        except PreprocessError as e:
            result["ok"] = False
            result["error"] = {"stage": "preprocess", "line": e.line, "col": 1, "msg": e.msg}
            return result
        
        # lex
        try:
            toks = lex_c(processed)
        except CLexError as e:
            result["ok"] = False
            result["error"] = {"stage": "lex", "line": e.line, "col": e.col, "msg": e.msg}
            return result
        result["tokens"] = [(t.kind, t.value, t.line, t.col) for t in toks]
        
        # parse
        try:
            p = Parser(toks)
            ast = p.parse_translation_unit()
        except CParseError as e:
            result["ok"] = False
            result["error"] = {"stage": "parse", "line": e.line, "col": e.col, "msg": e.msg}
            return result
        result["ast"] = str(ast)
        
        # semantic analysis
        try:
            typed_ast, sema = analyze(ast)
        except SemanticError as e:
            result["ok"] = False
            result["error"] = {"stage": "sema", "line": e.line, "col": e.col, "msg": e.msg}
            return result
        result["typed_ast"] = str(typed_ast)
        
        # code generation
        try:
            prog = generate_c(typed_ast)
        except Exception as e:
            result["ok"] = False
            result["error"] = {"stage": "codegen", "line": None, "col": None, "msg": str(e)}
            return result
        
        # run original
        try:
            r1 = run_program(prog)
        except Exception as e:
            result["ok"] = False
            result["error"] = {"stage": "runtime", "line": None, "col": None, "msg": str(e)}
            result["tac_before"] = [str(i) for i in prog.all_instrs()]
            return result
        result["output_before"] = [str(x) for x in r1.output] + ([r1.stdout] if r1.stdout else [])
        result["tac_before"] = [str(i) for i in prog.all_instrs()]
        
        # optimize main function body
        from passes import optimise, PassContext
        fn = prog.main()
        addr_taken = {i.arg1 for i in fn.body if i.op == "addr"}
        ctx = PassContext(globals_set=set(prog.globals.keys()), var_types=fn.var_types,
                          addr_taken=addr_taken)
        enabled = set() if mode == "none" else set(passes_list or [])
        if mode == "ai":
            try:
                from advisor import recommend, extract_features
                feats = extract_features(prog.all_instrs())
                recommended, expl = recommend(prog.all_instrs())
                result["recommended"] = sorted(recommended)
                result["predictions"] = expl.get("predictions", {})
                result["features"] = expl.get("features", {})
                enabled = set(recommended)
            except Exception:
                enabled = set(["fold", "dce"])
        if mode == "all":
            enabled = set(passes.ADVISED)
        result["passes_run"] = sorted(enabled)
        log = []
        try:
            new_body = optimise(list(fn.body), enabled, ctx=ctx, log=log)
        except Exception as e:
            result["ok"] = False
            result["error"] = {"stage": "optimize", "line": None, "col": None, "msg": str(e)}
            return result
        fn.body = new_body
        result["trace"] = list(log)
        
        # run optimized
        try:
            r2 = run_program(prog)
        except Exception as e:
            result["ok"] = False
            result["error"] = {"stage": "runtime", "line": None, "col": None, "msg": str(e)}
            result["output_after"] = []
            result["match"] = False
            return result
        result["output_after"] = [str(x) for x in r2.output] + ([r2.stdout] if r2.stdout else [])
        result["tac_after"] = [str(i) for i in prog.all_instrs()]
        result["match"] = (r1.stdout == r2.stdout and r1.exit_code == r2.exit_code and r1.error == r2.error)
        from eval.metrics import compute_metrics
        result["metrics"] = {
            "static_before": len(result["tac_before"]),
            "static_after": len(result["tac_after"]),
            "dynamic_before": r1.steps,
            "dynamic_after": r2.steps,
        }
        if not result["match"]:
            result["ok"] = False
            result["error"] = {"stage": "verify", "line": None, "col": None, "msg": "outputs differ"}
        if r1.error or r2.error:
            result["ok"] = False
            result["error"] = {"stage": "runtime", "line": None, "col": None, "msg": r1.error or r2.error}
    except Exception as e:
        result["ok"] = False
        result["error"] = {"stage": "unknown", "line": None, "col": None, "msg": str(e)}
    return result

def run_pipeline(source, mode="ai", passes=None, lang="c"):
    if lang == "c":
        return _run_c(source, mode, passes)
    elif lang == "mini":
        return _run_one(source, mode, passes)
    else:
        return {
            "ok": False,
            "error": {"stage": "config", "line": None, "msg": "unknown language '%s' (use 'c' or 'mini')" % lang},
            "tokens": [], "ast": "", "typed_ast": "",
            "tac_before": [], "tac_after": [], "features": {},
            "recommended": [], "predictions": {}, "passes_run": [],
            "trace": [], "metrics": {"static_before": 0, "static_after": 0,
                                    "dynamic_before": 0, "dynamic_after": 0},
            "output_before": [], "output_after": [], "match": False
        }


def compare_modes(source):
    out = {}
    for mode in ("none", "ai", "all"):
        r = run_pipeline(source, mode=mode)
        out[mode] = {
            "metrics": r["metrics"],
            "passes_run": r["passes_run"],
            "ok": r["ok"],
            "match": r["match"],
        }
    return out
