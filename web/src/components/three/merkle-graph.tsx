"use client";

// The WebGL force-graph, isolated so it can be loaded client-only (next/dynamic ssr:false from the
// explorer): r3f-forcegraph touches `window` at import, which breaks server prerendering otherwise.
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import R3fForceGraph from "r3f-forcegraph";
import { memo, useCallback, useMemo, useRef } from "react";

export type Kind = "leaf" | "internal" | "root";
export type GNode = { id: string; kind: Kind; hash?: string };
export type GLink = { source: string; target: string };

const COLOR: Record<Kind, string> = {
  leaf: "#34d399", // emerald: a real manifest leaf
  internal: "#64748b", // slate: a structural Merkle node
  root: "#f59e0b", // amber: the signed checkpoint root
};

// A leaf appended while the page is open, during the explorer's pulse window: brighter and larger
// than the settled emerald so the new ingestion reads as an event, then it relaxes to normal. This
// is a one-time restyle on arrival (and one on expiry), not a per-frame animation, so the render
// loop cost stays what it was.
const NEW_LEAF_COLOR = "#a7f3d0";
const NEW_LEAF_VAL = 2.5;

const linkColor = () => "rgba(255,255,255,0.18)";

function Graph({
  nodes,
  links,
  highlightIds,
}: {
  nodes: GNode[];
  links: GLink[];
  highlightIds: ReadonlySet<string> | null;
}) {
  const fgRef = useRef<{ tickFrame: () => void } | null>(null);
  const data = useMemo(() => ({ nodes, links }), [nodes, links]);
  useFrame(() => fgRef.current?.tickFrame());
  const nodeColor = useCallback(
    (n: GNode) => (highlightIds?.has(n.id) ? NEW_LEAF_COLOR : COLOR[n.kind]),
    [highlightIds],
  );
  const nodeVal = useCallback(
    (n: GNode) => (highlightIds?.has(n.id) ? NEW_LEAF_VAL : 1),
    [highlightIds],
  );
  return (
    <R3fForceGraph
      ref={fgRef}
      graphData={data}
      nodeColor={nodeColor}
      nodeVal={nodeVal}
      nodeRelSize={4}
      nodeOpacity={0.95}
      linkColor={linkColor}
      linkWidth={0.5}
    />
  );
}

function MerkleGraph({
  nodes,
  links,
  reduced,
  highlightIds = null,
}: {
  nodes: GNode[];
  links: GLink[];
  reduced: boolean;
  highlightIds?: ReadonlySet<string> | null;
}) {
  return (
    <Canvas
      frameloop="always"
      camera={{ position: [0, 0, 220], far: 2000 }}
      dpr={[1, 1.5]}
      gl={{ antialias: false }}
    >
      <ambientLight intensity={Math.PI} />
      <Graph nodes={nodes} links={links} highlightIds={highlightIds} />
      <OrbitControls enablePan={false} enableZoom autoRotate={!reduced} autoRotateSpeed={0.5} />
    </Canvas>
  );
}

// memo: the explorer re-renders on every poll tick (its checked-at time moves), but when the log is
// unchanged every prop here is referentially stable, so the WebGL tree must not re-render for that.
export default memo(MerkleGraph);
