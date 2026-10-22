"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";

import { $api } from "@/lib/api/client";
import { useInView } from "@/lib/use-in-view";
import { useLogPulse } from "@/lib/use-log-pulse";
import { usePrefersReducedMotion } from "@/lib/use-reduced-motion-pref";
import type { GLink, GNode } from "./merkle-graph";

// Client-only: r3f-forcegraph touches window at import, so it must not be server-rendered.
const MerkleGraph = dynamic(() => import("./merkle-graph"), { ssr: false });

// Poll the live log on a modest interval so the panel reflects new ingestions while the page is
// open. TanStack Query's structural sharing keeps an unchanged response referentially identical,
// so a no-change poll re-renders nothing in the WebGL tree; only a real change reaches the graph.
const POLL_MS = 20_000;

type Entry = { leafIndex: number; manifestId: string; leafHash: string };

// Build the binary Merkle tree shape from the ordered leaves: real leaf hashes at the bottom,
// structural internal nodes pairing upward, and the real signed root at the top.
function buildTree(entries: Entry[], rootHash: string): { nodes: GNode[]; links: GLink[] } {
  const nodes: GNode[] = [];
  const links: GLink[] = [];
  let level = entries.map((e) => {
    const id = `leaf-${e.leafIndex}`;
    nodes.push({ id, kind: "leaf", hash: e.leafHash });
    return id;
  });
  let depth = 0;
  while (level.length > 1) {
    depth += 1;
    const next: string[] = [];
    for (let i = 0; i < level.length; i += 2) {
      const id = `n${depth}-${i / 2}`;
      nodes.push({ id, kind: "internal" });
      links.push({ source: level[i], target: id });
      if (level[i + 1]) links.push({ source: level[i + 1], target: id });
      next.push(id);
    }
    level = next;
  }
  const root = nodes.find((n) => n.id === level[0]);
  if (root) {
    root.kind = "root";
    root.hash = rootHash;
  }
  return { nodes, links };
}

export function MerkleExplorer() {
  const reduced = usePrefersReducedMotion();
  const [graphRef, inView] = useInView<HTMLDivElement>();
  const { data, error, isPending, dataUpdatedAt } = $api.useQuery(
    "get",
    "/transparency/log",
    {},
    { refetchInterval: POLL_MS },
  );
  const graph = useMemo(
    () => (data ? buildTree(data.entries ?? [], data.rootHash) : { nodes: [], links: [] }),
    [data],
  );

  // Pulse only when the live tree really grew between two responses (never on the first load), and
  // highlight exactly the leaves the growth added.
  const pulse = useLogPulse(data?.treeSize);
  const newLeafIds = useMemo(() => {
    if (!pulse) return null;
    const ids = new Set<string>();
    for (let i = pulse.from; i < pulse.to; i += 1) ids.add(`leaf-${i}`);
    return ids;
  }, [pulse]);

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h2 className="text-xs uppercase tracking-widest text-white/50">
          Transparency log · Merkle tree
        </h2>
        {error == null && dataUpdatedAt > 0 && (
          <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-white/55">
            <span className="relative flex h-1.5 w-1.5" aria-hidden="true">
              {!reduced && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
              )}
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
            </span>
            <span className="uppercase tracking-[0.2em] text-emerald-300/90">live</span>
            <span>· checked {new Date(dataUpdatedAt).toLocaleTimeString()}</span>
          </span>
        )}
      </div>
      <p className="mb-4 text-[11px] text-white/55">
        Polls the live log every {POLL_MS / 1000} seconds. When the tree grows, the new leaf lights
        up in the graph and the counter updates; every value comes from the live response.
      </p>

      {isPending && <p className="font-mono text-sm text-white/50">Loading the log…</p>}
      {error != null && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}

      {data && graph.nodes.length > 0 && (
        <>
          <div
            ref={graphRef}
            className="h-80 w-full"
            role="img"
            aria-label="3D Merkle transparency tree; the tree size and root are listed below."
          >
            {inView && (
              <MerkleGraph
                nodes={graph.nodes}
                links={graph.links}
                reduced={reduced}
                highlightIds={newLeafIds}
              />
            )}
          </div>
          <dl className="mt-2 grid gap-1 font-mono text-xs text-white/60">
            <div className="flex gap-3">
              <dt className="w-20 text-white/55">leaves</dt>
              <dd className="text-white/80">
                {data.treeSize}
                {pulse != null && (
                  <span
                    className={`ml-2 rounded bg-emerald-400/10 px-1.5 py-0.5 text-emerald-300 ${
                      reduced ? "" : "animate-pulse"
                    }`}
                  >
                    +{pulse.to - pulse.from} new
                  </span>
                )}
              </dd>
            </div>
            <div className="flex gap-3">
              <dt className="w-20 shrink-0 text-white/55">root</dt>
              <dd className="break-all text-amber-300/90">{data.rootHash}</dd>
            </div>
          </dl>
        </>
      )}
    </section>
  );
}
