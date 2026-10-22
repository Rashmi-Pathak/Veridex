import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { MetricsRibbon } from "@/components/metrics-ribbon";

function mockFetch(body: unknown, status = 200): void {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
}

const STATUS = {
  transparency: { treeSize: 13, checkpointEpoch: 13 },
  storage: { backend: "backblaze-b2" },
  recoveryIndex: "postgres+hnsw",
  recoverySelfTest: { recovered: true, similarityScore: 100, latencyMs: 72 },
  generation: { enabled: true },
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MetricsRibbon", () => {
  it("renders live metrics from /api/status", async () => {
    mockFetch(STATUS);

    render(<MetricsRibbon />);

    expect(await screen.findByText(/13 leaves · epoch 13/)).toBeTruthy();
    expect(screen.getByText(/72ms · 100\/100/)).toBeTruthy();
    expect(screen.getByText("Backblaze B2")).toBeTruthy();
    expect(screen.getByText("postgres+hnsw")).toBeTruthy();
    expect(screen.getByText("live")).toBeTruthy();
  });

  it("degrades to connecting when the API is unreachable", async () => {
    mockFetch("", 500);

    render(<MetricsRibbon />);

    expect(await screen.findByText(/status connecting/)).toBeTruthy();
  });
});
