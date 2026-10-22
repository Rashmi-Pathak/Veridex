import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { StoragePanel } from "@/components/storage-panel";

function mockFetch(body: unknown, status = 200): void {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("StoragePanel", () => {
  it("shows Backblaze B2 with the bucket and object keys when the backend is B2", async () => {
    mockFetch({
      backend: "backblaze-b2",
      bucket: "rooted-dev",
      keys: {
        asset: "assets/ad/3c/ad3c659392",
        manifest: "manifests/urn_c2pa_demo.json",
        signature: "signatures/urn_c2pa_demo.cose",
      },
      present: { asset: true, manifest: true, signature: true },
    });

    render(<StoragePanel />);

    expect(await screen.findByText(/Stored content-addressably on Backblaze B2/)).toBeTruthy();
    expect(screen.getByText(/bucket rooted-dev/)).toBeTruthy();
    expect(screen.getByText("manifests/urn_c2pa_demo.json")).toBeTruthy();
  });

  it("shows the in-memory message when no B2 backend is configured", async () => {
    mockFetch({
      backend: "none",
      bucket: null,
      keys: { asset: "assets/x", manifest: "manifests/x.json", signature: "signatures/x.cose" },
      present: { asset: false, manifest: false, signature: false },
    });

    render(<StoragePanel />);

    expect(await screen.findByText(/In-memory demo/)).toBeTruthy();
    expect(screen.queryByText(/Backblaze B2 \(bucket/)).toBeNull();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);

    render(<StoragePanel />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
