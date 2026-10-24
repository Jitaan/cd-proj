import React, { useState, useEffect, useRef } from "react";
import ReactDOM from "react-dom/client";
import "./index.css";

const API = "http://127.0.0.1:8000";

function Card({ title, children, className = "" }) {
  return (
    <div className={`rounded-md border border-border bg-card p-4 ${className}`}>
      {title && (
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          {title}
        </h3>
      )}
      {children}
    </div>
  );
}

function formatValue(v) {
  if (typeof v === "number" && !Number.isInteger(v)) return v.toFixed(4);
  return String(v);
}

// trace entries are [round, pass, changed]; group by round and keep the
// names of the passes that actually modified the TAC that round.
function buildTraceRounds(trace) {
  const rounds = new Map();
  for (const [rnd, pass, changed] of trace) {
    if (!rounds.has(rnd)) rounds.set(rnd, []);
    if (changed) rounds.get(rnd).push(pass);
  }
  return [...rounds.entries()].sort((a, b) => a[0] - b[0]);
}

function App() {
  const [examples, setExamples] = useState({});
  const [source, setSource] = useState("");
  const mode = "ai";
  const [lang, setLang] = useState("c");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const sourceRef = useRef(null);

  const handleSourceKeyDown = (e) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const ta = sourceRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const next = source.slice(0, start) + "    " + source.slice(end);
    setSource(next);
    requestAnimationFrame(() => {
      ta.selectionStart = ta.selectionEnd = start + 4;
    });
  };

  useEffect(() => {
    fetch(API + "/api/examples").then(r => r.json()).then(setExamples).catch(() => {});
  }, []);

  const run = async (m = mode) => {
    setLoading(true);
    try {
      const res = await fetch(API + "/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source, mode: m, passes: null }),
      });
      setResult(await res.json());
    } catch (e) {
      setResult({ ok: false, error: { line: 0, msg: String(e) } });
    } finally {
      setLoading(false);
    }
  };

  const inputClass =
    "w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/40";
  const selectClass =
    "w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/40";

  const outputs = result
    ? [
        ["Output before", (result.output_before || []).join("\n")],
        ["Output after", (result.output_after || []).join("\n")],
        ["TAC before", (result.tac_before || []).join("\n")],
        ["TAC after", (result.tac_after || []).join("\n")],
        ["Passes run", (result.passes_run || []).join(", ")],
      ]
    : [];

  const featureRows = result && result.features ? Object.entries(result.features) : [];
  const traceRounds =
    result && Array.isArray(result.trace) && result.trace.length
      ? buildTraceRounds(result.trace)
      : [];

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4 sm:px-6">
          <div>
            <h1 className="text-lg font-bold tracking-tight sm:text-xl">
              AI-Assisted Intermediate Code Optimization
            </h1>
            <p className="text-xs text-muted-foreground">
              three-address code optimization dashboard
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="inline-block h-2 w-2 rounded-full bg-foreground" />
            ready
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <section className="flex flex-col gap-4">
            <Card title="Source code">
              <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <select
                  aria-label="Choose an example"
                  className={selectClass}
                  onChange={(e) => {
                    if (examples[e.target.value]) setSource(examples[e.target.value]);
                  }}
                >
                  <option value="">-- select example --</option>
                  {Object.keys(examples).map((k) => (
                    <option key={k} value={k}>
                      {k}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="Language"
                  className={selectClass}
                  value={lang}
                  onChange={(e) => setLang(e.target.value)}
                >
                  <option value="c">C</option>
                  <option value="mini">MiniC</option>
                </select>
              </div>
              <textarea
                aria-label="MiniC source code"
                ref={sourceRef}
                value={source}
                onChange={(e) => setSource(e.target.value)}
                onKeyDown={handleSourceKeyDown}
                rows={18}
                placeholder="Write or select a MiniC program to optimize..."
                className="w-full resize-y rounded-md border border-input bg-background p-3 font-mono text-sm leading-6 text-foreground outline-none placeholder:text-muted-foreground transition focus:border-ring focus:ring-2 focus:ring-ring/40"
              />
              <div className="mt-3 flex flex-col gap-3 sm:flex-row">
                <button
                  onClick={() => run(mode)}
                  disabled={loading}
                  className="flex-1 rounded-md bg-primary py-2.5 text-sm font-semibold text-primary-foreground transition hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {loading ? "Running..." : "Run Optimizer"}
                </button>
                <button
                  onClick={() => run("tac")}
                  disabled={loading}
                  className="rounded-md border border-border bg-secondary px-5 py-2.5 text-sm font-semibold text-secondary-foreground transition hover:bg-muted focus:outline-none focus:ring-2 focus:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Generate TAC only
                </button>
              </div>
            </Card>
          </section>

          <section className="flex flex-col gap-4">
            {!result && (
              <Card title="Result">
                <p className="text-sm text-muted-foreground">
                  Run the optimizer to see metrics and transformed code here.
                </p>
              </Card>
            )}
            {result && (
              <>
                <div
                  className={`rounded-md border p-3 text-sm font-semibold ${
                    result.ok
                      ? "border-foreground text-foreground"
                      : "border-destructive text-destructive"
                  }`}
                >
                  {result.ok
                    ? "Output match: YES"
                    : "ERROR: " +
                      (result.error && (result.error.line + ": " + result.error.msg))}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Card title="Static instructions">
                    <div className="text-2xl font-bold">
                      {result.metrics.static_before}{" "}
                      <span className="text-muted-foreground">→</span>{" "}
                      {result.metrics.static_after}
                    </div>
                  </Card>
                  <Card title="Dynamic instructions">
                    <div className="text-2xl font-bold">
                      {result.metrics.dynamic_before}{" "}
                      <span className="text-muted-foreground">→</span>{" "}
                      {result.metrics.dynamic_after}
                    </div>
                  </Card>
                </div>
                <div className="flex flex-col gap-3">
                  {outputs.map(([t, c]) => (
                    <Card key={t} title={t}>
                      <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-2 text-xs leading-5 text-foreground">
                        {c}
                      </pre>
                    </Card>
                  ))}
                  {result.features && (
                    <Card title="Features">
                      {featureRows.length > 0 ? (
                        <table className="w-full text-xs">
                          <tbody className="divide-y divide-border">
                            {featureRows.map(([k, v]) => (
                              <tr key={k}>
                                <td className="py-1 pr-3 font-mono text-muted-foreground">{k}</td>
                                <td className="py-1 text-right font-mono text-foreground">
                                  {formatValue(v)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : (
                        <p className="text-xs text-muted-foreground">No features available.</p>
                      )}
                    </Card>
                  )}
                  {Array.isArray(result.trace) && (
                    <Card title="Pass trace">
                      {traceRounds.length > 0 ? (
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-left text-muted-foreground">
                              <th className="w-14 pb-1 font-medium">Round</th>
                              <th className="pb-1 font-medium">Passes that changed the TAC</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-border">
                            {traceRounds.map(([rnd, changed]) => (
                              <tr key={rnd} className="align-top">
                                <td className="py-1 pr-3 font-mono text-muted-foreground">{rnd}</td>
                                <td className="py-1 font-mono text-foreground">
                                  {changed.length ? (
                                    changed.join(", ")
                                  ) : (
                                    <span className="text-muted-foreground">
                                      no changes (converged)
                                    </span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : (
                        <p className="text-xs text-muted-foreground">
                          No optimization passes were run.
                        </p>
                      )}
                    </Card>
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
