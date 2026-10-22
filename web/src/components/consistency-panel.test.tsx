import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { ConsistencyPanel } from "@/components/consistency-panel";

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
  priorSize: 12,
  priorRootHash: "aa11bb22cc33dd44ee55ff66aa11bb22cc33dd44ee55ff66aa11bb22cc33dd44",
  treeSize: 13,
  rootHash: "bd4b3094e2994bad9a52d0cfb5365241368014c81a624e2f520778bf8c676a88",
  serverVerified: true,
  sealedInObjectLock: false,
  sealedRootMatches: false,
  backend: "in-memory",
  bucket: null,
  retainUntil: null,
  keySource: "ephemeral",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ConsistencyPanel", () => {
  it("shows a verified append-only proof bound to a B2 Object-Lock seal", async () => {
    mockFetch({
      ...BASE,
      serverVerified: true,
      sealedInObjectLock: true,
      sealedRootMatches: true,
      backend: "backblaze-b2",
      bucket: "rooted-locked",
      retainUntil: "2026-09-27T00:00:00Z",
      keySource: "configured",
    });

    render(<ConsistencyPanel />);

    expect(await screen.findByText(/append-only verified/)).toBeTruthy();
    expect(screen.getByText(/size 12 → size 13/)).toBeTruthy();
    expect(screen.getByText(/WORM-sealed on Backblaze B2/)).toBeTruthy();
    expect(screen.getByText(/bucket rooted-locked/)).toBeTruthy();
    expect(screen.getByText(/retained until 2026-09-27/)).toBeTruthy();
  });

  it("proves append-only honestly when the prior state is not individually sealed", async () => {
    mockFetch(BASE);

    render(<ConsistencyPanel />);

    expect(await screen.findByText(/append-only verified/)).toBeTruthy();
    expect(screen.getByText(/not individually sealed here/)).toBeTruthy();
    expect(screen.queryByText(/WORM-sealed on Backblaze B2/)).toBeNull();
  });

  it("labels a single-leaf log honestly", async () => {
    mockFetch({ ...BASE, available: false, priorSize: 1, treeSize: 1 });

    render(<ConsistencyPanel />);

    expect(await screen.findByText(/single leaf/)).toBeTruthy();
    expect(screen.queryByText(/append-only verified/)).toBeNull();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);

    render(<ConsistencyPanel />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
