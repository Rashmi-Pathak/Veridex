"use client";

import { useEffect, useState } from "react";

// Backblaze B2 as an ACTIVE part of the pipeline, not just storage. A B2 Event Notification rule
// POSTs a signed webhook when an object lands under the watched prefix; Veridex verifies the HMAC,
// fetches the object from B2, fingerprints it, and registers it for recovery + the transparency log.
// Drop an asset in B2 and it auto-becomes recoverable. This panel reads /api/demo/b2-events.
type IngestRecord = {
  objectKey: string;
  manifestId: string;
  bucket: string;
  sizeBytes: number;
  ingestedAt: string;
};

type Status = {
  configured: boolean;
  watchPrefix: string;
  count: number;
  recent: IngestRecord[];
};

const short = (s: string, n = 22) => (s.length > n ? `${s.slice(0, n)}…` : s);

export function B2EventsPanel() {
  const [d, setD] = useState<Status | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/b2-events")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j: Status) => setD(j))
      .catch(() => setError(true));
  }, []);

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">
        Backblaze B2 event-driven ingest
      </h2>
      <p className="mb-3 text-[11px] text-white/55">
        Backblaze B2 as data orchestration, not just storage. A B2 Event Notification rule POSTs a
        signed webhook when an object lands under the watched prefix; Veridex verifies the HMAC,
        fetches the object from B2, fingerprints it, and registers it for recovery and the
        transparency log. Drop an asset in B2 and it auto-becomes recoverable.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !d && <p className="font-mono text-sm text-white/50">Loading…</p>}

      {d && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs">
            <span className={d.configured ? "text-emerald-300" : "text-amber-400"}>
              {d.configured ? "✓ webhook configured" : "○ not configured"}
            </span>
            <span className="text-white/55">
              prefix <span className="text-white/80">{d.watchPrefix}</span>
            </span>
            <span className="text-white/55">
              ingested <span className="text-white/80">{d.count}</span>
            </span>
          </div>

          {d.recent.length > 0 ? (
            <ul className="grid gap-1.5">
              {d.recent.map((r) => (
                <li
                  key={r.manifestId}
                  className="flex flex-wrap items-center gap-x-3 gap-y-0.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 font-mono text-xs"
                >
                  <span className="text-emerald-300">B2 ▸</span>
                  <span className="text-white/80">{short(r.objectKey, 30)}</span>
                  <span className="text-white/40">→</span>
                  <span className="text-white/70">{short(r.manifestId, 26)}</span>
                  <span className="ml-auto text-white/40">recoverable</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="font-mono text-xs text-white/50">
              {d.configured
                ? "No objects ingested yet. Upload one under the watched prefix in B2."
                : "Set B2_EVENT_SIGNING_SECRET and add a B2 Event Notification rule to activate."}
            </p>
          )}
        </>
      )}
    </section>
  );
}
