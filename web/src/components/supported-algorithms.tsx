"use client";

import { $api } from "@/lib/api/client";

// Foundation proof: a real typed call against the SBR API, with the UI driven entirely by query
// state (pending / error / data). This is the seed of the demo-safe pattern: the recovery result is
// rendered from the typed client, never gated on anything cosmetic.
export function SupportedAlgorithms() {
  const { data, error, isPending } = $api.useQuery("get", "/services/supportedAlgorithms");

  return (
    <section className="rounded-lg border border-white/15 bg-white/[0.03] p-5 font-mono text-sm">
      <h2 className="mb-3 text-xs uppercase tracking-widest text-white/50">
        SBR API · supported algorithms
      </h2>

      {isPending && <p className="text-white/60">Querying the resolver…</p>}

      {error != null && (
        <p className="text-amber-400">
          Backend unreachable. Start the API with{" "}
          <code className="text-white/80">uv run fastapi dev api/main.py</code>.
        </p>
      )}

      {data && (
        <div className="grid gap-4 sm:grid-cols-2">
          <AlgList label="Watermarks" entries={data.watermarks ?? []} />
          <AlgList label="Fingerprints" entries={data.fingerprints ?? []} />
        </div>
      )}
    </section>
  );
}

function AlgList({ label, entries }: { label: string; entries: { alg: string }[] }) {
  return (
    <div>
      <p className="mb-1 text-white/55">{label}</p>
      <ul className="space-y-1">
        {entries.length === 0 && <li className="text-white/50">none</li>}
        {entries.map((e) => (
          <li key={e.alg} className="text-emerald-300">
            {e.alg}
          </li>
        ))}
      </ul>
    </div>
  );
}
