"use client";

import { useRef, useState, type DragEvent } from "react";
import { AnimatePresence, motion } from "motion/react";

import { $api } from "@/lib/api/client";

// The headline: drop a stripped asset, recover its provenance. Every visible state is driven by the
// typed client's query state (the demo-safe rule), not by anything cosmetic. FAILED is a real result
// (an un-provenanced image genuinely has no match); VERIFIED shows the recovered, signed manifest.
type Phase = "idle" | "scanning" | "verified" | "failed" | "error";

export function RecoverPanel() {
  const [fileName, setFileName] = useState<string | null>(null);
  const [manifestId, setManifestId] = useState<string | null>(null);
  const [score, setScore] = useState<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const recover = $api.useMutation("post", "/matches/byContent");
  const manifest = $api.useQuery(
    "get",
    "/manifests/{manifest_id}",
    { params: { path: { manifest_id: manifestId ?? "" } } },
    { enabled: manifestId != null },
  );

  function submit(file: File) {
    setFileName(file.name);
    setManifestId(null);
    setScore(null);
    recover.mutate(
      {
        // The schema types the multipart `file` field as string; we send the real File and let the
        // FormData serializer carry it (when bodySerializer returns FormData, fetch sets the boundary).
        body: { file: file as unknown as string },
        bodySerializer: (body) => {
          const fd = new FormData();
          fd.append("file", body.file as unknown as Blob);
          return fd;
        },
      },
      {
        onSuccess: (data) => {
          const match = data.matches?.[0];
          if (match) {
            setManifestId(match.manifestId);
            setScore(match.similarityScore ?? null);
          }
        },
      },
    );
  }

  function onDrop(e: DragEvent<HTMLButtonElement>) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) submit(file);
  }

  async function trySample() {
    // The backend seeds one real AI-generated asset (Genblaze on GMI Cloud) and serves its exact
    // bytes at /demo/sample; recovering it exercises the genuine loop (it is registered, so this
    // resolves to VERIFIED).
    const res = await fetch("/api/demo/sample");
    const blob = await res.blob();
    submit(new File([blob], "sample.jpg", { type: blob.type || "image/jpeg" }));
  }

  const phase: Phase = recover.isError
    ? "error"
    : recover.isPending
      ? "scanning"
      : recover.isSuccess
        ? (recover.data.matches?.length ?? 0) > 0
          ? "verified"
          : "failed"
        : "idle";

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.04] p-6 backdrop-blur-md">
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDrop={onDrop}
        onDragOver={(e) => e.preventDefault()}
        className="flex w-full flex-col items-center gap-2 rounded-lg border border-dashed border-white/20 px-6 py-8 text-center transition hover:border-white/40 hover:bg-white/[0.03]"
      >
        <span className="text-sm text-white/70">
          Drop a stripped image, or click to select
        </span>
        <span className="font-mono text-xs text-white/55">
          {fileName ?? "we match its watermark or fingerprint against the registry"}
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) submit(file);
        }}
      />

      <div className="mt-3 text-center">
        <button
          type="button"
          onClick={trySample}
          className="font-mono text-xs text-sky-300/80 underline-offset-4 hover:underline"
        >
          or recover the demo asset
        </button>
      </div>

      <div className="mt-5 min-h-24">
        <AnimatePresence mode="wait">
          {phase === "idle" && (
            <Slot key="idle" className="text-white/55">
              Awaiting an asset.
            </Slot>
          )}

          {phase === "scanning" && (
            <Slot key="scanning" className="text-sky-300">
              <span className="inline-flex items-center gap-2">
                <span className="h-2 w-2 animate-ping rounded-full bg-sky-300" />
                Scanning watermark and perceptual hash…
              </span>
            </Slot>
          )}

          {phase === "error" && (
            <Slot key="error" className="text-amber-400">
              Backend unreachable. Start it with{" "}
              <code className="text-white/80">uv run fastapi dev api/main.py</code>.
            </Slot>
          )}

          {phase === "failed" && (
            <Slot key="failed" className="text-rose-400">
              <p className="text-lg font-semibold">FAILED</p>
              <p className="text-sm text-white/50">
                No provenance recovered. This asset is not in the registry.
              </p>
            </Slot>
          )}

          {phase === "verified" && (
            <Slot key="verified" className="text-emerald-300">
              <p className="text-lg font-semibold">VERIFIED</p>
              <dl className="mt-2 grid gap-1 font-mono text-xs text-white/70">
                <Row k="manifest" v={manifestId ?? "…"} />
                {score != null && <Row k="similarity" v={`${score}/100 (fingerprint)`} />}
                {manifest.data && (
                  <>
                    <Row k="created" v={manifest.data.createdAt} />
                    <Row
                      k="system"
                      v={JSON.stringify(manifest.data.systemProvenance)}
                    />
                    {manifest.data.softBindings?.map((b) => (
                      <Row key={b.alg} k={b.alg} v={b.value} />
                    ))}
                  </>
                )}
              </dl>
              <p className="mt-2 text-xs text-white/55">Provenance proves origin, not truth.</p>
            </Slot>
          )}
        </AnimatePresence>
      </div>
    </section>
  );
}

export function Slot({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.25 }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

export function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-3">
      <dt className="w-24 shrink-0 text-white/55">{k}</dt>
      <dd className="break-all text-white/80">{v}</dd>
    </div>
  );
}
