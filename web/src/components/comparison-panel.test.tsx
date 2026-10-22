import type { ReactElement } from "react";

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { fetchClient } from "@/lib/api/client";
import { ComparisonPanel } from "@/components/comparison-panel";

// Mock the official C2PA reader at the dynamic-import boundary so the test runs without WASM. The
// component imports "@contentauth/c2pa-web/inline" dynamically; vi.mock intercepts that too.
vi.mock("@contentauth/c2pa-web/inline", () => ({ createC2pa: vi.fn() }));
import { createC2pa } from "@contentauth/c2pa-web/inline";

type PostResult = Awaited<ReturnType<typeof fetchClient.POST>>;
type GetResult = Awaited<ReturnType<typeof fetchClient.GET>>;

function ok<T>(data: T): { data: T; error: undefined; response: Response } {
  return { data, error: undefined, response: new Response() };
}

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function selectFile(container: HTMLElement): void {
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  const file = new File(["x"], "stripped.jpg", { type: "image/jpeg" });
  fireEvent.change(input, { target: { files: [file] } });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ComparisonPanel", () => {
  it("official reader finds nothing while Veridex recovers, on the same bytes", async () => {
    // The official SDK returns a falsy reader (no embedded manifest in the stripped bytes).
    vi.mocked(createC2pa).mockResolvedValue({
      reader: { fromBlob: vi.fn().mockResolvedValue(null) },
    } as unknown as Awaited<ReturnType<typeof createC2pa>>);
    vi.spyOn(fetchClient, "POST").mockResolvedValue(
      ok({ matches: [{ manifestId: "urn:c2pa:demo", similarityScore: 100 }] }) as unknown as PostResult,
    );
    vi.spyOn(fetchClient, "GET").mockResolvedValue(
      ok({
        manifestId: "urn:c2pa:demo",
        assetSha256: "deadbeef",
        createdAt: "2026-06-27T00:00:00Z",
        systemProvenance: { model: "seedream-5.0-lite" },
        softBindings: [],
      }) as unknown as GetResult,
    );

    const { container } = renderWithClient(<ComparisonPanel />);
    selectFile(container);

    expect(await screen.findByText("No Content Credentials")).toBeTruthy();
    expect(await screen.findByText("RECOVERED")).toBeTruthy();
    expect(await screen.findByText(/seedream-5.0-lite/)).toBeTruthy();
  });

  it("shows the embedded manifest when the official reader finds one", async () => {
    vi.mocked(createC2pa).mockResolvedValue({
      reader: {
        fromBlob: vi.fn().mockResolvedValue({
          json: vi.fn().mockResolvedValue({
            active_manifest: "m1",
            manifests: { m1: { claim_generator: "Adobe Firefly" } },
          }),
          free: vi.fn().mockResolvedValue(undefined),
        }),
      },
    } as unknown as Awaited<ReturnType<typeof createC2pa>>);
    vi.spyOn(fetchClient, "POST").mockResolvedValue(ok({ matches: [] }) as unknown as PostResult);

    const { container } = renderWithClient(<ComparisonPanel />);
    selectFile(container);

    expect(await screen.findByText("Embedded manifest found")).toBeTruthy();
    expect(await screen.findByText(/Adobe Firefly/)).toBeTruthy();
  });
});
