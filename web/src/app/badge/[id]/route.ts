import { NextResponse } from "next/server";

import {
  decodeManifestId,
  lookupManifest,
  receiptFacts,
  RECEIPT_API_BASE,
} from "@/lib/receipt-manifest";

// GET /badge/<manifestId> : the JSON the embeddable badge (public/badge.js) reads to render a live
// VERIFIED seal on any third-party site. It runs server-side on Vercel, calls the SBR API
// server-to-server (so the API needs no CORS of its own), and returns the small set of facts the
// badge shows, with CORS wide open because a badge is meant to be embedded anywhere. Read-only and
// public: it exposes only what the receipt permalink already shows. verified comes from the live
// Merkle proof's serverVerified, never asserted.

export const runtime = "nodejs";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Cache-Control": "public, max-age=300",
};

type ProofResponse = {
  leafIndex?: number;
  treeSize?: number;
  serverVerified?: boolean;
};

async function fetchProof(id: string): Promise<ProofResponse | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 3500);
  try {
    const res = await fetch(
      `${RECEIPT_API_BASE}/transparency/proof/${encodeURIComponent(id)}`,
      { signal: controller.signal, next: { revalidate: 300 } },
    );
    return res.ok ? ((await res.json()) as ProofResponse) : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export function OPTIONS() {
  return new NextResponse(null, { status: 204, headers: CORS });
}

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const manifestId = decodeManifestId(id);
  const lookup = await lookupManifest(id);

  if (lookup.status === "notfound") {
    return NextResponse.json(
      { manifestId, status: "notfound", verified: false },
      { headers: CORS },
    );
  }
  if (lookup.status === "unknown") {
    return NextResponse.json(
      { manifestId, status: "unknown", verified: false },
      { headers: CORS },
    );
  }

  const facts = receiptFacts(lookup.manifest);
  const proof = await fetchProof(id);
  return NextResponse.json(
    {
      manifestId,
      status: "found",
      verified: proof?.serverVerified === true,
      model: facts.model,
      provider: facts.provider,
      leafIndex: proof?.leafIndex ?? null,
      treeSize: proof?.treeSize ?? null,
      receiptUrl: `/r/${encodeURIComponent(manifestId)}`,
    },
    { headers: CORS },
  );
}
