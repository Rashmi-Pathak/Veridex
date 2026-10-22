"use client";

import { useRef, useState, type DragEvent } from "react";
import { AnimatePresence } from "motion/react";

import { $api } from "@/lib/api/client";
import { Row, Slot } from "@/components/recover-panel";

// The video modality of the recovery loop. A real AI-generated clip (Veo3 via kie.ai) is served at
// /api/demo/video. The visitor plays it, then re-encodes it in any tool and drops it back; Veridex
// recovers its provenance by matching per-keyframe fingerprints to a green VERIFIED state. A re-encode
// drops any embedded credential while the keyframe fingerprints survive, so no embedded credential is
// needed. Every visible state is driven by a real fetch result (the demo bytes, the
// /matches/byVideoContent result, and the recovered manifest query), never by a cosmetic timer.
// /matches/byVideoContent is not in the typed schema, so it is a raw fetch; the recovered manifest GET
// is in the schema, so it goes through the typed client.

type RecoverState =
  | { kind: "intro" }
  | { kind: "recovering" }
  | { kind: "recovered"; manifestId: string; score: number | null }
  | { kind: "failed" }
  | { kind: "error"; detail: string };

type VideoMatchResponse = {
  matches?: { manifestId: string; similarityScore?: number | null }[];
};

export function VideoPanel() {
  const [state, setState] = useState<RecoverState>({ kind: "intro" });
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const manifestId = state.kind === "recovered" ? state.manifestId : null;
  const manifest = $api.useQuery(
    "get",
    "/manifests/{manifest_id}",
    { params: { path: { manifest_id: manifestId ?? "" } } },
    { enabled: manifestId != null },
  );

  // The single upload path. Whatever video bytes it is handed (a dropped file, a selected file, or the
  // fetched demo blob) are posted to /matches/byVideoContent and the result drives the state machine.
  async function recover(blob: Blob, name: string) {
    setFileName(name);
    setState({ kind: "recovering" });
    try {
      const fd = new FormData();
      fd.append("file", blob, name);
      const res = await fetch("/api/matches/byVideoContent", { method: "POST", body: fd });
      if (!res.ok) {
        const detail = await res
          .json()
          .then((d: { detail?: string }) => d.detail)
          .catch(() => null);
        setState({ kind: "error", detail: detail ?? `Recovery failed (HTTP ${res.status}).` });
        return;
      }

      const data: VideoMatchResponse = await res.json();
      const match = data.matches?.[0];
      if (match) {
        setState({ kind: "recovered", manifestId: match.manifestId, score: match.similarityScore ?? null });
      } else {
        setState({ kind: "failed" });
      }
    } catch {
      setState({
        kind: "error",
        detail: "Backend unreachable. Start it with uv run fastapi dev api/main.py.",
      });
    }
  }

  async function recoverDemoClip() {
    setState({ kind: "recovering" });
    try {
      const clipRes = await fetch("/api/demo/video");
      if (!clipRes.ok) {
        setState({ kind: "error", detail: `Could not load the demo clip (HTTP ${clipRes.status}).` });
        return;
      }
      const bytes = await clipRes.arrayBuffer();
      const blob = new Blob([bytes], { type: "video/mp4" });
      await recover(blob, "demo.mp4");
    } catch {
      setState({
        kind: "error",
        detail: "Backend unreachable. Start it with uv run fastapi dev api/main.py.",
      });
    }
  }

  function onDrop(e: DragEvent<HTMLButtonElement>) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) void recover(file, file.name);
  }

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.04] p-6 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">Video provenance</h2>
      <p className="mb-4 text-[11px] text-white/55">
        A real AI-generated video (Veo3 via kie.ai). Re-encode it in any tool and drop it below:
        Veridex recovers it by matching its keyframe fingerprints. No embedded credential needed.
      </p>

      <video
        controls
        preload="none"
        src="/api/demo/video"
        className="aspect-video w-full rounded-lg"
      >
        Your browser cannot play the demo clip.
      </video>

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDrop={onDrop}
        onDragOver={(e) => e.preventDefault()}
        disabled={state.kind === "recovering"}
        className="mt-4 flex w-full flex-col items-center gap-2 rounded-lg border border-dashed border-white/20 px-6 py-8 text-center transition hover:border-white/40 hover:bg-white/[0.03] disabled:cursor-not-allowed disabled:opacity-40"
      >
        <span className="text-sm text-white/70">Drop a video file, or click to select</span>
        <span className="font-mono text-xs text-white/55">
          {fileName ?? "we match its keyframe fingerprints against the registry"}
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="video/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void recover(file, file.name);
        }}
      />

      <div className="mt-3 text-center">
        <button
          type="button"
          onClick={() => void recoverDemoClip()}
          disabled={state.kind === "recovering"}
          className="font-mono text-xs text-sky-300/80 underline-offset-4 transition hover:underline disabled:cursor-not-allowed disabled:opacity-40"
        >
          or recover the demo clip
        </button>
      </div>

      <div className="mt-5 min-h-24">
        <AnimatePresence mode="wait">
          {state.kind === "intro" && (
            <Slot key="intro" className="text-white/55">
              Drop a re-encoded clip, or recover the demo clip.
            </Slot>
          )}

          {state.kind === "recovering" && (
            <Slot key="recovering" className="text-sky-300">
              <span className="inline-flex items-center gap-2">
                <span className="h-2 w-2 animate-ping rounded-full bg-sky-300" />
                Matching keyframe fingerprints…
              </span>
            </Slot>
          )}

          {state.kind === "error" && (
            <Slot key="error" className="text-amber-400">
              <p className="text-sm">{state.detail}</p>
            </Slot>
          )}

          {state.kind === "failed" && (
            <Slot key="failed" className="text-rose-400">
              <p className="text-lg font-semibold">FAILED</p>
              <p className="text-sm text-white/50">No provenance recovered for this video.</p>
            </Slot>
          )}

          {state.kind === "recovered" && (
            <Slot key="recovered" className="text-emerald-300">
              <p className="text-lg font-semibold">VERIFIED</p>
              <dl className="mt-2 grid gap-1 font-mono text-xs text-white/70">
                <Row k="manifest" v={state.manifestId} />
                {state.score != null && (
                  <Row k="similarity" v={`${state.score}/100 (keyframe fingerprint)`} />
                )}
                {manifest.data && (
                  <>
                    <Row k="created" v={manifest.data.createdAt} />
                    <Row k="system" v={JSON.stringify(manifest.data.systemProvenance)} />
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
