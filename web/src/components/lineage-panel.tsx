"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { useInView } from "@/lib/use-in-view";
import { usePrefersReducedMotion } from "@/lib/use-reduced-motion-pref";
import type { GLink, GNode } from "./three/lineage-graph";

// Client-only: r3f-forcegraph touches window at import, so the graph must not be server-rendered.
const LineageGraph = dynamic(() => import("./three/lineage-graph"), { ssr: false });

// /api/demo/lineage returns a real C2PA ingredient graph (camelCase). Each node is a signed manifest,
// each edge a cryptographically-linked ingredient. Raw fetch (this route is not in the typed client).
type NodeKind = "generation" | "edit" | "composite";
type LineageNode = {
  id: string;
  title: string | null;
  action: string | null;
  kind: NodeKind;
  isActive: boolean;
};
type LineageEdge = { source: string; target: string; relationship: string };
type LineageResponse = {
  nodes: LineageNode[];
  edges: LineageEdge[];
  validationState: string | null;
};

const KIND_LABEL: Record<NodeKind, string> = {
  generation: "generation",
  edit: "edit",
  composite: "composite",
};

const CHIP_COLOR: Record<NodeKind, string> = {
  generation: "#34d399",
  edit: "#60a5fa",
  composite: "#a78bfa",
};

export function LineagePanel() {
  const reduced = usePrefersReducedMotion();
  const [graphRef, inView] = useInView<HTMLDivElement>();
  const [data, setData] = useState<LineageResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/lineage")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: LineageResponse) => setData(d))
      .catch(() => setError(true));
  }, []);

  const graphNodes = useMemo<GNode[]>(
    () =>
      (data?.nodes ?? []).map((n) => ({
        id: n.id,
        kind: n.kind,
        title: n.title,
        isActive: n.isActive,
      })),
    [data],
  );

  const graphLinks = useMemo<GLink[]>(
    () => (data?.edges ?? []).map((e) => ({ source: e.source, target: e.target })),
    [data],
  );

  const trusted = data?.validationState === "Trusted";

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-3 text-xs uppercase tracking-widest text-white/50">Provenance lineage</h2>
      <p className="mb-4 max-w-xl text-sm text-white/60">
        A real C2PA ingredient graph: an AI generation, two edits, and a composite, each a signed
        manifest with cryptographically-linked ingredients.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !data && <p className="font-mono text-sm text-white/50">Reading the lineage…</p>}

      {data && (
        <>
          {data.validationState != null && (
            <div className="mb-4">
              <span
                className={`inline-block rounded-md px-2 py-1 font-mono text-xs ${
                  trusted
                    ? "bg-emerald-400/10 text-emerald-300"
                    : "bg-white/10 text-white/75"
                }`}
              >
                {data.validationState}
              </span>
              {trusted && (
                <p className="mt-2 text-xs text-white/50">
                  Validated against the C2PA conformance test trust list (FOR TESTING ONLY);
                  production uses the C2PA production trust list.
                </p>
              )}
            </div>
          )}

          {graphNodes.length > 0 && (
            <div
              ref={graphRef}
              className="h-72 w-full"
              role="img"
              aria-label="3D provenance lineage graph; the same nodes and relationships are listed below."
            >
              {inView && <LineageGraph nodes={graphNodes} links={graphLinks} reduced={reduced} />}
            </div>
          )}

          <ul className="mt-3 flex flex-wrap gap-4 text-xs text-white/60">
            {(["generation", "edit", "composite"] as NodeKind[]).map((k) => (
              <li key={k} className="flex items-center gap-2">
                <span
                  className="inline-block h-3 w-3 rounded-full"
                  style={{ backgroundColor: CHIP_COLOR[k] }}
                  aria-hidden="true"
                />
                <span>{KIND_LABEL[k]}</span>
              </li>
            ))}
          </ul>

          <ul className="mt-4 grid gap-2 font-mono text-xs text-white/75">
            {data.nodes.map((n) => (
              <li key={n.id} className="flex flex-wrap items-baseline gap-2">
                <span
                  className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: n.isActive ? "#f59e0b" : CHIP_COLOR[n.kind] }}
                  aria-hidden="true"
                />
                <span className="text-white/85">{n.title ?? n.id}</span>
                {n.action != null && <span className="text-white/55">{n.action}</span>}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
