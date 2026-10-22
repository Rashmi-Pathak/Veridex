import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { RobustnessPanel } from "@/components/robustness-panel";

function mockFetch(body: unknown, status = 200): void {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
}

const GRID = {
  manifestId: "urn:c2pa:demo-0000-0000-0000-000000000001",
  threshold: 31,
  rows: [
    { transform: "original", recovered: true, similarityScore: 100, hammingDistance: 0 },
    { transform: "JPEG quality 50", recovered: true, similarityScore: 98, hammingDistance: 4 },
    { transform: "rotate 90 deg", recovered: false, similarityScore: null, hammingDistance: 120 },
  ],
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RobustnessPanel", () => {
  it("renders an honest pass/fail grid with raw Hamming distances", async () => {
    mockFetch(GRID);

    render(<RobustnessPanel />);

    expect(await screen.findByText("original")).toBeTruthy();
    // a survived transform shows recovered + its similarity
    expect(screen.getByText(/✓ recovered 98/)).toBeTruthy();
    // a failed transform shows the honest fail and still reports its distance
    expect(screen.getByText(/✗ not recovered/)).toBeTruthy();
    expect(screen.getByText("120")).toBeTruthy();
    expect(screen.getByText(/Hamming distance at most 31/)).toBeTruthy();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);

    render(<RobustnessPanel />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
