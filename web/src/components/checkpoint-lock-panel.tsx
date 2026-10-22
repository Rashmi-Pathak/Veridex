"use client";

import { useEffect, useState } from "react";

// The transparency log's signed tree head, sealed to a separate Object-Lock (compliance/WORM) B2
// bucket: once written it cannot be deleted or overwritten until retention expires, so the operator
// cannot rewrite history without contradicting an object that physically cannot be removed. The panel
// reads /api/transparency/checkpoint/object, which seals the current checkpoint and reads it back,
// re-verifying its Ed25519 signature. When no locked bucket is configured the same write/read/verify
// contract runs against the in-memory model and is labeled honestly (modeled).
type CheckpointObject = {
  backend: string;
  bucket: string | null;
  key: string;
  retentionMode: string;
  retainUntil: string | null;
  checkpoint: {
    epoch: number;
    treeSize: number;
    rootHash: string;
    signedAt: string;
    signatureB64: string;
  };
  signatureVerified: boolean;
  immutable: boolean;
  modeled: boolean;
  keySource: string;
};

function formatUntil(iso: string | null): string {
  if (!iso) return "unset";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 10);
}

export function CheckpointLockPanel() {
  const [info, setInfo] = useState<CheckpointObject | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/transparency/checkpoint/object")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: CheckpointObject) => setInfo(d))
      .catch(() => setError(true));
  }, []);

  const onB2 = info?.backend === "backblaze-b2";

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">
        Object Lock checkpoint
      </h2>
      <p className="mb-4 text-[11px] text-white/55">
        The signed Merkle tree head, sealed to Backblaze B2 under Object Lock (compliance). Once
        written it cannot be deleted or overwritten until retention expires, so the ledger is
        tamper-evident at the storage layer.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !info && <p className="font-mono text-sm text-white/50">Reading checkpoint…</p>}

      {info && (
        <>
          <div className="flex items-center gap-2 font-mono text-sm">
            {info.immutable ? (
              <span className="rounded bg-emerald-400/10 px-2 py-0.5 text-emerald-300">
                immutable
              </span>
            ) : (
              <span className="rounded bg-white/10 px-2 py-0.5 text-white/60">unretained</span>
            )}
            {onB2 ? (
              <span className="text-emerald-300">
                Sealed on Backblaze B2{info.bucket ? ` (bucket ${info.bucket})` : ""}
              </span>
            ) : (
              <span className="text-white/60">Object Lock modeled in-memory</span>
            )}
          </div>

          {!onB2 && (
            <p className="mt-2 text-[11px] text-white/55">
              Set B2_BUCKET_LOCKED to a fileLock-enabled bucket on the deploy to seal the checkpoint
              to real Backblaze B2 Object Lock. The write, read-back, signature check, and
              delete-refusal are exercised against the model meanwhile.
            </p>
          )}

          <dl className="mt-3 grid gap-1 font-mono text-xs text-white/70">
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">object</dt>
              <dd className="break-all text-white/70">{info.key}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">retention</dt>
              <dd className="text-white/80">
                {info.retentionMode} · until {formatUntil(info.retainUntil)}
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">epoch · size</dt>
              <dd className="text-white/80">
                {info.checkpoint.epoch} · {info.checkpoint.treeSize} leaves
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">root</dt>
              <dd className="break-all text-white/60">{info.checkpoint.rootHash.slice(0, 32)}…</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">signature</dt>
              <dd className={info.signatureVerified ? "text-emerald-300" : "text-amber-400"}>
                {info.signatureVerified ? "✓ verified" : "✗ unverified"}
                {info.keySource === "configured" ? " (anchor key)" : " (ephemeral key)"}
              </dd>
            </div>
          </dl>
        </>
      )}
    </section>
  );
}
