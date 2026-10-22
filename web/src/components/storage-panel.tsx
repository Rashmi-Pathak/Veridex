"use client";

import { useEffect, useState } from "react";

// Shows where the demo asset is stored. /api/demo/storage confirms each object is present with a real
// read against the backend (Backblaze B2 when the deploy has B2 credentials, in-memory otherwise), so
// this panel honestly reflects whether the live demo is exercising B2.
type StorageInfo = {
  backend: string;
  bucket: string | null;
  keys: Record<string, string>;
  present: Record<string, boolean>;
};

const LABELS: Record<string, string> = {
  asset: "asset",
  manifest: "manifest",
  signature: "signature",
};

export function StoragePanel() {
  const [info, setInfo] = useState<StorageInfo | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/storage")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: StorageInfo) => setInfo(d))
      .catch(() => setError(true));
  }, []);

  const onB2 = info?.backend === "backblaze-b2";

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-3 text-xs uppercase tracking-widest text-white/50">
        Backblaze B2 storage
      </h2>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !info && <p className="font-mono text-sm text-white/50">Checking storage…</p>}

      {info && (
        <>
          <p className="font-mono text-sm">
            {onB2 ? (
              <span className="text-emerald-300">
                Stored content-addressably on Backblaze B2
                {info.bucket ? ` (bucket ${info.bucket})` : ""}
              </span>
            ) : (
              <span className="text-white/60">
                In-memory demo. Set the B2 credentials on the deploy to store on Backblaze B2.
              </span>
            )}
          </p>
          <ul className="mt-3 space-y-1 font-mono text-xs">
            {Object.keys(info.keys).map((name) => (
              <li key={name} className="flex gap-2">
                <span className={info.present[name] ? "text-emerald-300" : "text-white/50"}>
                  {info.present[name] ? "✓" : "·"}
                </span>
                <span className="w-20 shrink-0 text-white/55">{LABELS[name] ?? name}</span>
                <span className="break-all text-white/70">{info.keys[name]}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
