import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { FederationPanel } from "@/components/federation-panel";

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

describe("FederationPanel", () => {
  it("lists configured peers when federation is enabled", async () => {
    mockFetch({
      enabled: true,
      peers: ["https://peer-a.example", "https://peer-b.example"],
      note: "On a local miss the resolver forwards the soft-binding query to these peer SBR nodes.",
    });

    render(<FederationPanel />);

    expect(await screen.findByText(/2 peers configured/)).toBeTruthy();
    expect(screen.getByText(/https:\/\/peer-a.example\/matches\/byBinding/)).toBeTruthy();
    expect(screen.getByText(/these peer SBR nodes/)).toBeTruthy();
  });

  it("is honest when no peers are configured", async () => {
    mockFetch({
      enabled: false,
      peers: [],
      note: "No peers configured. Set VERIDEX_SBR_PEERS to other SBR resolver URLs.",
    });

    render(<FederationPanel />);

    expect(await screen.findByText(/no peers/)).toBeTruthy();
    expect(screen.getByText(/No peers configured/)).toBeTruthy();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);

    render(<FederationPanel />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
