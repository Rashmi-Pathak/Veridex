"use client";

import { useState } from "react";

// Ask the provenance agent. A visitor types a question and a Claude-powered agent answers by calling
// Veridex's live provenance tools, then we show its real tool-call trace. The backend endpoint is
// opt-in (it needs a model key); when no key is set it returns an honest disabled response, which we
// surface as-is (the reachable MCP endpoint plus example questions) instead of inventing an answer.
// /api/demo/agent is a raw fetch, not part of the typed OpenAPI client, exactly like /api/status.
type AgentToolCall = { tool: string; input: Record<string, unknown>; result: Record<string, unknown> };
type AgentResponse = {
  enabled: boolean;
  answer: string;
  toolCalls: AgentToolCall[];
  model: string;
  mcpEndpoint: string;
  suggestedQuestions: string[];
  fellBack: boolean;
  reason: string | null;
};

// Seed chips so the panel is useful before the first request. Once a response arrives, its own
// suggestedQuestions (when present) replace these.
const FALLBACK_QUESTIONS = [
  "What has Veridex signed recently?",
  "Verify the demo asset and tell me what model generated it.",
  "Is the transparency log tamper-evident?",
];

// The backend rejects a question over 600 chars with a 400; cap the input so that path is not hit.
const MAX_QUESTION = 600;

export function AgentPanel() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AgentResponse | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [showTrace, setShowTrace] = useState(false);

  // Refresh the chips from the latest response when it carries any, else keep the built-in list.
  const chips =
    result && result.suggestedQuestions.length > 0 ? result.suggestedQuestions : FALLBACK_QUESTIONS;

  async function ask(text: string) {
    const trimmed = text.trim();
    if (trimmed === "" || loading) return;
    setLoading(true);
    setUnreachable(false);
    setResult(null);
    setShowTrace(false);
    try {
      const res = await fetch("/api/demo/agent", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      // Valid requests are always 200; a disabled agent or a fallback comes back inside the body. Any
      // non-OK status means the backend itself is not answering, so we treat it as unreachable.
      if (!res.ok) {
        setUnreachable(true);
        return;
      }
      const data: AgentResponse = await res.json();
      setResult(data);
    } catch {
      setUnreachable(true);
    } finally {
      setLoading(false);
    }
  }

  function onChip(chip: string) {
    setQuestion(chip);
    void ask(chip);
  }

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-3 text-xs uppercase tracking-widest text-white/50">Ask the provenance agent</h2>
      <p className="mb-4 text-[11px] text-white/55">
        A Claude-powered agent answers your question by calling Veridex&apos;s live provenance tools.
        Its real tool calls appear under the reply.
      </p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex-1 font-mono text-xs text-white/60">
          question
          <textarea
            value={question}
            maxLength={MAX_QUESTION}
            rows={2}
            placeholder="Ask about a signed asset, the transparency log, or the demo image."
            onChange={(e) => setQuestion(e.target.value)}
            className="mt-1 w-full resize-none rounded border border-white/15 bg-black/40 px-2 py-1 text-white/90 placeholder:text-white/55"
          />
        </label>
        <button
          type="button"
          onClick={() => void ask(question)}
          disabled={question.trim() === "" || loading}
          className="shrink-0 rounded border border-white/20 px-4 py-2 font-mono text-xs text-white/80 transition hover:border-white/40 hover:bg-white/[0.03] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? "Asking…" : "Submit"}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {chips.map((chip) => (
          <button
            key={chip}
            type="button"
            onClick={() => onChip(chip)}
            disabled={loading}
            className="rounded-full border border-white/15 px-3 py-1 text-left font-mono text-[11px] text-white/55 transition hover:border-white/40 hover:bg-white/[0.03] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {chip}
          </button>
        ))}
      </div>

      <div className="mt-5 min-h-16">
        {loading && (
          <p className="font-mono text-sm text-sky-300">
            <span className="inline-flex items-center gap-2">
              <span className="h-2 w-2 animate-ping rounded-full bg-sky-300" />
              Asking the agent…
            </span>
          </p>
        )}

        {!loading && unreachable && (
          <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>
        )}

        {!loading && !unreachable && result && (
          <>
            {!result.enabled && (
              <div className="space-y-2">
                <p className="font-mono text-sm text-amber-400">
                  {result.reason ?? "Agent replies are off in this deployment."}
                </p>
                <p className="text-xs text-white/50">
                  Connect your own agent to Veridex&apos;s MCP server at{" "}
                  <code className="text-white/80">{result.mcpEndpoint}</code>.
                </p>
              </div>
            )}

            {result.enabled && result.fellBack && (
              <div className="space-y-1">
                <p className="font-mono text-sm text-amber-400">
                  {result.reason ?? "The agent returned a fallback response."}
                </p>
                <p className="text-xs text-white/55">Try one of the example questions above.</p>
              </div>
            )}

            {result.enabled && !result.fellBack && (
              <div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-white/80">
                  {result.answer}
                </p>
                {result.model && (
                  <p className="mt-1 text-[11px] text-white/55">answered by {result.model}</p>
                )}

                {result.toolCalls.length > 0 && (
                  <div className="mt-4">
                    <button
                      type="button"
                      onClick={() => setShowTrace((v) => !v)}
                      className="font-mono text-[11px] uppercase tracking-widest text-white/55 transition hover:text-white/70"
                    >
                      {showTrace ? "hide" : "show"} tool calls ({result.toolCalls.length})
                    </button>
                    <ol className="mt-2 space-y-2">
                      {result.toolCalls.map((tc, i) => (
                        <li key={`${tc.tool}-${i}`}>
                          <p className="font-mono text-xs text-emerald-300">{tc.tool}</p>
                          {showTrace && (
                            <pre className="mt-1 max-h-40 overflow-auto rounded border border-white/10 bg-black/40 p-2 font-mono text-[11px] text-white/60">
                              {JSON.stringify(tc.result, null, 2)}
                            </pre>
                          )}
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
