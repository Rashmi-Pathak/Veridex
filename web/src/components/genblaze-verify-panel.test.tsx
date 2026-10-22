import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { GenblazeVerifyPanel } from "@/components/genblaze-verify-panel";

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
  available: true,
  genblazeVersion: "0.3.7",
  schemaVersion: "1.5",
  runId: "aa1c1514-1ce7-4f40-b739-27344475a8ce",
  hashOk: true,
  outputsAllSha256: true,
  metadataInSpec: true,
  manifestVerified: true,
  byteSource: "fixture",
  byteVerified: true,
  sizeVerified: true,
  declaredSha256: "e873502180536dcd7d3f71d73545a710",
  fetchedSha256: "e873502180536dcd7d3f71d73545a710",
  declaredSizeBytes: 907976,
  fetchedSizeBytes: 907976,
  assetHost: "s3.us-east-005.backblazeb2.com",
  verified: true,
  note: "byte-level verification passed",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GenblazeVerifyPanel", () => {
  it("renders the verified byte-level view", async () => {
    mockFetch(SAMPLE);
    render(<GenblazeVerifyPanel />);
    expect(
      await screen.findByText(/verified: the stored asset bytes hash to the manifest/),
    ).toBeTruthy();
    expect(screen.getByText(/Byte-level · verify --fetch/)).toBeTruthy();
    expect(screen.getByText("0.3.7")).toBeTruthy();
    expect(screen.getByText("s3.us-east-005.backblazeb2.com")).toBeTruthy();
  });

  it("shows an honest message when verification is unavailable", async () => {
    mockFetch({ ...SAMPLE, available: false, verified: false, note: "the manifest is unavailable" });
    render(<GenblazeVerifyPanel />);
    expect(await screen.findByText(/Verification unavailable/)).toBeTruthy();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);
    render(<GenblazeVerifyPanel />);
    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
