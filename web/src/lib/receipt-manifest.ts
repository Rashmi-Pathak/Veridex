// Server-side lookup of a recovered manifest from the live SBR API. Used by the receipt route's
// metadata (the real-404 decision) and by the dynamic Open Graph image. The browser talks to the API
// through the same-origin /api proxy, but that proxy does not exist server-side, so this fetches the
// ABSOLUTE API URL. It uses a short timeout and never throws: a slow or unreachable API resolves to
// "unknown", so metadata and the OG image fall back to a neutral card instead of breaking the build
// or the link unfurl.

export const RECEIPT_API_BASE = "https://veridex-api-ubvc.onrender.com";

export type ReceiptManifest = {
  manifestId: string;
  assetSha256?: string;
  createdAt?: string;
  systemProvenance?: Record<string, unknown>;
  softBindings?: { alg?: string; value?: string; scope?: string }[];
};

export type ManifestLookup =
  | { status: "found"; manifest: ReceiptManifest }
  | { status: "notfound" }
  | { status: "unknown" };

// On the Vercel deploy the [id] segment arrives URL-encoded (urn%3Ac2pa%3A...); decode it once to the
// clean manifest id before the API call. A clean id has no literal %, so decoding it is a no-op; a
// malformed % falls back to the raw value.
export function decodeManifestId(rawId: string): string {
  try {
    return decodeURIComponent(rawId);
  } catch {
    return rawId;
  }
}

export async function lookupManifest(rawId: string, timeoutMs = 3500): Promise<ManifestLookup> {
  const id = decodeManifestId(rawId);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${RECEIPT_API_BASE}/manifests/${encodeURIComponent(id)}`, {
      signal: controller.signal,
      // The registry changes rarely; cache the lookup briefly so repeated unfurls of one link do not
      // hammer the API.
      next: { revalidate: 300 },
    });
    if (res.ok) return { status: "found", manifest: (await res.json()) as ReceiptManifest };
    if (res.status === 404) return { status: "notfound" };
    return { status: "unknown" };
  } catch {
    return { status: "unknown" };
  } finally {
    clearTimeout(timer);
  }
}

const asString = (v: unknown): string | null => (typeof v === "string" && v.length > 0 ? v : null);

// The facts the OG card and the metadata draw from a found manifest, all from real API data. A
// watermark soft binding recovers by exact ID match, so its recovery score is a true 100/100; the
// `watermark` flag is derived from the manifest's real bindings, never asserted unconditionally.
export function receiptFacts(manifest: ReceiptManifest): {
  model: string | null;
  provider: string | null;
  watermark: boolean;
} {
  const sp = manifest.systemProvenance ?? {};
  const watermark = (manifest.softBindings ?? []).some(
    (b) => typeof b?.alg === "string" && b.alg.toLowerCase().includes("trustmark"),
  );
  return { model: asString(sp.model), provider: asString(sp.provider), watermark };
}
