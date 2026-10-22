import type { ReactElement } from "react";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { fetchClient } from "@/lib/api/client";
import { GeneratePanel } from "@/components/generate-panel";

// Two boundaries are stubbed. /api/demo/generate is a raw fetch (the endpoint is intentionally not in
// the typed schema, like /api/demo/sample), so it is stubbed on global fetch. The strip + recover
// step uses the typed client, whose openapi-fetch builds a FormData Request that jsdom cannot
// construct, so fetchClient.POST/GET are stubbed exactly as recover-panel.test does. Real TanStack
// Query and the component's state -> UI mapping are exercised throughout.
type PostResult = Awaited<ReturnType<typeof fetchClient.POST>>;
type GetResult = Awaited<ReturnType<typeof fetchClient.GET>>;

// A 1x1 PNG, enough for the component to render an <img> and for the in-browser strip fallback.
const TINY_IMAGE =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

const GENERATE_OK = {
  image: TINY_IMAGE,
  manifestId: "urn:c2pa:generated-1",
  watermarkId: "L1a2b3c4d",
  merkleIndex: 7,
  model: "seedream-5.0-lite",
  provider: "gmicloud-image",
  signatureB64: "sig",
  manifest: {
    manifestId: "urn:c2pa:generated-1",
    assetSha256: "deadbeef",
    createdAt: "2026-06-28T00:00:00Z",
    systemProvenance: { model: "seedream-5.0-lite", provider: "gmicloud-image", generator: "genblaze" },
    softBindings: [{ alg: "com.adobe.trustmark.P", value: "L1a2b3c4d" }],
  },
  storedOnB2: true,
  fellBackToSeed: false,
  reason: null,
};

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

// Stub /api/demo/generate (raw fetch). The `body` argument lets a test return a non-200.
function stubGenerate(response: Response): void {
  globalThis.fetch = vi.fn(async (url: unknown) => {
    const u = String(url);
    if (u.includes("/api/demo/generate")) return response;
    return jsonResponse({}, 404);
  }) as unknown as typeof fetch;
}

function typePromptAndGenerate(): void {
  const textarea = screen.getByPlaceholderText(/lighthouse/i);
  fireEvent.change(textarea, { target: { value: "a calm harbor at dawn" } });
  fireEvent.click(screen.getByText("Generate"));
}

afterEach(() => {
  vi.restoreAllMocks();
});

beforeEach(() => {
  stubGenerate(jsonResponse(GENERATE_OK));
});

describe("GeneratePanel", () => {
  it("renders the credentialed image and Registered block after Generate", async () => {
    renderWithClient(<GeneratePanel />);
    typePromptAndGenerate();

    expect(await screen.findByText("Registered")).toBeTruthy();
    const img = (await screen.findByAltText("Generated, credentialed asset")) as HTMLImageElement;
    expect(img.getAttribute("src")).toBe(TINY_IMAGE);
    // the registered details are driven by the real generate response
    expect(screen.getByText(/leaf #7/)).toBeTruthy();
    expect(screen.getByText(/seedream-5.0-lite \(gmicloud-image\)/)).toBeTruthy();
  });

  it("strips, then reveals VERIFIED with the recovered manifest and similarity", async () => {
    vi.spyOn(fetchClient, "POST").mockResolvedValue(
      ok({
        matches: [{ manifestId: "urn:c2pa:generated-1", similarityScore: 100 }],
      }) as unknown as PostResult,
    );
    vi.spyOn(fetchClient, "GET").mockResolvedValue(
      ok({
        manifestId: "urn:c2pa:generated-1",
        assetSha256: "deadbeef",
        createdAt: "2026-06-28T00:00:00Z",
        systemProvenance: { model: "seedream-5.0-lite" },
        softBindings: [{ alg: "com.adobe.trustmark.P", value: "L1a2b3c4d" }],
      }) as unknown as GetResult,
    );

    renderWithClient(<GeneratePanel />);
    typePromptAndGenerate();

    fireEvent.click(await screen.findByText("Strip and recover"));

    expect(await screen.findByText("VERIFIED")).toBeTruthy();
    // the recovered manifest id is shown in the Registered block and again in the VERIFIED block
    expect((await screen.findAllByText("urn:c2pa:generated-1")).length).toBeGreaterThanOrEqual(1);
    expect(await screen.findByText("100/100 (fingerprint)")).toBeTruthy();
  });

  it("shows an honest amber note with the backend detail on a 429 cap", async () => {
    stubGenerate(jsonResponse({ detail: "Daily generation cap reached. Try the recover step." }, 429));

    renderWithClient(<GeneratePanel />);
    typePromptAndGenerate();

    expect(await screen.findByText(/Daily generation cap reached/)).toBeTruthy();
  });

  it("flags a seeded fallback with the reason instead of pretending it was fresh", async () => {
    stubGenerate(jsonResponse({ ...GENERATE_OK, fellBackToSeed: true, reason: "generator out of credits" }));

    renderWithClient(<GeneratePanel />);
    typePromptAndGenerate();

    expect(await screen.findByText(/Showing the seeded demo asset: generator out of credits/)).toBeTruthy();
  });
});
