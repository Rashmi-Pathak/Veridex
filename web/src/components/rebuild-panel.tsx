"use client";

import { useEffect, useState } from "react";

// Rebuild from B2. Veridex's resolver and transparency log are derived state; the authoritative
// record is the content-addressed objects in Backblaze B2. This reconstructs a fresh recovery index
// from B2 alone (no database) and re-proves the demo asset recovers against it, so a lost index can
// be fully reconstituted from B2. Reads /api/demo/rebuild (read-only: a throwaway index).
type Rebuild = {
  available: boolean;
  backend: string;
  manifestsScanned: number;
  manifestsRebuilt: number;
  skipped: number;
  leavesRebuilt: number;
  demoRecovered: boolean;
  demoSimilarity: number | null;
  rebuiltTreeSize: number;
  rebuiltRootHash: string;
  liveTreeSize: number;
  liveRootHash: string;
  rootsMatch: boolean;
  note: string;
};

export function RebuildPanel() {
  const [info, setInfo] = useState<Rebuild | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/rebuild")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: Rebuild) => setInfo(d))
      .catch(() => setError(true));
  }, []);

  const onB2 = info?.backend === "backblaze-b2";

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">Rebuild from B2</h2>
      <p className="mb-4 text-[11px] text-white/55">
        The recovery index and transparency log are derived state; the content-addressed objects in
        Backblaze B2 are the source of truth. This throws away the index and reconstructs it from B2
        alone, then re-proves the demo asset recovers, so a lost database reconstitutes from B2.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !info && (
        <p className="font-mono text-sm text-white/50">Rebuilding from B2…</p>
      )}

      {info && !info.available && (
        <p className="font-mono text-sm text-white/60">{info.note}</p>
      )}

      {info && info.available && (
        <>
          <div className="flex items-center gap-2 font-mono text-sm">
            {info.demoRecovered ? (
              <span className="rounded bg-emerald-400/10 px-2 py-0.5 text-emerald-300">
                ✓ recovered from B2 alone
                {info.demoSimilarity !== null ? ` (${info.demoSimilarity})` : ""}
              </span>
            ) : (
              <span className="rounded bg-amber-400/10 px-2 py-0.5 text-amber-400">
                did not recover
              </span>
            )}
            <span className="text-white/60">
              {onB2 ? "Backblaze B2" : "in-memory store"}
            </span>
          </div>

          <p className="mt-2 text-[11px] text-white/60">{info.note}</p>

          <dl className="mt-3 grid gap-1 font-mono text-xs text-white/70">
            <div className="flex gap-2">
              <dt className="w-32 shrink-0 text-white/55">rebuilt</dt>
              <dd className="text-white/80">
                {info.manifestsRebuilt} manifests · {info.leavesRebuilt} log leaves
                {info.skipped ? ` · ${info.skipped} skipped` : ""}
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-32 shrink-0 text-white/55">rebuilt root</dt>
              <dd className="break-all text-white/60">
                {info.rebuiltRootHash ? `${info.rebuiltRootHash.slice(0, 32)}…` : "(empty)"}
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-32 shrink-0 text-white/55">live tree</dt>
              <dd className="text-white/80">{info.liveTreeSize} leaves</dd>
            </div>
          </dl>
        </>
      )}
    </section>
  );
}
