"use client";

import { useEffect, useState } from "react";

// A C2PA Soft Binding Resolution 2.4 proof-of-ingestion receipt (a c2pa.verifiedManifestReceipt),
// fetched live from /api/demo/receipt. The receipt is the spec-conformant, portable form of Veridex's
// transparency proof: its anchor.proof is the signed Merkle inclusion proof for the manifest, and the
// top-level verified boolean is the real cryptographic check the server ran (the inclusion proof
// recomputes to the signed checkpoint root and the checkpoint's Ed25519 signature verifies). Nothing
// here is hardcoded; the VERIFIED badge and every field come from the live response.
type MerkleProof = {
  alg: string;
  manifestId: string;
  leafIndex: number;
  leafHash: string;
  treeSize: number;
  rootHash: string;
  proof: Record<string, unknown>;
  checkpoint: {
    epoch: number;
    treeSize: number;
    rootHash: string;
    signedAt: string;
    signatureB64: string;
  };
  publicKeyHex: string;
  keySource: string;
  serverVerified: boolean;
};

type Receipt = {
  "@context": Record<string, string>;
  "@type": string;
  repository: { uri: string; manifestId: string };
  anchor: {
    uri: string;
    parameters: { epoch: number };
    proof: MerkleProof;
  };
  verified: boolean;
  error?: string | null;
};

const SPEC_URL =
  "https://spec.c2pa.org/specifications/specifications/2.4/softbinding/Decoupled.html";

export function ReceiptPanel() {
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/receipt")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: Receipt) => setReceipt(d))
      .catch(() => setError(true));
  }, []);

  const proof = receipt?.anchor.proof;

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">
        C2PA 2.4 proof-of-ingestion receipt
      </h2>
      <p className="mb-4 text-[11px] text-white/55">
        A receipt conformant to the C2PA Soft Binding Resolution 2.4 spec that proves this repository
        ingested the manifest. The receipt&apos;s anchor.proof is Veridex&apos;s signed Merkle
        inclusion proof, and verified is the real cryptographic check: the inclusion proof recomputes
        to the signed checkpoint root and the checkpoint signature verifies.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !receipt && <p className="font-mono text-sm text-white/50">Fetching receipt…</p>}

      {receipt && proof?.rootHash ? (
        <>
          <div className="flex items-center gap-2 font-mono text-sm">
            {receipt.verified ? (
              <span className="rounded bg-emerald-400/10 px-2 py-0.5 text-emerald-300">
                ✓ VERIFIED
              </span>
            ) : (
              <span className="rounded bg-rose-400/10 px-2 py-0.5 text-rose-400">
                ✗ NOT VERIFIED
              </span>
            )}
            <span className="text-white/60">
              {proof.serverVerified ? "server re-verified" : "verification not run"}
            </span>
          </div>

          {!receipt.verified && receipt.error && (
            <p className="mt-2 font-mono text-xs text-rose-300">Not verified: {receipt.error}</p>
          )}

          <dl className="mt-3 grid gap-1 font-mono text-xs text-white/70">
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">@type</dt>
              <dd className="break-all text-white/80">{receipt["@type"]}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">manifest</dt>
              <dd className="break-all text-white/70">{receipt.repository.manifestId}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">anchor</dt>
              <dd className="break-all">
                <a
                  href={receipt.anchor.uri}
                  target="_blank"
                  rel="noreferrer"
                  className="text-emerald-300 underline-offset-4 hover:underline"
                >
                  {receipt.anchor.uri}
                </a>
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">epoch</dt>
              <dd className="text-white/80">{receipt.anchor.parameters.epoch}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">inclusion</dt>
              <dd className="text-white/80">
                leaf {proof.leafIndex} of {proof.treeSize}
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 shrink-0 text-white/55">root</dt>
              <dd className="break-all text-white/60">{proof.rootHash.slice(0, 32)}…</dd>
            </div>
          </dl>

          <details className="mt-4">
            <summary className="cursor-pointer font-mono text-[11px] text-white/55 hover:text-white/80">
              raw receipt JSON
            </summary>
            <pre className="mt-2 max-h-72 overflow-auto rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-[10px] leading-relaxed text-white/70">
              {JSON.stringify(receipt, null, 2)}
            </pre>
          </details>
        </>
      ) : receipt ? (
        // The log has no leaf for this manifest yet: the empty-log fallback returns an empty proof.
        // Render the honest degraded state instead of dereferencing a missing proof.
        <p className="font-mono text-sm text-amber-400">
          {receipt.error ?? "Transparency proof is not available yet."}
        </p>
      ) : null}

      <p className="mt-4 text-[11px] text-white/55">
        Interoperable with the C2PA SBR spec. Veridex deliberately refuses the spec mutation routes
        (DELETE returns 405) because the registry is append-only and WORM-backed by Backblaze B2
        Object Lock.{" "}
        <a
          href={SPEC_URL}
          target="_blank"
          rel="noreferrer"
          className="text-white/70 underline-offset-4 hover:underline"
        >
          C2PA SBR 2.4 spec
        </a>
      </p>
    </section>
  );
}
