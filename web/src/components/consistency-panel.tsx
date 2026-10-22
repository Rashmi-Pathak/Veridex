"use client";

import { useEffect, useState } from "react";

// Append-only proof. A Merkle consistency proof shows the current transparency log still contains
// the exact earlier tree, with no leaf altered or removed: only appends. This is the guarantee
// Certificate Transparency publishes. The panel reads /api/demo/consistency, which proves the head
// extends the immediately-prior tree size and reports whether that prior state is WORM-sealed in B2
// Object Lock (binding the proof to an object that physically cannot be rewritten). The full,
// independently-verifiable proof is at /transparency/consistency/{priorSize}.
type Consistency = {
  available: boolean;
  priorSize: number;
  priorRootHash: string;
  treeSize: number;
  rootHash: string;
  serverVerified: boolean;
  sealedInObjectLock: boolean;
  sealedRootMatches: boolean;
  backend: string;
  bucket: string | null;
  retainUntil: string | null;
  keySource: string;
};

function formatUntil(iso: string | null): string {
  if (!iso) return "unset";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 10);
}

export function ConsistencyPanel() {
  const [info, setInfo] = useState<Consistency | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/consistency")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: Consistency) => setInfo(d))
      .catch(() => setError(true));
  }, []);

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">Append-only proof</h2>
      <p className="mb-4 text-[11px] text-white/55">
        A Merkle consistency proof: the current log still contains the earlier tree unchanged, with
        no entry altered or removed. This is the append-only guarantee Certificate Transparency
        publishes, here bound to a checkpoint sealed in B2 Object Lock.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !info && <p className="font-mono text-sm text-white/50">Proving append-only…</p>}

      {info && !info.available && (
        <p className="font-mono text-sm text-white/60">
          The log has a single leaf; nothing has been appended on top of an earlier state yet.
        </p>
      )}

      {info && info.available && (
        <>
          <div className="flex items-center gap-2 font-mono text-sm">
            {info.serverVerified ? (
              <span className="rounded bg-emerald-400/10 px-2 py-0.5 text-emerald-300">
                ✓ append-only verified
              </span>
            ) : (
              <span className="rounded bg-amber-400/10 px-2 py-0.5 text-amber-400">unverified</span>
            )}
            <span className="text-white/70">
              size {info.priorSize} → size {info.treeSize}
            </span>
          </div>

          <p className="mt-2 text-[11px] text-white/60">
            The {info.priorSize}-leaf tree is contained, unchanged, in the current {info.treeSize}
            -leaf log. No earlier entry was rewritten or removed.
          </p>

          <div className="mt-3 font-mono text-sm">
            {info.sealedInObjectLock ? (
              <span className="text-emerald-300">
                The size-{info.priorSize} root is WORM-sealed on Backblaze B2
                {info.bucket ? ` (bucket ${info.bucket})` : ""}, retained until{" "}
                {formatUntil(info.retainUntil)}.
              </span>
            ) : (
              <span className="text-white/60">
                The prior state is not individually sealed here; the consistency proof and the signed
                head still hold.
              </span>
            )}
          </div>

          <dl className="mt-3 grid gap-1 font-mono text-xs text-white/70">
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">prior root</dt>
              <dd className="break-all text-white/60">{info.priorRootHash.slice(0, 32)}…</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">current root</dt>
              <dd className="break-all text-white/60">{info.rootHash.slice(0, 32)}…</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">verify</dt>
              <dd className="text-white/70">/transparency/consistency/{info.priorSize}</dd>
            </div>
          </dl>
        </>
      )}
    </section>
  );
}
