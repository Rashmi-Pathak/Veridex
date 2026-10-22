"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

// A shareable provenance receipt for a single recovered manifest. Given a manifest id it fetches the
// recovered (redacted) manifest and its transparency inclusion proof from the live SBR API, and
// renders a citable card: the system provenance, the asset hash, and the Merkle proof pinned to a
// signed checkpoint. The URL /r/<manifestId> is a permanent, linkable record of a recovery.
type Manifest = {
  manifestId: string;
  assetSha256: string;
  createdAt: string;
  systemProvenance: Record<string, unknown>;
};

type Proof = {
  manifestId: string;
  leafIndex: number;
  treeSize: number;
  leafHash: string;
  rootHash: string;
  serverVerified: boolean;
  keySource: string;
  publicKeyHex: string;
  checkpoint?: { epoch?: number; signedAt?: string; treeSize?: number } | null;
};

const short = (s: string | null | undefined, n = 20) =>
  s ? (s.length > n ? `${s.slice(0, n)}…` : s) : "-";
const prov = (m: Manifest | null, k: string) =>
  m ? String((m.systemProvenance as Record<string, unknown>)?.[k] ?? "-") : "-";

export function ProvenanceReceipt({ manifestId }: { manifestId: string }) {
  const [m, setM] = useState<Manifest | null>(null);
  const [p, setP] = useState<Proof | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "notfound" | "error">("loading");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const enc = encodeURIComponent(manifestId);
    Promise.all([
      // Only a 404 is "not found"; any other non-OK is a real backend error -> the error state.
      fetch(`/api/manifests/${enc}`).then((r) => {
        if (r.ok) return r.json();
        if (r.status === 404) return null;
        throw new Error(`manifest ${r.status}`);
      }),
      // The proof is secondary: a 404 means no proof yet; any other failure is logged but does not
      // fail the page, so the manifest still renders.
      fetch(`/api/transparency/proof/${enc}`).then((r) => {
        if (r.ok) return r.json();
        if (r.status !== 404) console.warn("Veridex receipt: proof fetch failed", r.status);
        return null;
      }),
    ])
      .then(([mm, pp]) => {
        setM(mm);
        setP(pp);
        setState(mm ? "ok" : "notfound");
      })
      .catch(() => setState("error"));
  }, [manifestId]);

  const copy = () => {
    if (typeof window !== "undefined") {
      navigator.clipboard?.writeText(window.location.href).then(
        () => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        },
        () => {},
      );
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-6 px-6 py-16">
      <header className="space-y-2">
        <p className="font-mono text-xs uppercase tracking-[0.3em] text-white/55">
          Veridex · provenance receipt
        </p>
        <h1 className="break-all text-xl font-semibold sm:text-2xl">{manifestId}</h1>
      </header>

      {state === "loading" && (
        <p className="font-mono text-sm text-white/50">Recovering the provenance record…</p>
      )}
      {state === "error" && <p className="font-mono text-sm text-amber-400">Backend unreachable.</p>}
      {state === "notfound" && (
        <div className="rounded-xl border border-white/15 bg-white/[0.03] p-5">
          <p className="font-mono text-sm text-amber-400">
            No provenance found in this Veridex registry for this id.
          </p>
          <p className="mt-2 text-[11px] text-white/50">
            A single instance only serves records it has ingested.
          </p>
        </div>
      )}

      {state === "ok" && m && (
        <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
          <p
            className={`mb-3 font-mono text-sm ${p?.serverVerified ? "text-emerald-300" : "text-white/60"}`}
          >
            {p?.serverVerified
              ? "✓ VERIFIED, included in the signed transparency log"
              : "recovered (proof pending)"}
          </p>

          <p className="mb-1 text-[11px] uppercase tracking-widest text-white/45">Provenance</p>
          <dl className="mb-4 grid gap-1 font-mono text-xs text-white/70">
            <Row k="model" v={prov(m, "model")} />
            <Row k="provider" v={prov(m, "provider")} />
            <Row k="generator" v={prov(m, "generator")} />
            <Row k="asset sha256" v={short(m.assetSha256)} />
            <Row k="created" v={m.createdAt} />
          </dl>

          <p className="mb-1 text-[11px] uppercase tracking-widest text-white/45">
            Transparency proof
          </p>
          <dl className="grid gap-1 font-mono text-xs text-white/70">
            <Row k="leaf index" v={p ? String(p.leafIndex) : "-"} />
            <Row k="tree size" v={p ? String(p.treeSize) : "-"} />
            <Row k="root hash" v={short(p?.rootHash)} />
            <Row
              k="checkpoint"
              v={p?.checkpoint?.epoch != null ? `epoch ${p.checkpoint.epoch}` : "-"}
            />
            <Row k="signing key" v={short(p?.publicKeyHex)} />
            <Row k="key source" v={p?.keySource ?? "-"} />
          </dl>

          <div className="mt-4 flex items-center gap-3">
            <button
              onClick={copy}
              className="rounded-md border border-white/15 px-3 py-1.5 text-xs text-white/80 hover:bg-white/[0.06]"
            >
              {copied ? "copied" : "copy link"}
            </button>
            <Link href="/" className="text-xs text-blue-400 hover:underline">
              Veridex &rarr;
            </Link>
          </div>
          <p className="mt-4 text-[11px] text-white/45">Provenance proves origin, not truth.</p>
        </section>
      )}
    </main>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-3">
      <dt className="w-28 shrink-0 text-white/55">{k}</dt>
      <dd className="break-all text-white/80">{v}</dd>
    </div>
  );
}
