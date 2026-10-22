"use client";

import { useRef, useState } from "react";

// Bring your own image: the judge-interactive loop. The browser asks the API for a presigned
// Backblaze B2 URL, PUTs the file DIRECT to B2 (the bytes never pass through the API), then asks
// the API to register the object: Veridex fetches it from B2, fingerprints it, appends it to the
// signed transparency log, and it becomes recoverable like every other asset. Each stage below
// flips only on the real response; nothing is faked. "Already registered" is a first-class honest
// outcome (re-uploading the same bytes resolves to the existing manifest).

const ALLOWED_TYPES = ["image/png", "image/jpeg", "image/webp"];
const MAX_BYTES = 26214400; // 25 MiB, the server-side limit

const CORS_BLOCKED_MESSAGE =
  "The direct-to-B2 upload was blocked in the browser (content security policy or bucket CORS). The API and registration flow are unaffected.";

type StageState = "pending" | "active" | "done" | "failed";

type Stages = { presign: StageState; put: StageState; register: StageState };

const IDLE_STAGES: Stages = { presign: "pending", put: "pending", register: "pending" };

const STAGE_ROWS: { key: keyof Stages; label: string }[] = [
  { key: "presign", label: "1 presign" },
  { key: "put", label: "2 direct PUT to B2" },
  { key: "register", label: "3 register + log append" },
];

type Failure = {
  // client = a pre-check stopped the run before any request; unconfigured = the server said 503
  // (BYO upload is not configured there); failed = a stage genuinely failed.
  kind: "client" | "unconfigured" | "failed";
  message: string;
};

type Presign = {
  uploadUrl: string;
  objectKey: string;
  bucket: string;
  contentType: string;
  expiresInSeconds: number;
  maxBytes: number;
};

type Registered = {
  manifestId: string;
  objectKey: string;
  bucket: string;
  backend: string;
  sizeBytes: number;
  assetSha256: string;
  alreadyRegistered: boolean;
  recoverable: boolean;
  note: string;
};

async function readDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    // non-JSON error body; fall through to the status line
  }
  return `HTTP ${res.status}`;
}

function stageText(state: StageState): string {
  if (state === "active") return "in progress…";
  if (state === "done") return "✓ done";
  if (state === "failed") return "✗ failed";
  return "pending";
}

function stageClass(state: StageState): string {
  if (state === "active") return "text-sky-300";
  if (state === "done") return "text-emerald-300";
  if (state === "failed") return "text-rose-400";
  return "text-white/40";
}

