import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { StatusPanel } from "@/components/status-panel";

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
  service: "veridex-api",
  transparency: {
    treeSize: 7,
    rootHash: "07a6d52bc815520b20c1615493240bc5dfc269bb7774e55328749f176c4df84c",
    checkpointEpoch: 7,
    keySource: "configured",
    publicKeyHex: "b1d184a5",
  },
  storage: { backend: "backblaze-b2", bucket: "rooted-dev", demoAssetPresent: true },
  recoveryIndex: "postgres+hnsw",
  algorithms: { watermarks: ["com.adobe.trustmark.P"], fingerprints: [] },
  generation: {
    enabled: false,
    configured: false,
    perIpPerDay: 5,
    globalPerDay: 50,
    maxInFlight: 2,
  },
  recoverySelfTest: {
    recovered: true,
    manifestId: "urn:c2pa:demo-0000-0000-0000-000000000001",
    similarityScore: 100,
    latencyMs: 12,
  },
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("StatusPanel", () => {
  it("renders the live recovery self-test and the real metrics", async () => {
    mockFetch(SAMPLE);
    render(<StatusPanel />);
    expect(await screen.findByText(/recovered the seed in 12 ms/)).toBeTruthy();
    expect(screen.getByText(/100\/100/)).toBeTruthy();
    expect(screen.getByText(/7 leaves · epoch 7/)).toBeTruthy();
    expect(screen.getByText(/Backblaze B2 \(rooted-dev\)/)).toBeTruthy();
    expect(screen.getByText("com.adobe.trustmark.P")).toBeTruthy();
    expect(screen.getByText(/Postgres \+ HNSW/)).toBeTruthy();
    // Live generation off in the sample -> honest "seed only".
    expect(screen.getByText("seed only")).toBeTruthy();
  });

  it("shows the live-generation caps when generation is enabled and configured", async () => {
    mockFetch({
      ...SAMPLE,
      generation: { ...SAMPLE.generation, enabled: true, configured: true },
    });
    render(<StatusPanel />);
    expect(await screen.findByText(/on · 5\/IP, 50\/day/)).toBeTruthy();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);
    render(<StatusPanel />);
    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
