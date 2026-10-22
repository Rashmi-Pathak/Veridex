"use client";

import { useEffect, useState } from "react";

// Adversarial-robustness grid. The same demo asset is put through common transforms and the real
// recovery path runs on each, so this shows honestly what perceptual-hash recovery survives and
// what it does not: PDQ is robust to re-encode and scaling, not to rotation or large crops. The raw
// Hamming distance is shown for every row, including the failures, which is the honest part. Reads
// /api/demo/robustness.
type RobustnessRow = {
  transform: string;
  recovered: boolean;
  similarityScore: number | null;
  hammingDistance: number;
};
type RobustnessGrid = {
  manifestId: string;
  threshold: number;
  rows: RobustnessRow[];
};

export function RobustnessPanel() {
  const [grid, setGrid] = useState<RobustnessGrid | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/demo/robustness")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: RobustnessGrid) => setGrid(d))
      .catch(() => setError(true));
  }, []);

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">Robustness grid</h2>
      <p className="mb-4 text-[11px] text-white/55">
        The same asset under common transforms, each run through the real recovery path. Perceptual
        hashing survives re-encode and scaling, not rotation or large crops. The raw Hamming distance
        is shown for every row, including the failures.
      </p>

      {error && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {!error && !grid && <p className="font-mono text-sm text-white/50">Running transforms…</p>}

      {grid && (
        <>
          <div className="grid grid-cols-[1fr_auto_auto] gap-x-4 gap-y-1 font-mono text-xs">
            <div className="text-white/45">transform</div>
            <div className="text-right text-white/45">recovery</div>
            <div className="text-right text-white/45">hamming</div>
            {grid.rows.map((r) => (
              <RowCells key={r.transform} row={r} threshold={grid.threshold} />
            ))}
          </div>
          <p className="mt-3 text-[11px] text-white/45">
            Recovery threshold: Hamming distance at most {grid.threshold} of 256 bits. PDQ is an
            internal index, never advertised as a registered C2PA algorithm.
          </p>
        </>
      )}
    </section>
  );
}

function RowCells({ row, threshold }: { row: RobustnessRow; threshold: number }) {
  return (
    <>
      <div className="text-white/70">{row.transform}</div>
      <div className="text-right">
        {row.recovered ? (
          <span className="text-emerald-300">
            ✓ recovered{row.similarityScore !== null ? ` ${row.similarityScore}` : ""}
          </span>
        ) : (
          <span className="text-amber-400">✗ not recovered</span>
        )}
      </div>
      <div
        className={`text-right ${row.hammingDistance <= threshold ? "text-white/70" : "text-white/40"}`}
      >
        {row.hammingDistance}
      </div>
    </>
  );
}
