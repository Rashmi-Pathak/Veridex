"use client";

import { useEffect, useState } from "react";

// Two-layer integrity clash, fetched live from /api/demo/integrity-clash. The EMBEDDED C2PA
// manifest travels inside the file, so anyone can strip it or swap in a forged claim. The
// RECOVERED record is the signed, transparency-log-anchored registry entry Veridex finds again by
// watermark or perceptual hash. The server compares the two layers field by field and returns the
// verdict; the embedded side is a staged attack-demonstration fixture (the response says so in
// stagedNote, rendered prominently below), while the recovered record and the verdict are computed
// for real. Nothing here is hardcoded; every value comes from the live response.

type SystemProvenance = {
  model?: string;
  provider?: string;
  digitalSourceType?: string;
  [k: string]: unknown;
};

type Recovered = {
  manifestId: string;
  assetSha256: string;
  createdAt: string;
  systemProvenance: SystemProvenance;
  personalProvenance: Record<string, unknown>;
  softBindings: unknown[];
};

type Embedded = {
  digitalSourceType?: string;
  model?: string;
  provider?: string;
  assetSha256?: string;
  claimGenerator?: string;
};

type Contradiction = {
  field: string;
  embedded: string;
  recovered: string;
  meaning: string;
};

type Verdict = {
  clash: boolean;
  contradictions: Contradiction[];
  fieldsCompared: string[];
};

type Clash = {
  staged: boolean;
  stagedNote: string;
  available: boolean;
  manifestId: string | null;
  recovered: Recovered | null;
  embedded: Embedded | null;
  verdict: Verdict | null;
  note: string;
};

// "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture" -> "digitalCapture"
function lastSegment(value?: string): string {
  if (!value) return "";
  const parts = value.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? value;
}

export function IntegrityClashPanel() {
  const [data, setData] = useState<Clash | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/integrity-clash")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: Clash) => setData(d))
      .catch(() => setError(true));
  }, []);

  const verdict = data?.verdict ?? null;

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">
        Integrity clash · embedded claim vs recovered record
      </h2>
      <p className="mb-3 text-[11px] text-white/55">
        An embedded C2PA manifest travels with the file, so anyone can strip it or replace it with a
        forged claim. Veridex recovers the signed, transparency-log-anchored registry record by
        watermark or fingerprint, compares the two layers field by field, and names every
        contradiction.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !data && (
        <p className="font-mono text-sm text-white/50">Comparing provenance layers…</p>
      )}

      {data && (
        <div className="mb-3 rounded-lg border border-amber-400/30 bg-amber-500/[0.06] p-3">
          <p className="font-mono text-xs text-amber-300">STAGED DEMONSTRATION</p>
          <p className="mt-1 text-[11px] text-white/55">{data.stagedNote}</p>
        </div>
      )}

      {data && !data.available && <p className="font-mono text-sm text-white/60">{data.note}</p>}

      {data && data.available && verdict && (
        <>
          <div className="flex items-center gap-2 font-mono text-sm">
            {verdict.clash ? (
              <span className="rounded bg-rose-400/10 px-2 py-0.5 text-rose-400">
                ✗ PROVENANCE CLASH
              </span>
            ) : (
              <span className="rounded bg-emerald-400/10 px-2 py-0.5 text-emerald-300">
                ✓ LAYERS AGREE
              </span>
            )}
            <span className="text-xs text-white/60">
              {verdict.fieldsCompared.length} fields compared
            </span>
          </div>
          <p className="mt-2 text-[11px] text-white/55">{data.note}</p>

          {verdict.clash && verdict.contradictions.length > 0 && (
            <div className="mt-3 rounded-lg border border-rose-400/30 bg-rose-500/[0.06] p-3">
              <dl className="grid gap-3 font-mono text-xs">
                {verdict.contradictions.map((c) => (
                  <div key={c.field}>
                    <dt className="text-white/60">{c.field}</dt>
                    <dd className="break-all text-rose-300 line-through">
                      {c.embedded} (embedded claim)
                    </dd>
                    <dd className="break-all text-emerald-300">{c.recovered} (recovered record)</dd>
                    <dd className="mt-0.5 font-sans text-[11px] text-white/55">{c.meaning}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          {data.embedded && data.recovered && (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-rose-400/20 bg-black/30 p-3">
                <p className="mb-2 font-mono text-[11px] uppercase tracking-widest text-rose-300/80">
                  embedded claim
                </p>
                <dl className="grid gap-1 font-mono text-xs text-white/70">
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-white/55">generator</dt>
                    <dd className="break-all text-white/80">{data.embedded.claimGenerator}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-white/55">source</dt>
                    <dd className="break-all text-white/80">
                      {lastSegment(data.embedded.digitalSourceType)}
                    </dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-white/55">model</dt>
                    <dd className="break-all text-white/80">{data.embedded.model}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-white/55">provider</dt>
                    <dd className="break-all text-white/80">{data.embedded.provider}</dd>
                  </div>
                </dl>
              </div>
              <div className="rounded-lg border border-emerald-400/20 bg-black/30 p-3">
                <p className="mb-2 font-mono text-[11px] uppercase tracking-widest text-emerald-300/80">
                  recovered record
                </p>
                <dl className="grid gap-1 font-mono text-xs text-white/70">
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-white/55">model</dt>
                    <dd className="break-all text-white/80">
                      {data.recovered.systemProvenance.model}
                    </dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-white/55">provider</dt>
                    <dd className="break-all text-white/80">
                      {data.recovered.systemProvenance.provider}
                    </dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-white/55">manifest</dt>
                    <dd className="break-all text-white/60">{data.recovered.manifestId}</dd>
                  </div>
                </dl>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
