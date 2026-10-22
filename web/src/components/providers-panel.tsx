"use client";

import { useEffect, useState } from "react";

import { $api } from "@/lib/api/client";

// Vendor-neutral proof: Veridex recovers provenance for AI media from MULTIPLE real generators
// (Google Nano Banana, Black Forest Labs Flux, Alibaba Qwen) through the same pipeline. Each tile
// holds a real generated image, re-encodes it in-browser (the canvas JPEG re-encode the generate and
// recover panels use, the way a screenshot or re-upload would), then recovers it by perceptual
// fingerprint via the typed SBR client and shows the recovered model and provider. Every visible
// state is driven by a real fetch result.

type ProviderInfo = {
  slug: string;
  label: string;
  model: string;
  provider: string;
  prompt: string;
  manifestId: string;
};

// The strip: draw the image onto a canvas and re-export it as a fresh JPEG. A re-encode like this is
// exactly what a screenshot or a re-upload does, it destroys any embedded credential while the PDQ
// perceptual fingerprint survives. jsdom (the test environment) has no real 2D canvas (getContext
// returns null) and no URL.createObjectURL, so we check for a real canvas first and fall back to the
// original bytes; the recovery loop still closes deterministically because the fingerprint survives.
async function stripBlob(input: Blob): Promise<Blob> {
  let canvas: HTMLCanvasElement | null = null;
  let ctx: CanvasRenderingContext2D | null = null;
  try {
    canvas = document.createElement("canvas");
    ctx = canvas.getContext("2d");
  } catch {
    ctx = null;
  }
  if (!canvas || !ctx || typeof canvas.toBlob !== "function") return input;

  let url: string | null = null;
  try {
    url = URL.createObjectURL(input);
    const objectUrl = url;
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("image decode failed"));
      el.src = objectUrl;
    });
    canvas.width = img.naturalWidth || img.width || 1;
    canvas.height = img.naturalHeight || img.height || 1;
    ctx.drawImage(img, 0, 0);
    const reencoded = await new Promise<Blob | null>((resolve) => {
      canvas!.toBlob((b) => resolve(b), "image/jpeg", 0.9);
    });
    return reencoded ?? input;
  } catch {
    return input;
  } finally {
    if (url) URL.revokeObjectURL(url);
  }
}

function ProviderTile({ info }: { info: ProviderInfo }) {
  const [requestError, setRequestError] = useState(false);

  const recover = $api.useMutation("post", "/matches/byContent");
  // Derive the match (and its score + manifest id) straight from the mutation result, so the score
  // renders in the SAME tick as the VERIFIED state. A separate setState in onSuccess could lag a
  // render behind recover.isSuccess (VERIFIED shown, score briefly null), which is a flaky-test trap.
  const match = recover.isSuccess ? recover.data.matches?.[0] : undefined;
  const recoveredId = match?.manifestId ?? null;
  const score = match?.similarityScore ?? null;
  const manifest = $api.useQuery(
    "get",
    "/manifests/{manifest_id}",
    { params: { path: { manifest_id: recoveredId ?? "" } } },
    { enabled: recoveredId != null },
  );

  async function recoverProvider() {
    if (recover.isPending) return;
    setRequestError(false);
    try {
      const res = await fetch(`/api/demo/provider/${info.slug}`);
      if (!res.ok) {
        setRequestError(true);
        return;
      }
      const stripped = await stripBlob(await res.blob());
      recover.mutate(
        {
          // The schema types the multipart `file` field as string; we send the real Blob and let the
          // FormData serializer carry it (when bodySerializer returns FormData, fetch sets the boundary).
          body: { file: stripped as unknown as string },
          bodySerializer: (b) => {
            const fd = new FormData();
            fd.append("file", b.file as unknown as Blob, "stripped.jpg");
            return fd;
          },
        },
        { onError: () => setRequestError(true) },
      );
    } catch {
      setRequestError(true);
    }
  }

  const matched = !!match;
  const noMatch = recover.isSuccess && (recover.data.matches?.length ?? 0) === 0;
  const recoveredModel =
    typeof manifest.data?.systemProvenance?.model === "string"
      ? manifest.data.systemProvenance.model
      : null;
  const recoveredProvider =
    typeof manifest.data?.systemProvenance?.provider === "string"
      ? manifest.data.systemProvenance.provider
      : null;

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-white/10 bg-black/30 p-4">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`/api/demo/provider/${info.slug}`}
        alt={`${info.label} generated image`}
        className="aspect-square w-full rounded border border-white/10 object-cover"
      />

      <div className="font-mono text-xs text-white/70">
        <p className="text-sm font-semibold text-white/90">{info.label}</p>
        <p className="mt-1 break-all text-white/50">{info.model}</p>
        <p className="break-all text-white/55">{info.provider}</p>
      </div>

      <button
        type="button"
        onClick={recoverProvider}
        disabled={recover.isPending}
        className="rounded border border-white/20 px-3 py-1.5 font-mono text-xs text-white/80 transition hover:border-white/40 hover:bg-white/[0.03] disabled:cursor-not-allowed disabled:opacity-40"
      >
        {recover.isPending ? "Recovering…" : "Recover"}
      </button>

      {requestError && (
        <p className="font-mono text-xs text-amber-400">
          Recovery request failed. The backend may be unreachable.
        </p>
      )}

      {!requestError && noMatch && (
        <p className="font-mono text-xs text-white/50">
          No provenance recovered for this asset.
        </p>
      )}

      {!requestError && matched && (
        <div className="font-mono text-xs text-emerald-300">
          <p className="text-sm font-semibold">VERIFIED</p>
          <dl className="mt-1 grid gap-0.5 text-white/70">
            {score != null && (
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-white/55">similarity</dt>
                <dd className="text-white/80">{score}/100</dd>
              </div>
            )}
            {recoveredModel && (
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-white/55">model</dt>
                <dd className="break-all text-white/80">{recoveredModel}</dd>
              </div>
            )}
            {recoveredProvider && (
              <div className="flex gap-2">
                <dt className="w-20 shrink-0 text-white/55">provider</dt>
                <dd className="break-all text-white/80">{recoveredProvider}</dd>
              </div>
            )}
          </dl>
        </div>
      )}
    </div>
  );
}

export function ProvidersPanel() {
  const [providers, setProviders] = useState<ProviderInfo[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/providers")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: ProviderInfo[]) => setProviders(d))
      .catch(() => setError(true));
  }, []);

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">Vendor-neutral</h2>
      <p className="mb-4 text-[11px] text-white/55">
        Recover provenance for AI media from any generator. Each image below is from a different real
        model (Google Nano Banana, Black Forest Labs Flux, Alibaba Qwen). Strip one and Veridex recovers
        it through the same pipeline.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !providers && (
        <p className="font-mono text-sm text-white/50">Loading generators…</p>
      )}
      {!error && providers && providers.length === 0 && (
        <p className="font-mono text-sm text-white/50">No generators available.</p>
      )}

      {!error && providers && providers.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {providers.map((info) => (
            <ProviderTile key={info.slug} info={info} />
          ))}
        </div>
      )}
    </section>
  );
}
