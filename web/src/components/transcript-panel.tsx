"use client";

import { useEffect, useState } from "react";

// Genblaze's newest connector (AssemblyAI speech-to-text) + Veridex, on one artifact. A real AI
// speech clip (/api/demo/speech, an ElevenLabs clip) was transcribed by Genblaze into a hash-verified
// TEXT transcript with word-level timings, and the run was persisted to Backblaze B2 via Genblaze's
// own S3 backend. /api/demo/transcript re-verifies the native Genblaze manifest at request time and
// reconciles it with Veridex's signed manifest over the same transcript bytes. Three axes, one piece:
// AI-generated audio, Genblaze's newest connector, and Backblaze B2 storage.
type WordTiming = { word: string; start: number; end: number; confidence: number | null };

type Reconcile = {
  available: boolean;
  transcript: string;
  wordCount: number;
  wordTimings: WordTiming[];
  language: string | null;
  audioDuration: number | null;
  sourceAudioUrl: string;
  assetSha256: string;
  genblaze: {
    available: boolean;
    runId: string | null;
    canonicalHash: string | null;
    verifyHash: boolean;
    outputAssetSha256: string | null;
    generator: string;
    storedOnB2: boolean;
    b2Keys: string[];
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
const prov = (d: Reconcile, k: string) =>
  String((d.rooted.systemProvenance as Record<string, unknown>)?.[k] ?? "-");

export function TranscriptPanel() {
  const [d, setD] = useState<Reconcile | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/transcript")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j: Reconcile) => setD(j))
      .catch(() => setError(true));
  }, []);

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">
        Genblaze speech-to-text + Veridex C2PA
      </h2>
      <p className="mb-3 text-[11px] text-white/55">
        Genblaze&apos;s newest connector (AssemblyAI) transcribes a real AI speech clip into a
        hash-verified transcript with word-level timings, persisted to Backblaze B2 by
        Genblaze&apos;s own storage backend. Veridex re-verifies it and adds an Ed25519/COSE signature
        and a C2PA claim over the same transcript bytes.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !d && <p className="font-mono text-sm text-white/50">Transcribing…</p>}

      {d && d.available && (
        <>
          <p
            className={`mb-3 font-mono text-sm ${d.reconciled ? "text-emerald-300" : "text-amber-400"}`}
          >
            {d.reconciled
              ? "✓ reconciled: same transcript, both layers verify"
              : "not reconciled"}
          </p>

          <audio controls preload="none" src={`/api${d.sourceAudioUrl}`} className="mb-3 w-full">
            <track kind="captions" />
          </audio>

          <blockquote className="mb-3 rounded-lg border border-white/10 bg-white/[0.03] p-4 text-sm leading-relaxed text-white/80">
            {d.transcript}
          </blockquote>

          <div className="mb-3 flex flex-wrap gap-1.5">
            {d.wordTimings.slice(0, 14).map((w, i) => (
              <span
                key={i}
                className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-white/70"
                title={`${w.start.toFixed(2)}-${w.end.toFixed(2)}s`}
              >
                {w.word}{" "}
                <span className="text-white/40">{w.start.toFixed(1)}s</span>
              </span>
            ))}
            {d.wordCount > 14 && (
              <span className="px-1.5 py-0.5 font-mono text-[10px] text-white/40">
                +{d.wordCount - 14} more
              </span>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
              <p className="mb-2 text-[11px] uppercase tracking-widest text-white/45">
                Genblaze · transcript integrity (Mode 1)
              </p>
              <dl className="grid gap-1 font-mono text-xs text-white/70">
                <Row k="connector" v={`${prov(d, "provider")} · ${prov(d, "model")}`} />
                <Row k="hash verified" v={d.genblaze.verifyHash ? "✓ true" : "✗ false"} />
                <Row k="words" v={`${d.wordCount} · ${d.language ?? "-"} · ${d.audioDuration ?? "-"}s`} />
                <Row k="canonical hash" v={short(d.genblaze.canonicalHash)} />
                <Row k="output sha256" v={short(d.genblaze.outputAssetSha256)} />
                <Row
                  k="stored on B2"
                  v={
                    d.genblaze.storedOnB2
                      ? `✓ ${short(d.genblaze.b2Keys?.[0] ?? "via S3 backend", 22)}`
                      : "no"
                  }
                />
              </dl>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
              <p className="mb-2 text-[11px] uppercase tracking-widest text-white/45">
                Veridex · signed (Ed25519/COSE)
              </p>
              <dl className="grid gap-1 font-mono text-xs text-white/70">
                <Row k="manifest" v={short(d.rooted.manifestId, 24)} />
                <Row k="asset sha256" v={short(d.rooted.assetSha256)} />
                <Row k="signature" v={d.rooted.signatureValid ? "✓ valid" : "✗ invalid"} />
                <Row k="kind" v={prov(d, "kind")} />
                <Row k="signing key" v={short(d.rooted.publicKeyHex)} />
              </dl>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-white/50">
            Reconcile: Genblaze output sha256 = Veridex asset sha256 = the transcript bytes&apos;
            sha256. The audio is AI-generated, the transcript comes from Genblaze&apos;s newest
            connector, and both live in Backblaze B2.
          </p>
        </>
      )}

      {d && !d.available && (
        <p className="font-mono text-sm text-white/50">
          Transcript fixture not present in this deploy.
        </p>
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
