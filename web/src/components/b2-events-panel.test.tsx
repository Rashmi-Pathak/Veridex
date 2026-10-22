import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { B2EventsPanel } from "@/components/b2-events-panel";

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

describe("B2EventsPanel", () => {
  it("shows configured status and a recent ingested object", async () => {
    mockFetch({
      configured: true,
      watchPrefix: "ingest/",
      count: 1,
      recent: [
        {
          objectKey: "ingest/photo.png",
          manifestId: "urn:c2pa:b2-abc123",
          bucket: "rooted-dev",
          sizeBytes: 4096,
          ingestedAt: "2026-06-29T00:00:00Z",
        },
      ],
    });
    render(<B2EventsPanel />);
    expect(await screen.findByText(/webhook configured/)).toBeTruthy();
    expect(screen.getByText(/ingest\/photo.png/)).toBeTruthy();
    expect(screen.getByText("recoverable")).toBeTruthy();
  });

  it("shows the activation hint when not configured", async () => {
    mockFetch({ configured: false, watchPrefix: "ingest/", count: 0, recent: [] });
    render(<B2EventsPanel />);
    expect(await screen.findByText(/add a B2 Event Notification rule to activate/)).toBeTruthy();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);
    render(<B2EventsPanel />);
    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
