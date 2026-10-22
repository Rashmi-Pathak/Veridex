import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { CheckpointLockPanel } from "@/components/checkpoint-lock-panel";

function mockFetch(body: unknown, status = 200): void {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
}

const CHECKPOINT = {
  epoch: 12,
  treeSize: 12,
  rootHash: "bd4b3094e2994bad9a52d0cfb5365241368014c81a624e2f520778bf8c676a88",
  signedAt: "2026-06-28T00:00:00Z",
  signatureB64: "c2ln",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("CheckpointLockPanel", () => {
  it("shows a real B2 Object-Lock seal with the bucket, retention, and verified signature", async () => {
    mockFetch({
      backend: "backblaze-b2",
      bucket: "rooted-checkpoints",
      key: "merkle/checkpoints/epoch_00000012.json",
      retentionMode: "compliance",
      retainUntil: "2026-09-26T00:00:00Z",
      checkpoint: CHECKPOINT,
      signatureVerified: true,
      immutable: true,
      modeled: false,
      keySource: "configured",
    });

    render(<CheckpointLockPanel />);

    expect(await screen.findByText(/Sealed on Backblaze B2/)).toBeTruthy();
    expect(screen.getByText(/bucket rooted-checkpoints/)).toBeTruthy();
    expect(screen.getByText("immutable")).toBeTruthy();
    expect(screen.getByText("merkle/checkpoints/epoch_00000012.json")).toBeTruthy();
    expect(screen.getByText(/compliance · until 2026-09-26/)).toBeTruthy();
    expect(screen.getByText(/✓ verified/)).toBeTruthy();
  });

  it("labels the in-memory model honestly when no locked bucket is configured", async () => {
    mockFetch({
      backend: "in-memory",
      bucket: null,
      key: "merkle/checkpoints/epoch_00000003.json",
      retentionMode: "compliance",
      retainUntil: "2026-09-26T00:00:00Z",
      checkpoint: { ...CHECKPOINT, epoch: 3, treeSize: 3 },
      signatureVerified: true,
      immutable: true,
      modeled: true,
      keySource: "ephemeral",
    });

    render(<CheckpointLockPanel />);

    expect(await screen.findByText(/Object Lock modeled in-memory/)).toBeTruthy();
    expect(screen.getByText(/Set B2_BUCKET_LOCKED/)).toBeTruthy();
    expect(screen.queryByText(/Sealed on Backblaze B2/)).toBeNull();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);

    render(<CheckpointLockPanel />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
