"use client";

// The WebGL force-graph for the C2PA provenance lineage, isolated so it can be loaded client-only
// (next/dynamic ssr:false from the panel): r3f-forcegraph touches `window` at import, which breaks
// server prerendering otherwise. Per-node 3D text labels are intentionally omitted: troika-three-text
// (drei's Text dependency) is not resolvable in this workspace, so the readable lineage lives in the
// panel's legend and text fallback list, and the graph carries the meaning through node color and the
// directional arrows that show the ingredient flow.
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import R3fForceGraph from "r3f-forcegraph";
import { useMemo, useRef } from "react";

export type Kind = "generation" | "edit" | "composite";
export type GNode = { id: string; kind: Kind; title: string | null; isActive: boolean };
export type GLink = { source: string; target: string };

const COLOR: Record<Kind, string> = {
  generation: "#34d399", // emerald: the real AI generation, the root of the lineage
  edit: "#60a5fa", // blue: an edit on a parent manifest
  composite: "#a78bfa", // violet: a composite that ingests parents
};

// The active (final) node gets a brighter amber and a larger radius so the end of the lineage reads.
const ACTIVE_COLOR = "#f59e0b";

function nodeColor(n: GNode): string {
  return n.isActive ? ACTIVE_COLOR : COLOR[n.kind];
}

function nodeVal(n: GNode): number {
  return n.isActive ? 6 : 2;
}

function Graph({ nodes, links }: { nodes: GNode[]; links: GLink[] }) {
  const fgRef = useRef<{ tickFrame: () => void } | null>(null);
  const data = useMemo(() => ({ nodes, links }), [nodes, links]);
  useFrame(() => fgRef.current?.tickFrame());
  return (
    <R3fForceGraph
      ref={fgRef}
      graphData={data}
      nodeColor={(n: GNode) => nodeColor(n)}
      nodeVal={(n: GNode) => nodeVal(n)}
      nodeRelSize={4}
      nodeOpacity={0.95}
      linkColor={() => "rgba(255,255,255,0.22)"}
      linkWidth={0.6}
      linkDirectionalArrowLength={3.5}
      linkDirectionalArrowRelPos={1}
    />
  );
}

export default function LineageGraph({
  nodes,
  links,
  reduced,
}: {
  nodes: GNode[];
  links: GLink[];
  reduced: boolean;
}) {
  return (
    <Canvas
      frameloop="always"
      camera={{ position: [0, 0, 180], far: 2000 }}
      dpr={[1, 1.5]}
      gl={{ antialias: false }}
    >
      <ambientLight intensity={Math.PI} />
      <Graph nodes={nodes} links={links} />
      <OrbitControls enablePan={false} enableZoom autoRotate={!reduced} autoRotateSpeed={0.5} />
    </Canvas>
  );
}
