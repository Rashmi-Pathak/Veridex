"use client";

import { useEffect, useState } from "react";

// Checkpoint history. The chain of signed Merkle checkpoints sealed to B2 Object Lock over time;
// each is an immutable WORM object, so the chain is an append-only audit trail of the tree head at
// successive epochs. Combined with the consistency proof, it shows the live log extends every sealed
// checkpoint. Reads /api/demo/checkpoint-history. Modeled in-memory when no locked bucket is set.
type HistEntry = {
  epoch: number;
  treeSize: number;
  rootHash: string;
  signedAt: string;
  signatureVerified: boolean;
  retainUntil: string | null;
  immutable: boolean;
};
type History = {
  backend: string;
  bucket: string | null;
  count: number;
  modeled: boolean;
  entries: HistEntry[];
};

function formatUntil(iso: string | null): string {
  if (!iso) return "unset";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 10);
}

export function CheckpointHistoryPanel() {
  const [info, setInfo] = useState<History | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/checkpoint-history")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: History) => setInfo(d))
      .catch(() => setError(true));
  }, []);

  const onB2 = info?.backend === "backblaze-b2";

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">Checkpoint history</h2>
      <p className="mb-4 text-[11px] text-white/55">
        The chain of signed Merkle checkpoints sealed to Backblaze B2 Object Lock over time. Each is
        an immutable WORM object, so the chain is an append-only audit trail of the tree head; the
        consistency proof shows the live log extends every one of them.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !info && (
        <p className="font-mono text-sm text-white/50">Reading checkpoint chain…</p>
      )}

      {info && (
        <>
          <div className="mb-3 flex items-center gap-2 font-mono text-sm">
            <span className="text-white/70">
              {info.count} checkpoint{info.count === 1 ? "" : "s"}
            </span>
            {onB2 ? (
              <span className="text-emerald-300">
                on Backblaze B2{info.bucket ? ` (bucket ${info.bucket})` : ""}
              </span>
            ) : (
              <span className="text-white/60">Object Lock modeled in-memory</span>
            )}
          </div>

          <ol className="grid gap-1.5 font-mono text-xs">
            {info.entries.map((e) => (
              <li
                key={e.epoch}
                className="flex flex-wrap items-center gap-x-3 gap-y-0.5 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2"
              >
                <span className="text-white/80">epoch {e.epoch}</span>
                <span className="text-white/55">{e.treeSize} leaves</span>
                <span className="break-all text-white/45">{e.rootHash.slice(0, 16)}…</span>
                <span className={e.signatureVerified ? "text-emerald-300" : "text-amber-400"}>
                  {e.signatureVerified ? "✓ signed" : "✗ unsigned"}
                </span>
                {e.immutable ? (
                  <span className="text-emerald-300/80">immutable · until {formatUntil(e.retainUntil)}</span>
                ) : (
                  <span className="text-white/40">unretained</span>
                )}
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
