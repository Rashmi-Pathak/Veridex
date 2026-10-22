"use client";

import dynamic from "next/dynamic";

import { usePrefersReducedMotion } from "@/lib/use-reduced-motion-pref";

// The galaxy WebGL backdrop is deferred two ways from this client boundary:
//  1. dynamic(ssr:false) so the ~876KB of three.js + r3f + drei never blocks first paint or
//     hydration. The backdrop is a fixed -z-10 aria-hidden decoration, so a slightly later mount is
//     invisible and the DOM UI (the load-bearing recovery loop) is unaffected.
//  2. under prefers-reduced-motion we never import three.js at all; the CSS atmosphere below is the
//     whole backdrop there, so a reduced-motion or low-power device pays no GL or per-frame cost.
const Scene = dynamic(() => import("./scene").then((m) => m.Scene), { ssr: false });

// The always-on CSS atmosphere bed, layered under the canvas (and server-rendered, so the very
// first paint already has depth instead of a flat black wall while three.js loads). Top to bottom:
// an edge vignette, the emerald zenith glare (the brand's VERIFIED green as weather), a warm hint
// where the galactic core sits, a deep-teal ground band, and a green-tinted near-black base. The
// same palette the WebGL layers use, so the canvas fading in reads as the sky waking up, not a
// scene swap.
const ATMOSPHERE_BED = [
  "radial-gradient(130% 95% at 50% 45%, transparent 58%, rgba(2, 8, 9, 0.6) 100%)",
  "radial-gradient(95% 55% at 50% -12%, rgba(52, 211, 153, 0.13), rgba(52, 211, 153, 0.04) 46%, transparent 70%)",
  "radial-gradient(55% 42% at 50% 40%, rgba(255, 168, 86, 0.08), rgba(78, 120, 200, 0.05) 52%, transparent 72%)",
  "linear-gradient(to top, rgba(3, 17, 15, 0.92), rgba(4, 24, 25, 0.4) 16%, transparent 32%)",
  "linear-gradient(#060a09, #05070a)",
].join(", ");

export function SceneBackdrop() {
  const reduced = usePrefersReducedMotion();
  return (
    <>
      <div
        className="pointer-events-none fixed inset-0 -z-20"
        aria-hidden="true"
        style={{ background: ATMOSPHERE_BED }}
      />
      {!reduced && <Scene />}
    </>
  );
}
