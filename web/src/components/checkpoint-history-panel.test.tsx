import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { CheckpointHistoryPanel } from "@/components/checkpoint-history-panel";

function mockFetch(body: unknown, status = 200): void {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
}

const ENTRY = {
  epoch: 12,
  treeSize: 12,
  rootHash: "bd4b3094e2994bad9a52d0cfb5365241368014c81a624e2f520778bf8c676a88",
  signedAt: "2026-06-29T00:00:00Z",
  signatureVerified: true,
  retainUntil: "2026-09-27T00:00:00Z",
  immutable: true,
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("CheckpointHistoryPanel", () => {
  it("renders the B2 Object-Lock checkpoint chain", async () => {
    mockFetch({
      backend: "backblaze-b2",
      bucket: "rooted-locked",
      count: 2,
      modeled: false,
      entries: [ENTRY, { ...ENTRY, epoch: 13, treeSize: 13 }],
    });

    render(<CheckpointHistoryPanel />);

    expect(await screen.findByText(/2 checkpoints/)).toBeTruthy();
    expect(screen.getByText(/on Backblaze B2/)).toBeTruthy();
    expect(screen.getByText(/bucket rooted-locked/)).toBeTruthy();
    expect(screen.getByText("epoch 12")).toBeTruthy();
    expect(screen.getByText("epoch 13")).toBeTruthy();
    expect(screen.getAllByText(/immutable · until 2026-09-27/).length).toBe(2);
  });

  it("labels the in-memory model when no locked bucket is configured", async () => {
    mockFetch({
      backend: "in-memory",
      bucket: null,
      count: 1,
      modeled: true,
      entries: [ENTRY],
    });

    render(<CheckpointHistoryPanel />);

    expect(await screen.findByText(/Object Lock modeled in-memory/)).toBeTruthy();
    expect(screen.queryByText(/on Backblaze B2/)).toBeNull();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);

    render(<CheckpointHistoryPanel />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
