import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { ProvenanceReceipt } from "@/components/provenance-receipt";

const MANIFEST = {
  manifestId: "urn:c2pa:demo-0000-0000-0000-000000000001",
  assetSha256: "a699e1329ddb5488b49732894c86ee0a",
  createdAt: "2026-06-27T00:00:00Z",
  systemProvenance: { model: "seedream-5.0-lite", provider: "gmicloud-image", generator: "genblaze" },
};
const PROOF = {
  manifestId: "urn:c2pa:demo-0000-0000-0000-000000000001",
  leafIndex: 0,
  treeSize: 7,
  leafHash: "abc123",
  rootHash: "def456789",
  serverVerified: true,
  keySource: "configured",
  publicKeyHex: "b1d184a5fe16",
  checkpoint: { epoch: 7, signedAt: "2026-06-29T00:00:00Z" },
};

function mockFetch(map: Record<string, unknown>): void {
  globalThis.fetch = vi.fn(async (url: string) => {
    const body = url.includes("/transparency/proof/") ? map.proof : map.manifest;
    return new Response(JSON.stringify(body), {
      status: body ? 200 : 404,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ProvenanceReceipt", () => {
  it("renders the verified receipt with provenance + the transparency proof", async () => {
    mockFetch({ manifest: MANIFEST, proof: PROOF });
    render(<ProvenanceReceipt manifestId={MANIFEST.manifestId} />);
    expect(await screen.findByText(/VERIFIED/)).toBeTruthy();
    expect(screen.getByText("seedream-5.0-lite")).toBeTruthy();
    expect(screen.getByText("genblaze")).toBeTruthy();
    expect(screen.getByText(/epoch 7/)).toBeTruthy();
    expect(screen.getByText("Provenance proves origin, not truth.")).toBeTruthy();
  });

  it("shows an honest not-found when the id is not in the registry", async () => {
    mockFetch({ manifest: null, proof: null });
    render(<ProvenanceReceipt manifestId="urn:c2pa:nope" />);
    expect(await screen.findByText(/No provenance found in this Veridex registry/)).toBeTruthy();
  });
});
