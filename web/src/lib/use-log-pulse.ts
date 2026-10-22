"use client";

import { useEffect, useRef, useState } from "react";

// Watches the live transparency-log tree size and opens a short pulse window when the tree really
// grows between two live responses. The first observed size is only the baseline and never pulses,
// so a fresh page load does not present existing leaves as new. Anything else (an equal size, or a
// smaller one, which an append-only log should never produce) moves the baseline without pulsing.
// The range derives entirely from the live responses; nothing is simulated.
export type LogPulse = {
  // The half-open range [from, to) of new leaf indices: from is the previous live tree size and
  // to is the grown one, so the leaves numbered from..to-1 are the ones that just arrived.
  from: number;
  to: number;
};

const PULSE_MS = 8_000;

export function useLogPulse(
  treeSize: number | undefined,
  pulseMs: number = PULSE_MS,
): LogPulse | null {
  const [pulse, setPulse] = useState<LogPulse | null>(null);
  const prev = useRef<number | null>(null);

  useEffect(() => {
    if (treeSize == null) return;
    const last = prev.current;
    prev.current = treeSize;
    if (last != null && treeSize > last) setPulse({ from: last, to: treeSize });
  }, [treeSize]);

  useEffect(() => {
    if (pulse == null) return;
    const timer = setTimeout(() => setPulse(null), pulseMs);
    return () => clearTimeout(timer);
  }, [pulse, pulseMs]);

  return pulse;
}
