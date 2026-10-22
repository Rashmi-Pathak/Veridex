import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { GenblazePanel } from "@/components/genblaze-panel";

function mockFetch(body: unknown, status = 200): void {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
}

const SAMPLE = {
  assetSha256: "e873502180536dcd",
  genblaze: {
    available: true,
    schemaVersion: "1.5",
    runId: "aa1c1514-1ce7-4f40-b739-27344475a8ce",
    canonicalHash: "a71e7c34808cc406",
    verifyHash: true,
    outputAssetSha256: "e873502180536dcd",
    generator: "genblaze",
    mode: "integrity (Mode 1)",
    storedOnB2: true,
  },
  rooted: {
    manifestId: "urn:c2pa:genblaze-b2-0000-0000-0000-000000000001",
    assetSha256: "e873502180536dcd",
    systemProvenance: { model: "seedream-5.0-lite", provider: "gmicloud-image", generator: "genblaze" },
    signatureValid: true,
    publicKeyHex: "b1d184a5",
  },
  reconciled: true,
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GenblazePanel", () => {
  it("renders the reconciled two-layer view", async () => {
    mockFetch(SAMPLE);
    render(<GenblazePanel />);
    expect(await screen.findByText(/reconciled: same asset, both layers verify/)).toBeTruthy();
    expect(screen.getByText(/Genblaze · integrity/)).toBeTruthy();
    expect(screen.getByText(/Veridex · signed/)).toBeTruthy();
    expect(screen.getByText(/via ObjectStorageSink/)).toBeTruthy();
    expect(screen.getByText("seedream-5.0-lite")).toBeTruthy();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);
    render(<GenblazePanel />);
    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
