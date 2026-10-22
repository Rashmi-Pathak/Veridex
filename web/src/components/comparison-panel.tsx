"use client";

import { useRef, useState, type DragEvent } from "react";
import { AnimatePresence } from "motion/react";

import { $api } from "@/lib/api/client";
import { Row, Slot } from "@/components/recover-panel";

// Same stripped bytes, two engines. The OFFICIAL C2PA reader (@contentauth/c2pa-web, the maintained
// CAI data SDK that powers contentcredentials.org) finds no embedded manifest on a stripped asset,
// while Veridex recovers the full signed manifest from its Backblaze B2 registry by perceptual-hash
// fingerprint. The contrast is the point: stripping the embedded credential does not destroy
// provenance once a soft-binding resolver exists. Both run on the identical bytes, in the browser,
// so the comparison is real (not a screenshot, not a scrape of the hosted site).

type Official =
  | { state: "idle" | "reading" | "none" }
  | { state: "found"; summary: string }
  | { state: "error"; summary: string };

async function readOfficial(blob: Blob, mime: string): Promise<Official> {
  // Dynamic import so the worker/WASM only run client-side, never during SSR (same as the Content
  // Credentials panel). A falsy reader means the SDK found no embedded C2PA manifest in the bytes.
  const { createC2pa } = await import("@contentauth/c2pa-web/inline");
  const c2pa = await createC2pa();
  const reader = await c2pa.reader.fromBlob(mime || "image/jpeg", blob);
  if (!reader) return { state: "none" };
  try {
    const store = await reader.json();
    const active = store?.manifests?.[store?.active_manifest] ?? {};
    return { state: "found", summary: active?.claim_generator ?? "embedded manifest present" };
  } finally {
    await reader.free(); // WASM heap is not GC'd; always free.
  }
}

type Phase = "idle" | "scanning" | "verified" | "failed" | "error";

export function ComparisonPanel() {
  const [fileName, setFileName] = useState<string | null>(null);
  const [manifestId, setManifestId] = useState<string | null>(null);
  const [score, setScore] = useState<number | null>(null);
  const [official, setOfficial] = useState<Official>({ state: "idle" });
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
    setOfficial({ state: "reading" });
    readOfficial(file, file.type)
      .then(setOfficial)
      .catch((e) =>
        setOfficial({ state: "error", summary: e instanceof Error ? e.message : "read failed" }),
      );
    recover.mutate(
      {
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

  async function tryStrippedSample() {
    // The bundled AI image (Genblaze on GMI Cloud) carries no embedded C2PA manifest, so the official
    // reader finds nothing; Veridex recovers it by fingerprint. The same bytes go to both engines.
    const res = await fetch("/api/demo/sample");
    const blob = await res.blob();
    submit(new File([blob], "stripped-sample.jpg", { type: blob.type || "image/jpeg" }));
  }

  function onDrop(e: DragEvent<HTMLButtonElement>) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) submit(file);
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
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">Same bytes, two readers</h2>
      <p className="mb-4 text-[11px] text-white/55">
        The official C2PA reader (the @contentauth/c2pa-web engine behind contentcredentials.org) and
        Veridex, run on the identical stripped image in your browser. The official tool finds no
        embedded credential; Veridex recovers the signed manifest from its Backblaze B2 registry.
      </p>

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDrop={onDrop}
        onDragOver={(e) => e.preventDefault()}
        className="flex w-full flex-col items-center gap-2 rounded-lg border border-dashed border-white/20 px-6 py-6 text-center transition hover:border-white/40 hover:bg-white/[0.03]"
      >
        <span className="text-sm text-white/70">Drop a stripped image, or click to select</span>
        <span className="font-mono text-xs text-white/55">
          {fileName ?? "the same bytes go to both readers"}
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
          onClick={tryStrippedSample}
          className="font-mono text-xs text-sky-300/80 underline-offset-4 hover:underline"
        >
          or compare the stripped demo asset
        </button>
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
          <p className="mb-2 text-[11px] uppercase tracking-widest text-white/45">
            Official C2PA reader
          </p>
          <div className="min-h-20">
            <AnimatePresence mode="wait">
              {official.state === "idle" && (
                <Slot key="o-idle" className="font-mono text-sm text-white/45">
                  Awaiting an asset.
                </Slot>
              )}
              {official.state === "reading" && (
                <Slot key="o-reading" className="font-mono text-sm text-white/50">
                  Reading embedded manifest…
                </Slot>
              )}
              {official.state === "none" && (
                <Slot key="o-none" className="text-rose-400">
                  <p className="text-base font-semibold">No Content Credentials</p>
                  <p className="mt-1 text-xs text-white/50">
                    The embedded manifest is gone. To the official tool, this asset has no provenance.
                  </p>
                </Slot>
              )}
              {official.state === "found" && (
                <Slot key="o-found" className="text-emerald-300">
                  <p className="text-base font-semibold">Embedded manifest found</p>
                  <p className="mt-1 break-all font-mono text-xs text-white/60">{official.summary}</p>
                </Slot>
              )}
              {official.state === "error" && (
                <Slot key="o-error" className="text-amber-400">
                  <p className="font-mono text-sm">Reader error</p>
                  <p className="mt-1 break-all text-xs text-white/50">{official.summary}</p>
                </Slot>
              )}
            </AnimatePresence>
          </div>
        </div>

        <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
          <p className="mb-2 text-[11px] uppercase tracking-widest text-white/45">Veridex recovery</p>
          <div className="min-h-20">
            <AnimatePresence mode="wait">
              {phase === "idle" && (
                <Slot key="r-idle" className="font-mono text-sm text-white/45">
                  Awaiting an asset.
                </Slot>
              )}
              {phase === "scanning" && (
                <Slot key="r-scanning" className="text-sky-300">
                  <span className="inline-flex items-center gap-2">
                    <span className="h-2 w-2 animate-ping rounded-full bg-sky-300" />
                    Matching fingerprint against the registry…
                  </span>
                </Slot>
              )}
              {phase === "error" && (
                <Slot key="r-error" className="text-amber-400">
                  Backend unreachable.
                </Slot>
              )}
              {phase === "failed" && (
                <Slot key="r-failed" className="text-rose-400">
                  <p className="text-base font-semibold">Not in the registry</p>
                  <p className="mt-1 text-xs text-white/50">No provenance recovered for this asset.</p>
                </Slot>
              )}
              {phase === "verified" && (
                <Slot key="r-verified" className="text-emerald-300">
                  <p className="text-base font-semibold">RECOVERED</p>
                  <dl className="mt-2 grid gap-1 font-mono text-xs text-white/70">
                    <Row k="manifest" v={manifestId ?? "…"} />
                    {score != null && <Row k="similarity" v={`${score}/100 (fingerprint)`} />}
                    {manifest.data && (
                      <Row k="system" v={JSON.stringify(manifest.data.systemProvenance)} />
                    )}
                  </dl>
                </Slot>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  );
}
