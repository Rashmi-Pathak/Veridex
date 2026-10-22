import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { RebuildPanel } from "@/components/rebuild-panel";

function mockFetch(body: unknown, status = 200): void {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
}

const BASE = {
  available: true,
  backend: "backblaze-b2",
  manifestsScanned: 7,
  manifestsRebuilt: 7,
  skipped: 2,
  leavesRebuilt: 7,
  demoRecovered: true,
  demoSimilarity: 100,
  rebuiltTreeSize: 7,
  rebuiltRootHash: "aa11bb22cc33dd44ee55ff66aa11bb22cc33dd44ee55ff66aa11bb22cc33dd44",
  liveTreeSize: 13,
  liveRootHash: "bd4b3094e2994bad9a52d0cfb5365241368014c81a624e2f520778bf8c676a88",
  rootsMatch: false,
  note: "Rebuilt 7 image manifests from B2 content-addressed objects with no database; the demo asset recovers against the rebuilt index.",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RebuildPanel", () => {
  it("shows the recovery index reconstructed from B2 with the demo recovered", async () => {
    mockFetch(BASE);

    render(<RebuildPanel />);

    expect(await screen.findByText(/recovered from B2 alone/)).toBeTruthy();
    expect(screen.getByText(/7 manifests · 7 log leaves · 2 skipped/)).toBeTruthy();
    expect(screen.getByText(/13 leaves/)).toBeTruthy();
  });

  it("is honest when no storage backend is configured", async () => {
    mockFetch({
      ...BASE,
      available: false,
      backend: "none",
      demoRecovered: false,
      note: "No storage backend configured; rebuild requires Backblaze B2 (or the in-memory store in tests).",
    });

    render(<RebuildPanel />);

    expect(await screen.findByText(/No storage backend configured/)).toBeTruthy();
    expect(screen.queryByText(/recovered from B2 alone/)).toBeNull();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);

    render(<RebuildPanel />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
