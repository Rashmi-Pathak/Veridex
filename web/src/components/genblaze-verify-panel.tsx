"use client";

import { useEffect, useState } from "react";

// genblaze v0.6.0 shipped `genblaze verify --fetch`: it downloads each output asset and confirms its
// bytes hash to the manifest's committed sha256 (with a size cross-check), on top of the canonical-
// hash and declared-sha256 checks. /api/demo/genblaze-verify runs that byte-level verification on the
// real Genblaze asset Veridex stored to Backblaze B2: genblaze-core re-verifies the native manifest
// (Mode 1), then the asset bytes are fetched (a presigned GET against the private B2 bucket, falling
// back to the committed content-addressed copy) and hashed and compared. Genblaze proves integrity;
// Veridex adds the Ed25519/COSE signature, the C2PA claim, recovery, and the transparency proof.
type Verify = {
  available: boolean;
  genblazeVersion: string | null;
  schemaVersion: string | null;
  runId: string | null;
  hashOk: boolean;
  outputsAllSha256: boolean;
  metadataInSpec: boolean;
  manifestVerified: boolean;
  byteSource: string;
  byteVerified: boolean;
  sizeVerified: boolean;
  declaredSha256: string | null;
  fetchedSha256: string | null;
  declaredSizeBytes: number | null;
  fetchedSizeBytes: number | null;
  assetHost: string | null;
  verified: boolean;
  note: string;
};

const short = (s: string | null, n = 16) => (s ? (s.length > n ? `${s.slice(0, n)}…` : s) : "-");
const yn = (b: boolean) => (b ? "✓ true" : "✗ false");
const sourceLabel: Record<string, string> = {
  b2: "Backblaze B2 (presigned)",
  fixture: "committed copy",
  none: "unavailable",
};

export function GenblazeVerifyPanel() {
  const [d, setD] = useState<Verify | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/genblaze-verify")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j: Verify) => setD(j))
      .catch(() => setError(true));
  }, []);

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">
        Genblaze v0.6.0 · byte-level verify
      </h2>
      <p className="mb-3 text-[11px] text-white/55">
        genblaze v0.6.0 shipped <code className="text-white/70">genblaze verify --fetch</code>, which
        downloads each output asset and confirms its bytes hash to the manifest&apos;s committed
        sha256. Veridex runs that check on the real Genblaze asset it stored to Backblaze B2.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !d && <p className="font-mono text-sm text-white/50">Verifying…</p>}

      {d && !d.available && (
        <p className="font-mono text-sm text-amber-400">Verification unavailable: {d.note}.</p>
      )}

      {d && d.available && (
        <>
          <p
            className={`mb-3 font-mono text-sm ${d.verified ? "text-emerald-300" : "text-amber-400"}`}
          >
            {d.verified
              ? "✓ verified: the stored asset bytes hash to the manifest's committed sha256"
              : "not verified"}
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
              <p className="mb-2 text-[11px] uppercase tracking-widest text-white/45">
                Genblaze · manifest (Mode 1)
              </p>
              <dl className="grid gap-1 font-mono text-xs text-white/70">
                <Row k="hash ok" v={yn(d.hashOk)} />
                <Row k="outputs sha256" v={yn(d.outputsAllSha256)} />
                <Row k="metadata in spec" v={yn(d.metadataInSpec)} />
                <Row k="schema" v={d.schemaVersion ?? "-"} />
                <Row k="genblaze-core" v={d.genblazeVersion ?? "-"} />
                <Row k="run id" v={short(d.runId)} />
              </dl>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
              <p className="mb-2 text-[11px] uppercase tracking-widest text-white/45">
                Byte-level · verify --fetch
              </p>
              <dl className="grid gap-1 font-mono text-xs text-white/70">
                <Row k="byte source" v={sourceLabel[d.byteSource] ?? d.byteSource} />
                <Row k="bytes match" v={yn(d.byteVerified)} />
                <Row k="size match" v={yn(d.sizeVerified)} />
                <Row k="committed sha256" v={short(d.declaredSha256)} />
                <Row k="fetched sha256" v={short(d.fetchedSha256)} />
                <Row k="asset host" v={d.assetHost ?? "-"} />
              </dl>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-white/50">
            genblaze-core re-verifies the native manifest and the asset bytes are re-hashed against
            its committed sha256. Genblaze proves integrity (its Mode 1); Veridex adds the Ed25519/COSE
            signature, the C2PA claim, recovery, and the transparency proof, which Genblaze does not.
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