export function ByoUploadPanel() {
  const [fileName, setFileName] = useState<string | null>(null);
  const [stages, setStages] = useState<Stages>(IDLE_STAGES);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [result, setResult] = useState<Registered | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  function onFile(file: File) {
    // A new file aborts any in-flight run and resets every stage to pending.
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setFileName(file.name);
    setStages(IDLE_STAGES);
    setFailure(null);
    setResult(null);

    // Client-side pre-checks: no request is made when the file cannot succeed.
    if (!ALLOWED_TYPES.includes(file.type)) {
      setFailure({
        kind: "client",
        message: `Unsupported type "${file.type || "unknown"}". Pick a PNG, JPEG, or WebP image.`,
      });
      return;
    }
    if (file.size > MAX_BYTES) {
      setFailure({
        kind: "client",
        message: `This file is ${file.size.toLocaleString()} bytes; the limit is ${MAX_BYTES.toLocaleString()} bytes (25 MiB).`,
      });
      return;
    }

    void run(file, ctrl);
  }

  async function run(file: File, ctrl: AbortController) {
    // Stage 1: ask the API for a presigned B2 upload URL for exactly this type and size.
    setStages((s) => ({ ...s, presign: "active" }));
    let presign: Presign;
    try {
      const res = await fetch("/api/demo/byo/upload-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contentType: file.type, sizeBytes: file.size }),
        signal: ctrl.signal,
      });
      if (ctrl.signal.aborted) return;
      if (!res.ok) {
        const detail = await readDetail(res);
        if (ctrl.signal.aborted) return;
        setStages((s) => ({ ...s, presign: "failed" }));
        setFailure(
          res.status === 503
            ? { kind: "unconfigured", message: detail }
            : { kind: "failed", message: `Presign refused (HTTP ${res.status}): ${detail}` },
        );
        return;
      }
      presign = (await res.json()) as Presign;
    } catch {
      if (ctrl.signal.aborted) return;
      setStages((s) => ({ ...s, presign: "failed" }));
      setFailure({ kind: "failed", message: "Backend unreachable." });
      return;
    }
    if (ctrl.signal.aborted) return;
    setStages((s) => ({ ...s, presign: "done", put: "active" }));

    // Stage 2: PUT the raw bytes straight to Backblaze B2, cross-origin, no API in the path.
    try {
      const putRes = await fetch(presign.uploadUrl, {
        method: "PUT",
        headers: { "Content-Type": presign.contentType },
        body: file,
        signal: ctrl.signal,
      });
      if (ctrl.signal.aborted) return;
      if (!putRes.ok) {
        setStages((s) => ({ ...s, put: "failed" }));
        setFailure({
          kind: "failed",
          message: `Backblaze B2 refused the direct upload (HTTP ${putRes.status}).`,
        });
        return;
      }
    } catch {
      // A cross-origin PUT that never gets a response is the CORS signature in the browser.
      if (ctrl.signal.aborted) return;
      setStages((s) => ({ ...s, put: "failed" }));
      setFailure({ kind: "failed", message: CORS_BLOCKED_MESSAGE });
      return;
    }
    if (ctrl.signal.aborted) return;
    setStages((s) => ({ ...s, put: "done", register: "active" }));

    // Stage 3: register the B2 object; the API fetches it from B2, fingerprints it, and appends
    // a leaf to the signed transparency log.
    try {
      const res = await fetch("/api/demo/byo/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objectKey: presign.objectKey }),
        signal: ctrl.signal,
      });
      if (ctrl.signal.aborted) return;
      if (!res.ok) {
        const detail = await readDetail(res);
        if (ctrl.signal.aborted) return;
        setStages((s) => ({ ...s, register: "failed" }));
        if (res.status === 503) {
          setFailure({ kind: "unconfigured", message: detail });
        } else if (res.status === 404) {
          setFailure({
            kind: "failed",
            message: `${detail} The direct PUT to B2 may not have completed.`,
          });
        } else {
          setFailure({
            kind: "failed",
            message: `Registration refused (HTTP ${res.status}): ${detail}`,
          });
        }
        return;
      }
      const data = (await res.json()) as Registered;
      if (ctrl.signal.aborted) return;
      setStages((s) => ({ ...s, register: "done" }));
      setResult(data);
    } catch {
      if (ctrl.signal.aborted) return;
      setStages((s) => ({ ...s, register: "failed" }));
      setFailure({ kind: "failed", message: "Backend unreachable." });
    }
  }

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">
        Bring your own image · direct-to-B2 recovery loop
      </h2>
      <p className="mb-4 text-[11px] text-white/55">
        Pick any PNG, JPEG, or WebP. The browser uploads it straight to Backblaze B2 with a
        presigned URL (the file never passes through the API), Veridex ingests it from B2 into the
        signed transparency log, and it becomes recoverable like any other asset.
      </p>

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="flex w-full flex-col items-center gap-1 rounded-lg border border-dashed border-white/20 px-4 py-5 text-center transition hover:border-white/40 hover:bg-white/[0.03]"
      >
        <span className="text-sm text-white/70">Pick an image to upload straight to B2</span>
        <span className="font-mono text-xs text-white/55">
          {fileName ?? "PNG, JPEG, or WebP · up to 25 MiB"}
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          // Allow re-selecting the same file to re-run the loop.
          e.target.value = "";
        }}
      />

      <ol aria-label="upload stages" className="mt-4 grid gap-1 font-mono text-xs">
        {STAGE_ROWS.map(({ key, label }) => (
          <li
            key={key}
            className="flex items-center justify-between gap-2 rounded border border-white/10 bg-black/20 px-3 py-1.5"
          >
            <span className="text-white/70">{label}</span>
            <span className={stageClass(stages[key])}>{stageText(stages[key])}</span>
          </li>
        ))}
      </ol>

      {failure && (
        <p
          className={`mt-3 font-mono text-xs ${
            failure.kind === "failed" ? "text-rose-300" : "text-amber-300"
          }`}
        >
          {failure.message}
        </p>
      )}

      {result && (
        <div className="mt-4">
          <div className="flex items-center gap-2 font-mono text-sm">
            {result.alreadyRegistered ? (
              <span className="rounded bg-amber-400/10 px-2 py-0.5 text-amber-300">
                already registered
              </span>
            ) : (
              <span className="rounded bg-emerald-400/10 px-2 py-0.5 text-emerald-300">
                ✓ REGISTERED
              </span>
            )}
            <span className="text-xs text-white/60">
              {result.recoverable ? "recoverable" : "not recoverable"}
            </span>
          </div>

          <p className="mt-2 text-[11px] text-white/55">{result.note}</p>

          <dl className="mt-3 grid gap-1 font-mono text-xs text-white/70">
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-white/55">manifest</dt>
              <dd className="break-all text-white/80">{result.manifestId}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-white/55">sha256</dt>
              <dd className="break-all text-white/60">{result.assetSha256.slice(0, 32)}…</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-white/55">size</dt>
              <dd className="text-white/80">{result.sizeBytes.toLocaleString()} bytes</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-white/55">bucket</dt>
              <dd className="text-white/80">{result.bucket}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-white/55">backend</dt>
              <dd className="text-white/80">{result.backend}</dd>
            </div>
          </dl>

          <p className="mt-3 font-mono text-xs">
            <a
              href={`/r/${encodeURIComponent(result.manifestId)}`}
              className="text-emerald-300 underline-offset-4 hover:underline"
            >
              open the provenance receipt
            </a>
          </p>

          {!result.alreadyRegistered && (
            <p className="mt-2 text-[11px] text-white/55">
              The transparency log explorer below will show the new leaf on its next poll.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
