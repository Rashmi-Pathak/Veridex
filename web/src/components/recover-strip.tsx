"use client";

import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

// The headline visual. It does not describe the thesis, it performs it on one real image: a
// credentialed AI asset is stripped in the browser by a genuine JPEG re-encode (which drops any
// embedded C2PA manifest), then Veridex recovers the provenance with a live call to the SBR API. The
// "VERIFIED" result is the real registry response, never hardcoded. Visual direction: a refined split
// wipe, where the rose "stripped" state is swept left to right by the emerald "VERIFIED" state.

type Phase =
  | "loading"
  | "credentialed"
  | "stripping"
  | "stripped"
  | "scanning"
  | "recovered"
  | "failed"
  | "error";

// The /matches/byContent response shape (mirrors the generated SBR schema). Read defensively: at
// runtime the matches array and its scores may be absent.
interface MatchResult {
  manifestId: string;
  similarityScore: number | null;
  endpoint: string | null;
}

interface ByContentResponse {
  matches?: MatchResult[];
}

interface Recovered {
  manifestId: string;
  similarityScore: number | null;
}

const STATUS_COLOR: Record<Phase, string> = {
  loading: "text-sky-300",
  credentialed: "text-emerald-300",
  stripping: "text-amber-300",
  stripped: "text-rose-300",
  scanning: "text-sky-300",
  recovered: "text-emerald-300",
  failed: "text-rose-400",
  error: "text-amber-400",
};

const STATUS_NODE: Record<Phase, ReactNode> = {
  loading: "Fetching the credentialed sample, please wait.",
  credentialed: "This image carries C2PA Content Credentials.",
  stripping: "Re-encoding the image, the embedded credential is being removed.",
  stripped: "Credential stripped. The embedded provenance is gone.",
  scanning: (
    <span className="inline-flex items-center gap-2">
      <span className="h-2 w-2 animate-ping rounded-full bg-sky-300" />
      Scanning the registry for a soft-binding match.
    </span>
  ),
  recovered: "Provenance recovered from the registry.",
  failed: "No match. This asset is not in the registry.",
  error: "Backend unreachable. The recovery API did not respond.",
};

