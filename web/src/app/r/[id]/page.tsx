import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ProvenanceReceipt } from "@/components/provenance-receipt";
import { decodeManifestId, lookupManifest, receiptFacts } from "@/lib/receipt-manifest";

// The shared receipt link unfurls with a clean title and description (the per-receipt Open Graph image
// lives in opengraph-image.tsx alongside this file). The lookup never throws: a slow or unreachable
// API falls back to a generic, honest title rather than breaking metadata generation.
export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const manifestId = decodeManifestId(id);
  const lookup = await lookupManifest(id);

  if (lookup.status === "notfound") {
    return {
      title: "Provenance receipt not found: Veridex",
      description: `No provenance record for ${manifestId} in this Veridex registry. A single instance only serves records it has ingested.`,
      robots: { index: false, follow: true },
    };
  }

  if (lookup.status === "found") {
    const { model } = receiptFacts(lookup.manifest);
    return {
      title: `Provenance receipt: ${manifestId}`,
      description: model
        ? `Verified provenance receipt for ${model}, recovered and signed by Veridex with a transparency-log proof. Manifest ${manifestId}.`
        : `Verified provenance receipt recovered and signed by Veridex with a transparency-log proof. Manifest ${manifestId}.`,
      openGraph: {
        title: model ? `Veridex provenance receipt: ${model}` : "Veridex provenance receipt",
        type: "article",
      },
    };
  }

  // unknown (slow or unreachable API): a generic title that claims neither found nor not-found.
  return {
    title: `Provenance receipt: ${manifestId}`,
    description:
      "A Veridex provenance receipt: recovered, signed C2PA provenance with a transparency-log proof.",
  };
}

// /r/<manifestId> : a shareable, citable provenance-receipt permalink for one recovered manifest.
export default async function ReceiptPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // On the live Vercel deploy the dynamic segment arrives URL-ENCODED (urn%3Ac2pa%3A...), so decode
  // it to the clean manifest id (urn:c2pa:...) before passing it down. The receipt then applies a
  // single encodeURIComponent for its fetch; without this decode that becomes a double-encode
  // (%3A -> %253A) and every colon-bearing id 404s. A clean id contains no literal %, so decoding it
  // is a no-op; a malformed % falls back to the raw value.
  const manifestId = decodeManifestId(id);

  // A confirmed 404 from the API yields a real HTTP 404 (rendered by not-found.tsx). A slow or
  // unreachable API does NOT 404 a valid id: the receipt renders and the client component shows its
  // own loading / not-found / error state, so an API hiccup never turns a real id into a 404.
  const lookup = await lookupManifest(id);
  if (lookup.status === "notfound") notFound();

  return <ProvenanceReceipt manifestId={manifestId} />;
}
