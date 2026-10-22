"use client";

import { useEffect, useState } from "react";

// Watermark-removal failover, fetched live from /api/demo/remark-failover. The ReMark literature
// shows removal attacks (regeneration/diffusion) can scrub an invisible watermark out of an image.
// Veridex recovers by two independent soft bindings, so the server stages that attack live on the
// demo asset and reports both halves: whether the TrustMark watermark survived, and whether the PDQ
// perceptual fingerprint still matched the manifest. On deployments without the TrustMark model the
// watermark half reports attempted:false with an honest note (that state is rendered as informative,
// not as an error). Nothing here is hardcoded; the verdict and every value come from the live
// response.

type Attack = {
  name: string;
  parameters: { gaussianBlurRadius: number; jpegQuality: number };
  note: string;
};

type Watermark = {
  attempted: boolean;
  recovered: boolean;
  decodedId: string | null;
  expectedId: string;
  note: string | null;
};

type Fingerprint = {
  attempted: boolean;
  recovered: boolean;
  hammingDistance: number | null;
  threshold: number;
  matchedManifestId: string | null;
};

type RemarkFailover = {
  available: boolean;
  staged: boolean;
  stagedNote: string;
  reason?: string | null;
  attack: Attack | null;
  watermark: Watermark | null;
  fingerprint: Fingerprint | null;
  verdict: string | null;
};

export function RemarkPanel() {
  const [data, setData] = useState<RemarkFailover | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/remark-failover")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: RemarkFailover) => setData(d))
      .catch(() => setError(true));
  }, []);

  const attack = data?.attack ?? null;
  const wm = data?.watermark ?? null;
  const fp = data?.fingerprint ?? null;

  const wmBorder = !wm?.attempted
    ? "border-white/10"
    : wm.recovered
      ? "border-emerald-400/20"
      : "border-rose-400/20";

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">
        Watermark removal · fingerprint failover
      </h2>
      <p className="mb-3 text-[11px] text-white/55">
        ReMark-class removal attacks scrub the invisible watermark out of an image while keeping it
        recognizable. Veridex carries a second, independent soft binding, a perceptual fingerprint of
        the image structure the attack has to preserve. When the watermark is destroyed, the
        fingerprint still recovers the manifest, so recovery survives removal.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !data && (
        <p className="font-mono text-sm text-white/50">Staging the removal attack…</p>
      )}

      {data && (
        <div className="mb-3 rounded-lg border border-amber-400/30 bg-amber-500/[0.06] p-3">
          <p className="font-mono text-xs text-amber-300">STAGED DEMONSTRATION</p>
          <p className="mt-1 text-[11px] text-white/55">{data.stagedNote}</p>
        </div>
      )}

      {data && !data.available && (
        <p className="font-mono text-sm text-white/60">{data.reason}</p>
      )}

      {data && data.available && attack && wm && fp && (
        <>
          <div className="rounded-lg border border-white/10 bg-black/30 p-3">
            <p className="mb-2 font-mono text-[11px] uppercase tracking-widest text-white/50">
              attack
            </p>
            <p className="font-mono text-xs text-white/80">{attack.name}</p>
            <dl className="mt-2 grid gap-1 font-mono text-xs text-white/70">
              <div className="flex gap-2">
                <dt className="w-28 shrink-0 text-white/55">blur radius</dt>
                <dd className="text-white/80">{attack.parameters.gaussianBlurRadius}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-28 shrink-0 text-white/55">JPEG quality</dt>
                <dd className="text-white/80">{attack.parameters.jpegQuality}</dd>
              </div>
            </dl>
            <p className="mt-2 text-[11px] text-white/55">{attack.note}</p>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className={`rounded-lg border ${wmBorder} bg-black/30 p-3`}>
              <p className="mb-2 font-mono text-[11px] uppercase tracking-widest text-white/60">
                watermark (TrustMark)
              </p>
              {wm.attempted ? (
                <>
                  {wm.recovered ? (
                    <span className="rounded bg-emerald-400/10 px-2 py-0.5 font-mono text-xs text-emerald-300">
                      ✓ survived
                    </span>
                  ) : (
                    <span className="rounded bg-rose-400/10 px-2 py-0.5 font-mono text-xs text-rose-400">
                      ✗ destroyed
                    </span>
                  )}
                  <dl className="mt-2 grid gap-1 font-mono text-xs text-white/70">
                    <div className="flex gap-2">
                      <dt className="w-20 shrink-0 text-white/55">decoded</dt>
                      <dd className="break-all text-white/80">{wm.decodedId ?? "(none)"}</dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="w-20 shrink-0 text-white/55">expected</dt>
                      <dd className="break-all text-white/80">{wm.expectedId}</dd>
                    </div>
                  </dl>
                  {wm.note && <p className="mt-2 text-[11px] text-white/55">{wm.note}</p>}
                </>
              ) : (
                <>
                  <span className="rounded bg-white/[0.06] px-2 py-0.5 font-mono text-xs text-white/60">
                    not run in this deployment
                  </span>
                  {wm.note && <p className="mt-2 text-[11px] text-white/55">{wm.note}</p>}
                </>
              )}
            </div>

            <div
              className={`rounded-lg border ${
                fp.recovered ? "border-emerald-400/20" : "border-rose-400/20"
              } bg-black/30 p-3`}
            >
              <p className="mb-2 font-mono text-[11px] uppercase tracking-widest text-white/60">
                fingerprint (PDQ)
              </p>
              {fp.recovered ? (
                <span className="rounded bg-emerald-400/10 px-2 py-0.5 font-mono text-xs text-emerald-300">
                  ✓ recovered
                </span>
              ) : (
                <span className="rounded bg-rose-400/10 px-2 py-0.5 font-mono text-xs text-rose-400">
                  ✗ lost
                </span>
              )}
              {typeof fp.hammingDistance === "number" && (
                <p className="mt-2 font-mono text-white/70">
                  distance <span className="text-lg text-white/90">{fp.hammingDistance}</span> of{" "}
                  <span className="text-white/60">{fp.threshold}</span>
                </p>
              )}
              {fp.matchedManifestId && (
                <dl className="mt-2 grid gap-1 font-mono text-xs text-white/70">
                  <div className="flex gap-2">
                    <dt className="w-20 shrink-0 text-white/55">manifest</dt>
                    <dd className="break-all text-white/60">{fp.matchedManifestId}</dd>
                  </div>
                </dl>
              )}
            </div>
          </div>

          {data.verdict && (
            <div className="mt-4 rounded-lg border border-white/10 bg-black/30 p-3">
              <p className="font-mono text-[11px] uppercase tracking-widest text-white/50">
                verdict
              </p>
              <p className="mt-1 text-[11px] text-white/70">{data.verdict}</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