export function RecoverStrip() {
  const reduce = useReducedMotion() ?? false;

  const [phase, setPhase] = useState<Phase>("loading");
  const [credentialedUrl, setCredentialedUrl] = useState<string | null>(null);
  const [strippedUrl, setStrippedUrl] = useState<string | null>(null);
  const [imgLoaded, setImgLoaded] = useState(false);
  const [recovered, setRecovered] = useState<Recovered | null>(null);

  const imgRef = useRef<HTMLImageElement | null>(null);
  const strippedBlobRef = useRef<Blob | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  // The displayed source is the stripped re-encode once it exists, otherwise the credentialed
  // original. It is always the SAME <img> element, so the strip and recover happen in place.
  const imgSrc = strippedUrl ?? credentialedUrl;
  const showRose =
    phase === "stripped" || phase === "scanning" || phase === "recovered" || phase === "failed";

  const loadSample = useCallback(async (signal: AbortSignal) => {
    setPhase("loading");
    try {
      const res = await fetch("/api/demo/sample", { signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      if (signal.aborted) return;
      setImgLoaded(false);
      setCredentialedUrl(URL.createObjectURL(blob));
      setPhase("credentialed");
    } catch (err) {
      if (signal.aborted || (err instanceof DOMException && err.name === "AbortError")) return;
      setPhase("error");
    }
  }, []);

  const start = useCallback(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    void loadSample(controller.signal);
  }, [loadSample]);

  // Fetch the credentialed demo image on mount.
  useEffect(() => {
    start();
    return () => controllerRef.current?.abort();
  }, [start]);

  // Revoke object URLs to avoid leaks: the cleanup runs with the previous value when the URL changes,
  // and on unmount for the current value.
  useEffect(() => {
    return () => {
      if (credentialedUrl) URL.revokeObjectURL(credentialedUrl);
    };
  }, [credentialedUrl]);

  useEffect(() => {
    return () => {
      if (strippedUrl) URL.revokeObjectURL(strippedUrl);
    };
  }, [strippedUrl]);

  function strip() {
    const img = imgRef.current;
    if (!img || img.naturalWidth === 0 || img.naturalHeight === 0) return;
    setPhase("stripping");
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      setPhase("error");
      return;
    }
    ctx.drawImage(img, 0, 0);
    // Real strip: re-encoding to a fresh JPEG drops any embedded C2PA metadata. toBlob is async.
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          setPhase("error");
          return;
        }
        strippedBlobRef.current = blob;
        setStrippedUrl(URL.createObjectURL(blob));
        setPhase("stripped");
      },
      "image/jpeg",
      0.92,
    );
  }

  async function recover() {
    const blob = strippedBlobRef.current;
    if (!blob) return;
    setPhase("scanning");
    setRecovered(null);
    try {
      const body = new FormData();
      body.append("file", blob, "stripped.jpg");
      const res = await fetch("/api/matches/byContent", { method: "POST", body });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ByContentResponse;
      const match = data.matches?.[0];
      if (match) {
        setRecovered({
          manifestId: match.manifestId,
          similarityScore: match.similarityScore ?? null,
        });
        setPhase("recovered");
      } else {
        setPhase("failed");
      }
    } catch {
      setPhase("error");
    }
  }

  function retry() {
    strippedBlobRef.current = null;
    setStrippedUrl(null);
    setRecovered(null);
    start();
  }

  function renderAction(): ReactNode {
    const base =
      "rounded-lg border px-5 py-2.5 font-mono text-xs uppercase tracking-widest transition disabled:cursor-not-allowed disabled:opacity-40";
    switch (phase) {
      case "credentialed":
        return (
          <button
            type="button"
            onClick={strip}
            disabled={!imgLoaded}
            className={`${base} border-white/25 text-white/85 hover:border-rose-400/50 hover:bg-rose-500/[0.06] hover:text-rose-200`}
          >
            Strip the credential
          </button>
        );
      case "stripped":
        return (
          <button
            type="button"
            onClick={() => void recover()}
            className={`${base} border-emerald-300/45 text-emerald-200 hover:border-emerald-300/80 hover:bg-emerald-400/10`}
          >
            Recover provenance
          </button>
        );
      case "loading":
      case "stripping":
      case "scanning":
        return (
          <button type="button" disabled className={`${base} border-white/20 text-white/60`}>
            {phase === "scanning" ? "Recovering" : "Working"}
          </button>
        );
      case "error":
      case "failed":
        return (
          <button
            type="button"
            onClick={retry}
            className={`${base} border-white/25 text-white/80 hover:border-white/45 hover:bg-white/[0.04]`}
          >
            Reload the sample
          </button>
        );
      case "recovered":
        return (
          <button
            type="button"
            onClick={retry}
            className={`${base} border-white/25 text-white/80 hover:border-white/45 hover:bg-white/[0.04]`}
          >
            Run it again
          </button>
        );
    }
  }

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-6 backdrop-blur-md">
      <p className="font-mono text-[11px] uppercase tracking-widest text-white/45">
        Strip and recover
      </p>
      <h2 className="mt-1 text-lg font-semibold text-white/90">
        The same image, stripped then recovered
      </h2>
      <p className="mt-1 max-w-prose text-sm text-white/60">
        A credentialed AI image loses its provenance to a real in-browser re-encode, then Veridex
        recovers it with a live call to the SBR API. Nothing here is staged.
      </p>

      <div className="mt-6 flex flex-col items-center gap-6">
        <div className="relative w-full max-w-md">
          <div className="relative aspect-square overflow-hidden rounded-lg border border-white/10 bg-black/40 shadow-[0_0_70px_-22px_rgba(52,211,153,0.3)]">
            {imgSrc ? (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  ref={imgRef}
                  src={imgSrc}
                  onLoad={() => setImgLoaded(true)}
                  alt={
                    phase === "recovered"
                      ? "AI generated demo image, its provenance recovered and verified"
                      : showRose
                        ? "AI generated demo image with its content credential stripped"
                        : "AI generated demo image carrying content credentials"
                  }
                  className="h-full w-full object-cover"
                />

                <AnimatePresence>
                  {phase === "credentialed" && (
                    <motion.div
                      key="cc"
                      initial={{ opacity: 0, scale: 0.92 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.85, rotate: -10, y: 16, filter: "blur(3px)" }}
                      transition={{ duration: 0.5, ease: "easeOut" }}
                      className="absolute right-3 top-3 flex items-center gap-2 rounded-full border border-emerald-300/60 bg-emerald-300/10 px-2.5 py-1 backdrop-blur-sm"
                    >
                      <span className="inline-flex h-5 w-5 items-center justify-center rounded-full rounded-br-none border border-emerald-300/70 font-mono text-[10px] font-semibold lowercase text-emerald-300">
                        cr
                      </span>
                      <span className="font-mono text-[11px] text-emerald-200">
                        Content Credentials
                      </span>
                    </motion.div>
                  )}

                  {showRose && (
                    <motion.div
                      key="rose"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.4 }}
                      className="pointer-events-none absolute inset-0 rounded-lg ring-1 ring-inset ring-rose-400/40"
                    >
                      <div className="absolute inset-0 bg-gradient-to-br from-rose-500/12 via-transparent to-transparent" />
                      <div className="absolute left-3 top-3 flex items-center gap-2 rounded-full border border-rose-400/50 bg-rose-500/10 px-2.5 py-1 backdrop-blur-sm">
                        <BrokenBadge />
                        <span className="font-mono text-[11px] text-rose-200">No credentials</span>
                      </div>
                    </motion.div>
                  )}

                  {phase === "scanning" && (
                    <motion.div
                      key="scan"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.3 }}
                      className="pointer-events-none absolute inset-0"
                    >
                      <div className="absolute inset-0 ring-1 ring-inset ring-sky-300/40" />
                      {!reduce && (
                        <motion.div
                          className="absolute inset-x-0 h-16 bg-gradient-to-b from-transparent via-sky-300/25 to-transparent"
                          initial={{ top: "-20%" }}
                          animate={{ top: ["-20%", "100%"] }}
                          transition={{ duration: 1.4, ease: "linear", repeat: Infinity }}
                        />
                      )}
                      <div className="absolute left-3 top-3 flex items-center gap-2 rounded-full border border-sky-300/50 bg-sky-400/10 px-2.5 py-1 backdrop-blur-sm">
                        <span className="h-2 w-2 animate-ping rounded-full bg-sky-300" />
                        <span className="font-mono text-[11px] text-sky-200">Scanning</span>
                      </div>
                    </motion.div>
                  )}

                  {phase === "recovered" && (
                    <motion.div
                      key="wipe"
                      className="pointer-events-none absolute inset-0"
                      initial={reduce ? { opacity: 0 } : { clipPath: "inset(0% 100% 0% 0%)" }}
                      animate={reduce ? { opacity: 1 } : { clipPath: "inset(0% 0% 0% 0%)" }}
                      transition={{ duration: reduce ? 0.4 : 0.9, ease: [0.65, 0, 0.35, 1] }}
                    >
                      <div className="absolute inset-0 ring-1 ring-inset ring-emerald-300/60" />
                      <div className="absolute inset-0 bg-gradient-to-tr from-emerald-500/18 via-emerald-400/6 to-transparent" />
                      <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
                        <motion.div
                          initial={{ opacity: 0, scale: 0.6 }}
                          animate={{ opacity: 1, scale: 1 }}
                          transition={{ delay: reduce ? 0 : 0.45, duration: 0.5, ease: "easeOut" }}
                          className="relative flex h-24 w-24 items-center justify-center rounded-full border border-emerald-300/70 bg-emerald-400/10 shadow-[0_0_45px_rgba(52,211,153,0.45)] backdrop-blur-sm"
                        >
                          <span className="absolute inset-0 rounded-full ring-1 ring-emerald-200/30" />
                          <CheckMark />
                        </motion.div>
                        <motion.span
                          initial={{ opacity: 0, y: reduce ? 0 : 8 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: reduce ? 0 : 0.6, duration: 0.45 }}
                          className="font-mono text-lg font-semibold tracking-[0.35em] text-emerald-200 drop-shadow-[0_0_12px_rgba(52,211,153,0.6)]"
                        >
                          VERIFIED
                        </motion.span>
                      </div>
                    </motion.div>
                  )}

                  {phase === "recovered" && !reduce && (
                    <motion.div
                      key="wipe-edge"
                      className="pointer-events-none absolute inset-y-0 w-[2px] bg-emerald-200 shadow-[0_0_24px_6px_rgba(52,211,153,0.8)]"
                      initial={{ left: "0%", opacity: 0 }}
                      animate={{ left: ["0%", "100%"], opacity: [0, 1, 1, 0] }}
                      transition={{ duration: 0.9, ease: [0.65, 0, 0.35, 1] }}
                    />
                  )}
                </AnimatePresence>
              </>
            ) : (
              <div className="flex h-full w-full items-center justify-center">
                <span className="inline-flex items-center gap-2 font-mono text-xs text-sky-300">
                  <span className="h-2 w-2 animate-ping rounded-full bg-sky-300" />
                  Loading the credentialed sample
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="flex w-full max-w-md flex-col items-center gap-4">
          <div className="min-h-[2.5rem] text-center" role="status" aria-live="polite">
            <AnimatePresence mode="wait">
              <motion.p
                key={phase}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.25 }}
                className={`font-mono text-sm ${STATUS_COLOR[phase]}`}
              >
                {STATUS_NODE[phase]}
              </motion.p>
            </AnimatePresence>
          </div>

          {renderAction()}

          {phase === "recovered" && recovered && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: reduce ? 0 : 0.7, duration: 0.4 }}
              className="w-full rounded-lg border border-emerald-300/25 bg-emerald-400/[0.04] p-4 text-left"
            >
              <p className="mb-2 font-mono text-[11px] uppercase tracking-widest text-emerald-300/80">
                Recovered manifest
              </p>
              <dl>
                <Row k="manifest" v={recovered.manifestId} />
                <Row
                  k="similarity"
                  v={
                    recovered.similarityScore != null
                      ? `${recovered.similarityScore}/100`
                      : "exact (watermark)"
                  }
                />
              </dl>
            </motion.div>
          )}
        </div>
      </div>

      <p className="mt-6 border-t border-white/10 pt-4 font-mono text-[11px] text-white/45">
        The strip is a genuine canvas JPEG re-encode that drops embedded C2PA metadata. The recovery is
        a live SBR API call, the verified result is not hardcoded. Provenance proves origin, not truth.
      </p>
    </section>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-3 py-0.5 font-mono text-xs">
      <dt className="w-20 shrink-0 text-white/45">{k}</dt>
      <dd className="break-all text-white/80">{v}</dd>
    </div>
  );
}

function CheckMark() {
  return (
    <svg viewBox="0 0 24 24" className="h-10 w-10 text-emerald-200" fill="none" aria-hidden="true">
      <path
        d="M5 12.5 10 17.5 19 7"
        stroke="currentColor"
        strokeWidth="2.25"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function BrokenBadge() {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 text-rose-300" fill="none" aria-hidden="true">
      <circle
        cx="8"
        cy="8"
        r="6.25"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeDasharray="2.5 1.8"
      />
      <path d="M5 11 11 5" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  );
}
