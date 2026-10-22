"use client";

import { useEffect, useState } from "react";

// A compact live-metrics ribbon under the hero: the system's strongest proof (the recovery self-test
// and the transparency tree) made visible at first glance instead of buried in a panel far down the
// page. Reads /api/status (the same authoritative surface the Status panel uses). Degrades quietly
// to "status connecting" if the API is unreachable, so the hero never shows a broken state.
type Status = {
  transparency: { treeSize: number; checkpointEpoch: number };
  storage: { backend: string };
  recoveryIndex: string;
  recoverySelfTest: { recovered: boolean; similarityScore: number | null; latencyMs: number };
  generation: { enabled: boolean };
};

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className="text-white/35">{label}</span>
      <span className={accent ? "text-emerald-300" : "text-white/75"}>{value}</span>
    </span>
  );
}

export function MetricsRibbon() {
  const [s, setS] = useState<Status | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/status")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: Status) => setS(d))
      .catch(() => setError(true));
  }, []);

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-xs text-white/55">
      <span className="inline-flex items-center gap-1.5">
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
        </span>
        <span className="uppercase tracking-[0.2em] text-emerald-300/90">live</span>
      </span>

      {error && <span className="text-white/40">status connecting</span>}

      {s && (
        <>
          <Stat
            label="log"
            value={`${s.transparency.treeSize} leaves · epoch ${s.transparency.checkpointEpoch}`}
          />
          <Stat
            label="recovery"
            accent={s.recoverySelfTest.recovered}
            value={
              s.recoverySelfTest.recovered
                ? `${s.recoverySelfTest.latencyMs}ms · ${s.recoverySelfTest.similarityScore ?? "-"}/100`
                : "self-test failing"
            }
          />
          <Stat
            label="storage"
            value={s.storage.backend === "backblaze-b2" ? "Backblaze B2" : s.storage.backend}
          />
          <Stat label="index" value={s.recoveryIndex} />
          <Stat label="generation" value={s.generation.enabled ? "on" : "seed only"} />
        </>
      )}
    </div>
  );
}
