import type { ReactElement } from "react";

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { fetchClient } from "@/lib/api/client";
import { ProvidersPanel } from "@/components/providers-panel";

// The provider list and the per-tile image bytes are raw fetches (not in the typed schema), so they
// are stubbed on global fetch. The strip + recover step uses the typed client, whose openapi-fetch
// builds a FormData Request that jsdom cannot construct, so fetchClient.POST/GET are stubbed exactly
// as recover-panel.test does. Real TanStack Query and the component's state -> UI mapping are
// exercised throughout.
type PostResult = Awaited<ReturnType<typeof fetchClient.POST>>;
type GetResult = Awaited<ReturnType<typeof fetchClient.GET>>;

const PROVIDERS = [
  {
    slug: "nano-banana",
    label: "Nano Banana 2",
    model: "nano-banana-2",
    provider: "kie.ai-nano-banana",
    prompt: "a glowing bioluminescent oak tree",
    manifestId: "urn:c2pa:demo-provider-nano-banana-000000000001",
  },
  {
    slug: "flux",
    label: "Flux 2 Pro",
    model: "flux-2/pro-text-to-image",
    provider: "kie.ai-flux",
    prompt: "an ancient oak tree",
    manifestId: "urn:c2pa:demo-provider-flux-000000000001",
  },
  {
    slug: "qwen",
    label: "Qwen Image",
    model: "qwen/text-to-image",
    provider: "kie.ai-qwen",
    prompt: "a lone tree of light",
    manifestId: "urn:c2pa:demo-provider-qwen-000000000001",
  },
];

function ok<T>(data: T): { data: T; error: undefined; response: Response } {
  return { data, error: undefined, response: new Response() };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

// Stub the raw fetches: /api/demo/providers returns the list, /api/demo/provider/{slug} returns bytes.
function stubFetch(providersResponse: Response): void {
  globalThis.fetch = vi.fn(async (url: unknown) => {
    const u = String(url);
    if (u.includes("/api/demo/providers")) return providersResponse;
    if (u.includes("/api/demo/provider/")) {
      // A string body (not a jsdom Blob) so undici's Response.blob() can stream it in this test env.
      return new Response("imagebytes", {
        status: 200,
        headers: { "content-type": "image/jpeg" },
      });
    }
    return jsonResponse({}, 404);
  }) as unknown as typeof fetch;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ProvidersPanel", () => {
  it("renders a tile per provider with its label, model, and provider", async () => {
    stubFetch(jsonResponse(PROVIDERS));
    renderWithClient(<ProvidersPanel />);

    expect(await screen.findByText("Nano Banana 2")).toBeTruthy();
    expect(screen.getByText("Flux 2 Pro")).toBeTruthy();
    expect(screen.getByText("Qwen Image")).toBeTruthy();

    // each tile shows its model id
    expect(screen.getByText("nano-banana-2")).toBeTruthy();
    expect(screen.getByText("flux-2/pro-text-to-image")).toBeTruthy();
    expect(screen.getByText("qwen/text-to-image")).toBeTruthy();
  });

  it("shows an error when the provider list cannot be loaded", async () => {
    stubFetch(jsonResponse("", 500));
    renderWithClient(<ProvidersPanel />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });

  it("recovers a provider asset to VERIFIED with the recovered model and provider", async () => {
    stubFetch(jsonResponse(PROVIDERS));
    // The strip falls back to the original bytes in jsdom (no real canvas), so the recover round-trip
    // still runs; the typed client is stubbed at the network boundary.
    vi.spyOn(fetchClient, "POST").mockResolvedValue(
      ok({
        matches: [
          { manifestId: "urn:c2pa:demo-provider-nano-banana-000000000001", similarityScore: 100 },
        ],
      }) as unknown as PostResult,
    );
    vi.spyOn(fetchClient, "GET").mockResolvedValue(
      ok({
        manifestId: "urn:c2pa:demo-provider-nano-banana-000000000001",
        assetSha256: "deadbeef",
        createdAt: "2026-06-28T00:00:00Z",
        systemProvenance: { model: "nano-banana-2", provider: "kie.ai-nano-banana" },
        softBindings: [],
      }) as unknown as GetResult,
    );

    renderWithClient(<ProvidersPanel />);

    // recover the first tile (Nano Banana)
    const buttons = await screen.findAllByText("Recover");
    fireEvent.click(buttons[0]);

    expect(await screen.findByText("VERIFIED", undefined, { timeout: 4000 })).toBeTruthy();
    expect(await screen.findByText("100/100", undefined, { timeout: 4000 })).toBeTruthy();
    // the recovered manifest's real system provenance (model + provider) is rendered. These strings
    // also appear in the static tile metadata, so the recovered copy makes them appear twice.
    expect(
      (await screen.findAllByText("nano-banana-2", undefined, { timeout: 4000 })).length,
    ).toBeGreaterThanOrEqual(2);
    expect(
      (await screen.findAllByText("kie.ai-nano-banana", undefined, { timeout: 4000 })).length,
    ).toBeGreaterThanOrEqual(2);
  }, 15000);
});
