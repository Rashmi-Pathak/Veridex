"use client";

import { useEffect, useState } from "react";

// The dual-axis: Backblaze B2 + Genblaze, one asset, two trust layers. A real Genblaze Pipeline
// generation (GMI Cloud) was written to B2 by Genblaze's OWN ObjectStorageSink; /api/demo/genblaze-
// manifest re-verifies the native Genblaze integrity manifest at request time and reconciles it with
// Veridex's signed manifest over the same bytes. Genblaze proves INTEGRITY (Mode 1); Veridex adds the
// Ed25519/COSE signature, the C2PA mapping, recovery, and the transparency proof. Genblaze's own
// signing (Mode 2) and C2PA interop (Mode 3) are not shipped, which is why Veridex's layer is needed.
type Reconcile = {
  assetSha256: string;
  genblaze: {
    available: boolean;
    schemaVersion: string | null;
    runId: string | null;
    canonicalHash: string | null;
    verifyHash: boolean;
    outputAssetSha256: string | null;
    generator: string;
    mode: string;
    storedOnB2: boolean;
  };
  rooted: {
    manifestId: string;
    assetSha256: string;
    systemProvenance: Record<string, unknown>;
    signatureValid: boolean;
    publicKeyHex: string;
  };
  reconciled: boolean;
};

const short = (s: string | null, n = 16) => (s ? (s.length > n ? `${s.slice(0, n)}…` : s) : "-");

export function GenblazePanel() {
  const [d, setD] = useState<Reconcile | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/genblaze-manifest")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j: Reconcile) => setD(j))
      .catch(() => setError(true));
  }, []);

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">
        Genblaze integrity + Veridex C2PA
      </h2>
      <p className="mb-3 text-[11px] text-white/55">
        One asset, two trust layers. A real Genblaze generation was written to Backblaze B2 by
        Genblaze&apos;s own storage sink; Genblaze proves integrity (its Mode 1), and Veridex adds an
        Ed25519/COSE signature and a C2PA claim over the same bytes (recovery and the transparency
        log are demonstrated in the panels above).
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !d && <p className="font-mono text-sm text-white/50">Reconciling manifests…</p>}

      {d && (
        <>
          <p
            className={`mb-3 font-mono text-sm ${d.reconciled ? "text-emerald-300" : "text-amber-400"}`}
          >
            {d.reconciled
              ? "✓ reconciled: same asset, both layers verify"
              : "not reconciled"}
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
              <p className="mb-2 text-[11px] uppercase tracking-widest text-white/45">
                Genblaze · integrity (Mode 1)
              </p>
              <dl className="grid gap-1 font-mono text-xs text-white/70">
                <Row k="generator" v={d.genblaze.generator} />
                <Row k="hash verified" v={d.genblaze.verifyHash ? "✓ true" : "✗ false"} />
                <Row k="canonical hash" v={short(d.genblaze.canonicalHash)} />
                <Row k="run id" v={short(d.genblaze.runId)} />
                <Row k="output sha256" v={short(d.genblaze.outputAssetSha256)} />
                <Row k="stored on B2" v={d.genblaze.storedOnB2 ? "✓ via ObjectStorageSink" : "no"} />
              </dl>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
              <p className="mb-2 text-[11px] uppercase tracking-widest text-white/45">
                Veridex · signed (Ed25519/COSE)
              </p>
              <dl className="grid gap-1 font-mono text-xs text-white/70">
                <Row k="manifest" v={short(d.rooted.manifestId, 22)} />
                <Row k="asset sha256" v={short(d.rooted.assetSha256)} />
                <Row k="signature" v={d.rooted.signatureValid ? "✓ valid" : "✗ invalid"} />
                <Row
                  k="model"
                  v={String((d.rooted.systemProvenance as { model?: string })?.model ?? "-")}
                />
                <Row k="signing key" v={short(d.rooted.publicKeyHex)} />
              </dl>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-white/50">
            Reconcile: Genblaze output sha256 = Veridex asset sha256 = the asset bytes&apos; sha256.
            Genblaze signing (Mode 2) and C2PA interop (Mode 3) are not shipped, so Veridex&apos;s
            signing layer is load-bearing, not redundant.
          </p>
        </>
      )}
    </section>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-3">
      <dt className="w-28 shrink-0 text-white/55">{k}</dt>
      <dd className="break-all text-white/80">{v}</dd>
    </div>
  );
}
