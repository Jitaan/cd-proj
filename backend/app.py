# app.py - Streamlit UI (thin layer over service.py)

import difflib

import streamlit as st

import service

st.set_page_config(layout="wide", page_title="AI-Assisted TAC Optimizer")

examples = service.list_examples()


@st.cache_resource
def load_model_info():
    return service.explain_model()


model_info = load_model_info()


def main():
    st.title("AI-Assisted TAC Optimizer")

    if "result" not in st.session_state:
        st.session_state.result = None
    if "source" not in st.session_state:
        st.session_state.source = list(examples.values())[0] if examples else ""

    # sidebar
    with st.sidebar:
        st.header("Settings")
        ex_names = ["Custom"] + list(examples.keys())
        choice = st.selectbox("Example", ex_names)
        if choice != "Custom" and choice in examples:
            if st.button("Load example"):
                st.session_state.source = examples[choice]
                st.rerun()
        mode = st.radio("Mode", ["AI recommended", "All passes", "None", "Custom"])
        mode_map = {"AI recommended": "ai", "All passes": "all", "None": "none",
                    "Custom": "custom"}
        mode_key = mode_map[mode]
        custom_passes = []
        if mode_key == "custom":
            custom_passes = st.multiselect("Passes", passes.ADVISED)
        run_btn = st.button("Run")

    col1, col2 = st.columns(2)
    with col1:
        src = st.text_area("Source", value=st.session_state.source, height=400)
        st.session_state.source = src

    with col2:
        if run_btn:
            st.session_state.result = service.run_pipeline(
                src, mode=mode_key, passes=custom_passes if mode_key == "custom" else None)
        res = st.session_state.result
        if res is None:
            st.info("Press Run to compile.")
            return
        # status banner
        if res["ok"]:
            st.success("Output matches: YES")
        else:
            err = res.get("error") or {}
            line = err.get("line")
            msg = err.get("msg", "")
            stage = err.get("stage", "")
            if line is not None:
                st.error("line %s: %s (%s)" % (line, msg, stage))
            else:
                st.error("%s (%s)" % (msg, stage))
        # Result tab content inline metrics
        m = res.get("metrics", {})
        c1, c2, c3, c4 = st.columns(4)
        sb = m.get("static_before", 0)
        sa = m.get("static_after", 0)
        db = m.get("dynamic_before", 0)
        da = m.get("dynamic_after", 0)
        c1.metric("Static before", sb)
        c2.metric("Static after", sa, delta=sa - sb)
        c3.metric("Dynamic before", db)
        c4.metric("Dynamic after", da, delta=da - db)
        # outputs
        o1, o2 = st.columns(2)
        with o1:
            st.subheader("Output before")
            out_b = res.get("output_before", [])[:200]
            st.code("\n".join(out_b) + ("\n(truncated)" if len(res.get("output_before", [])) > 200 else ""))
        with o2:
            st.subheader("Output after")
            out_a = res.get("output_after", [])[:200]
            st.code("\n".join(out_a) + ("\n(truncated)" if len(res.get("output_after", [])) > 200 else ""))

    # tabs below
    tabs = st.tabs(["Result", "TAC", "AI advisor", "Pass trace", "Front end", "Compare modes"])
    res = st.session_state.result
    if res is None:
        return
    with tabs[1]:
        t1, t2 = st.columns(2)
        with t1:
            st.subheader("Original TAC")
            st.code("\n".join(res.get("tac_before", [])))
        with t2:
            st.subheader("Optimized TAC")
            st.code("\n".join(res.get("tac_after", [])))
        diff = list(difflib.unified_diff(res.get("tac_before", []), res.get("tac_after", []),
                                         fromfile="before", tofile="after", lineterm=""))
        st.subheader("Diff")
        st.code("\n".join(diff), language="diff")
    with tabs[2]:
        st.subheader("Features")
        feats = res.get("features", {})
        st.table([{"feature": k, "value": v} for k, v in feats.items()])
        st.subheader("Predictions / passes")
        preds = res.get("predictions", {})
        rows = []
        for p in (res.get("passes_run", []) + res.get("recommended", [])):
            pass
        for p in sorted(set(res.get("recommended", []) + res.get("passes_run", []))):
            rows.append({"pass": p, "predicted": preds.get(p, "-"),
                         "ran": p in res.get("passes_run", [])})
        st.table(rows)
        with st.expander("Decision trees"):
            for k, v in model_info.items():
                st.text(k + ":\n" + str(v))
    with tabs[3]:
        st.subheader("Pass trace")
        tr = res.get("trace", [])
        st.table([{"round": r, "pass": p, "changed": c} for (r, p, c) in tr])
    with tabs[4]:
        st.subheader("Tokens")
        toks = res.get("tokens", [])
        st.table([{"type": t[0], "text": t[1], "line": t[2]} for t in toks])
        st.subheader("AST")
        st.code(res.get("ast", ""))
        st.subheader("Typed AST")
        st.code(res.get("typed_ast", ""))
    with tabs[5]:
        if st.button("Compare modes"):
            cmp = service.compare_modes(src)
            rows = []
            for mode, info in cmp.items():
                mm = info.get("metrics", {})
                rows.append({"mode": mode,
                             "static": mm.get("static_after", 0),
                             "dynamic": mm.get("dynamic_after", 0),
                             "passes": len(info.get("passes_run", []))})
            st.table(rows)
            import pandas as pd
            df = pd.DataFrame(rows).set_index("mode")
            st.bar_chart(df[["static", "dynamic"]])


if __name__ == "__main__":
    main()
