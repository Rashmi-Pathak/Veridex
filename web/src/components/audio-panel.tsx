"use client";

import { useState } from "react";
import { AnimatePresence } from "motion/react";

import { $api } from "@/lib/api/client";
import { Row, Slot } from "@/components/recover-panel";

// The audio modality of the recovery loop. A real AI-generated music clip (Suno via kie.ai) is served
// at /api/demo/audio. The visitor plays it, then STRIPS it (an in-browser re-encode to WAV that drops
// any embedded credential while the perceptual fingerprint survives) and RECOVERS its provenance by
// audio fingerprint to a green VERIFIED state. Every visible state is driven by a real fetch result
// (the demo bytes, the /matches/byAudioContent result, and the recovered manifest query), never by a
// cosmetic timer. /matches/byAudioContent is not in the typed schema, so it is a raw fetch; the
// recovered manifest GET is in the schema, so it goes through the typed client.

type RecoverState =
  | { kind: "intro" }
  | { kind: "recovering" }
  | { kind: "recovered"; manifestId: string; score: number | null }
  | { kind: "failed" }
  | { kind: "error"; detail: string };

// Render decoded PCM channels to a 16-bit little-endian WAV Blob (a standard 44-byte header followed
// by interleaved samples). A re-encode like this is a real container change: it strips any embedded
// metadata while the perceptual audio fingerprint survives. Pure and small, so it is easy to reason
// about and the output is deterministic for a given input.
function encodeWav(channels: Float32Array[], sampleRate: number): Blob {
  const numChannels = Math.max(1, channels.length);
  const numFrames = channels[0]?.length ?? 0;
  const bytesPerSample = 2;
  const blockAlign = numChannels * bytesPerSample;
  const dataSize = numFrames * blockAlign;

  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  const writeString = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i += 1) view.setUint8(offset + i, s.charCodeAt(i));
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true); // PCM fmt chunk size
  view.setUint16(20, 1, true); // audio format: 1 = PCM
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true); // byte rate
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 8 * bytesPerSample, true); // bits per sample
  writeString(36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;
  for (let frame = 0; frame < numFrames; frame += 1) {
    for (let ch = 0; ch < numChannels; ch += 1) {
      const sample = Math.max(-1, Math.min(1, channels[ch]?.[frame] ?? 0));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      offset += 2;
    }
  }

  return new Blob([buffer], { type: "audio/wav" });
}

// The strip: decode the fetched clip with the Web Audio API and re-encode the PCM to WAV. jsdom (the
// test environment) has no real AudioContext, and a real decodeAudioData can throw on a clip it cannot
// parse, so on either condition we fall back to uploading the original fetched bytes. The recovery
// loop still closes deterministically because the backend fingerprints whatever bytes it receives.
async function stripAudio(bytes: ArrayBuffer): Promise<Blob> {
  const w = window as unknown as {
    AudioContext?: typeof AudioContext;
    webkitAudioContext?: typeof AudioContext;
  };
  const AudioCtor = w.AudioContext ?? w.webkitAudioContext;
  const original = new Blob([bytes], { type: "audio/mpeg" });
  if (!AudioCtor) return original;

  try {
    const ctx = new AudioCtor();
    // decodeAudioData detaches its input buffer, so hand it a copy and keep `bytes` for the fallback.
    const decoded = await ctx.decodeAudioData(bytes.slice(0));
    const channels: Float32Array[] = [];
    for (let c = 0; c < decoded.numberOfChannels; c += 1) {
      channels.push(decoded.getChannelData(c));
    }
    return encodeWav(channels, decoded.sampleRate);
  } catch {
    return original;
  }
}

type AudioMatchResponse = {
  matches?: { manifestId: string; similarityScore?: number | null }[];
};

export function AudioPanel() {
  const [state, setState] = useState<RecoverState>({ kind: "intro" });

  const manifestId = state.kind === "recovered" ? state.manifestId : null;
  const manifest = $api.useQuery(
    "get",
    "/manifests/{manifest_id}",
    { params: { path: { manifest_id: manifestId ?? "" } } },
    { enabled: manifestId != null },
  );

  async function stripAndRecover() {
    setState({ kind: "recovering" });
    try {
      const clipRes = await fetch("/api/demo/audio");
      if (!clipRes.ok) {
        setState({ kind: "error", detail: `Could not load the demo clip (HTTP ${clipRes.status}).` });
        return;
      }
      const bytes = await clipRes.arrayBuffer();
      const stripped = await stripAudio(bytes);

      const fd = new FormData();
      fd.append("file", stripped, "stripped.wav");
      const res = await fetch("/api/matches/byAudioContent", { method: "POST", body: fd });
      if (!res.ok) {
        const detail = await res
          .json()
          .then((d: { detail?: string }) => d.detail)
          .catch(() => null);
        setState({ kind: "error", detail: detail ?? `Recovery failed (HTTP ${res.status}).` });
        return;
      }

      const data: AudioMatchResponse = await res.json();
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

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.04] p-6 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">Audio provenance</h2>
      <p className="mb-4 text-[11px] text-white/55">
        A real AI-generated music clip (Suno via kie.ai). Play it, then strip it (a re-encode that
        removes any embedded credential) and watch Veridex recover its provenance by audio fingerprint.
      </p>

      <audio controls preload="none" src="/api/demo/audio" className="w-full">
        Your browser cannot play the demo clip.
      </audio>

      <button
        type="button"
        onClick={() => void stripAndRecover()}
        disabled={state.kind === "recovering"}
        className="mt-4 rounded border border-white/20 px-4 py-2 font-mono text-xs text-white/80 transition hover:border-white/40 hover:bg-white/[0.03] disabled:cursor-not-allowed disabled:opacity-40"
      >
        {state.kind === "recovering" ? "Recovering…" : "Strip and recover"}
      </button>

      <div className="mt-5 min-h-24">
        <AnimatePresence mode="wait">
          {state.kind === "intro" && (
            <Slot key="intro" className="text-white/55">
              Play the clip, then strip and recover its provenance.
            </Slot>
          )}

          {state.kind === "recovering" && (
            <Slot key="recovering" className="text-sky-300">
              <span className="inline-flex items-center gap-2">
                <span className="h-2 w-2 animate-ping rounded-full bg-sky-300" />
                Stripped. Matching the audio fingerprint…
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
              <p className="text-sm text-white/50">
                No provenance recovered. This clip is not in the registry.
              </p>
            </Slot>
          )}

          {state.kind === "recovered" && (
            <Slot key="recovered" className="text-emerald-300">
              <p className="text-lg font-semibold">VERIFIED</p>
              <dl className="mt-2 grid gap-1 font-mono text-xs text-white/70">
                <Row k="manifest" v={state.manifestId} />
                {state.score != null && (
                  <Row k="similarity" v={`${state.score}/100 (audio fingerprint)`} />
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
