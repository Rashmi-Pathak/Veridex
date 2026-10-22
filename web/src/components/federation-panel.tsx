"use client";

import { useEffect, useState } from "react";

// Federation. Recovery as an open, vendor-neutral network: on a local miss this resolver forwards the
// soft-binding query to peer SBR nodes (an operator allowlist, SSRF-guarded), and returns the first
// peer's recovered manifest labeled with its endpoint. Reads /api/demo/federation. A live cross-node
// hit needs a second node with a complementary index; the forwarding itself is wired and tested.
type Federation = {
  enabled: boolean;
  peers: string[];
  note: string;
};

export function FederationPanel() {
  const [info, setInfo] = useState<Federation | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/federation")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: Federation) => setInfo(d))
      .catch(() => setError(true));
  }, []);

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">Federation</h2>
      <p className="mb-4 text-[11px] text-white/55">
        Recovery as an open, vendor-neutral network. On a local miss the resolver forwards the
        soft-binding query to peer SBR nodes and returns the first peer to recover the manifest,
        labeled with its endpoint. No peer ever sees the asset, only the binding.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !info && <p className="font-mono text-sm text-white/50">Reading peers…</p>}

      {info && (
        <>
          <div className="flex items-center gap-2 font-mono text-sm">
            {info.enabled ? (
              <span className="rounded bg-emerald-400/10 px-2 py-0.5 text-emerald-300">
                {info.peers.length} peer{info.peers.length === 1 ? "" : "s"} configured
              </span>
            ) : (
              <span className="rounded bg-white/10 px-2 py-0.5 text-white/60">no peers</span>
            )}
          </div>

          {info.peers.length > 0 && (
            <ul className="mt-3 grid gap-1 font-mono text-xs text-white/70">
              {info.peers.map((p) => (
                <li key={p} className="break-all">
                  {p}/matches/byBinding
                </li>
              ))}
            </ul>
          )}

          <p className="mt-3 text-[11px] text-white/55">{info.note}</p>
        </>
      )}
    </section>
  );
}
