"use client";

import { useEffect, useState } from "react";

// A live, judge-facing status panel. /api/status reports the running service's real, measured state:
// the transparency tree, the storage backend, the advertised algorithms, the live-generation config,
// and a recovery self-test that recovers the seeded asset right now. Every value is measured at
// request time, so this panel is a real production signal, not a static claim.
type Status = {
  service: string;
  transparency: {
    treeSize: number;
    rootHash: string;
    checkpointEpoch: number;
    keySource: string;
    publicKeyHex: string;
  };
  storage: { backend: string; bucket: string | null; demoAssetPresent: boolean };
  recoveryIndex: string;
  algorithms: { watermarks: string[]; fingerprints: string[] };
  generation: {
    enabled: boolean;
    configured: boolean;
    perIpPerDay: number;
    globalPerDay: number;
    maxInFlight: number;
  };
  recoverySelfTest: {
    recovered: boolean;
    manifestId: string | null;
    similarityScore: number | null;
    latencyMs: number;
  };
};

export function StatusPanel() {
  const [s, setS] = useState<Status | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/status")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: Status) => setS(d))
      .catch(() => setError(true));
  }, []);

  const storageLabel = !s
    ? ""
    : s.storage.backend === "backblaze-b2"
      ? `Backblaze B2${s.storage.bucket ? ` (${s.storage.bucket})` : ""}`
      : s.storage.backend;

  const indexLabel = !s
    ? ""
    : s.recoveryIndex === "postgres+hnsw"
      ? "Postgres + HNSW (bit_hamming_ops)"
      : s.recoveryIndex === "postgres+bitcount"
        ? "Postgres (bit_count)"
        : "in-memory";

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-3 text-xs uppercase tracking-widest text-white/50">Live status</h2>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !s && <p className="font-mono text-sm text-white/50">Reading live status…</p>}

      {s && (
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <p className="mb-1 text-[11px] uppercase tracking-widest text-white/55">
              recovery self-test
            </p>
            {s.recoverySelfTest.recovered ? (
              <p className="font-mono text-sm text-emerald-300">
                ✓ recovered the seed in {s.recoverySelfTest.latencyMs} ms
                {s.recoverySelfTest.similarityScore != null
                  ? ` · ${s.recoverySelfTest.similarityScore}/100`
                  : ""}
              </p>
            ) : (
              <p className="font-mono text-sm text-amber-400">not recovered</p>
            )}
          </div>
          <Item
            label="transparency tree"
            value={`${s.transparency.treeSize} leaves · epoch ${s.transparency.checkpointEpoch}`}
          />
          <Item label="checkpoint key" value={s.transparency.keySource} />
          <Item label="storage" value={storageLabel} />
          <Item label="recovery index" value={indexLabel} />
          <Item label="algorithms" value={s.algorithms.watermarks.join(", ") || "none"} />
          <Item
            label="live generation"
            value={
              s.generation.enabled && s.generation.configured
                ? `on · ${s.generation.perIpPerDay}/IP, ${s.generation.globalPerDay}/day`
                : "seed only"
            }
          />
        </div>
      )}
    </section>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="mb-1 text-[11px] uppercase tracking-widest text-white/55">{label}</p>
      <p className="break-all font-mono text-sm text-white/75">{value}</p>
    </div>
  );
}
