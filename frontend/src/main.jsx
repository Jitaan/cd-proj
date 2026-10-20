import React, { useState, useEffect } from "react";
import ReactDOM from "react-dom/client";

const API = "http://127.0.0.1:8000";

function Card({ title, children }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-5 shadow-xl shadow-black/20">
      <h3 className="mb-3 text-xs font-bold uppercase tracking-[0.16em] text-indigo-400">{title}</h3>
      {children}
    </div>
  );
}

function App() {
  const [examples, setExamples] = useState({});
  const [source, setSource] = useState("");
  const mode = "ai";
  const [lang, setLang] = useState("c");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch(API + "/api/examples").then(r => r.json()).then(setExamples).catch(() => {});
  }, []);

  const run = async (m = mode) => {
    setLoading(true);
    const res = await fetch(API + "/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, mode: m, passes: null }),
    });
    setResult(await res.json());
    setLoading(false);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <main className="mx-auto max-w-4xl px-4 py-10 sm:px-6 sm:py-16">
        <header className="mb-10 text-center">
          
          <h1 className="bg-gradient-to-r from-indigo-300 via-violet-300 to-fuchsia-300 bg-clip-text text-4xl font-extrabold text-transparent sm:text-5xl">
            AI-Assisted Intermediate Code Optimization
          </h1>
          <p className="mt-3 text-slate-400">AI-assisted three-address code optimization</p>
        </header>

        <section className="space-y-6">
          <Card title="Source code">
              <div className="mb-4 flex flex-col gap-3 sm:flex-row">
                <select aria-label="Choose an example" className="flex-1 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-200 outline-none transition focus:border-indigo-400 focus:ring-4 focus:ring-indigo-950"
                  onChange={(e) => { if (examples[e.target.value]) setSource(examples[e.target.value]); }}>
                  <option value="">-- select example --</option>
                  {Object.keys(examples).map(k => <option key={k} value={k}>{k}</option>)}
                </select>
                <select aria-label="Language" className="rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-200 outline-none transition focus:border-indigo-400 focus:ring-4 focus:ring-indigo-950" value={lang} onChange={(e) => setLang(e.target.value)}>
                <option value="c">C</option>
                <option value="mini">MiniC</option>
              </select>
              </div>
              <textarea aria-label="MiniC source code" value={source} onChange={(e) => setSource(e.target.value)} rows={16} placeholder="Write or select a MiniC program to optimize..."
                className="w-full resize-y rounded-xl border border-slate-700 bg-black p-4 font-mono text-sm leading-6 text-slate-100 outline-none placeholder:text-slate-600 transition focus:border-indigo-400 focus:ring-4 focus:ring-indigo-950" />
              <div className="mt-4 flex flex-col gap-3 sm:flex-row">
                <button onClick={() => run(mode)} disabled={loading}
                  className="flex-1 rounded-xl bg-indigo-500 py-3 font-semibold text-white shadow-lg shadow-indigo-950/50 transition hover:bg-indigo-400 focus:outline-none focus:ring-4 focus:ring-indigo-950 disabled:cursor-not-allowed disabled:opacity-50">
                  {loading ? "Running..." : "Run Optimizer"}
                </button>
                <button onClick={() => run("tac")} disabled={loading}
                  className="rounded-xl border border-slate-700 bg-slate-800 px-5 py-3 font-semibold text-slate-200 transition hover:bg-slate-700 focus:outline-none focus:ring-4 focus:ring-slate-800 disabled:cursor-not-allowed disabled:opacity-50">
                  Generate TAC only
                </button>
              </div>
          </Card>

          <section aria-live="polite" className="space-y-4">
            {!result && (
              <Card title="Result">
                <p className="text-slate-400">Your compiled program and optimization details will appear here.</p>
              </Card>
            )}
            {result && (
              <>
                <div className={`rounded-xl border p-4 font-semibold ${result.ok ? "border-emerald-900 bg-emerald-950/60 text-emerald-300" : "border-red-900 bg-red-950/60 text-red-300"}`}>
                  {result.ok ? "Output match: YES" : ("ERROR: " + (result.error && (result.error.line + ": " + result.error.msg)))}
                </div>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Card title="Static instructions">
                    <div className="text-3xl font-bold text-indigo-600">{result.metrics.static_before} <span className="text-slate-300">→</span> {result.metrics.static_after}</div>
                  </Card>
                  <Card title="Dynamic instructions">
                    <div className="text-3xl font-bold text-violet-600">{result.metrics.dynamic_before} <span className="text-slate-300">→</span> {result.metrics.dynamic_after}</div>
                  </Card>
                </div>
                {[
                  ["Output before", (result.output_before || []).join("\n")],
                  ["Output after", (result.output_after || []).join("\n")],
                  ["TAC before", (result.tac_before || []).join("\n")],
                  ["TAC after", (result.tac_after || []).join("\n")],
                  ["Features", JSON.stringify(result.features, null, 2)],
                  ["Passes run", (result.passes_run || []).join(", ")],
                  ["Trace", JSON.stringify(result.trace)],
                ].map(([t, c]) => (
                  <Card key={t} title={t}>
                    <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-200">{c}</pre>
                  </Card>
                ))}
              </>
            )}
          </section>
        </section>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
