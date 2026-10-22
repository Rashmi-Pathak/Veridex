import type { ReactElement } from "react";

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { fetchClient } from "@/lib/api/client";
import { RecoverPanel } from "@/components/recover-panel";

// Stub the typed client at the network boundary (not the component's logic). openapi-fetch builds a
// Request with a FormData body, which jsdom + undici cannot construct; stubbing fetchClient.POST/GET
// keeps real TanStack Query and openapi-react-query while exercising the component's state -> UI map.
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
  const file = new File(["x"], "a.png", { type: "image/png" });
  fireEvent.change(input, { target: { files: [file] } });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RecoverPanel", () => {
  it("reveals VERIFIED with the recovered manifest on a match", async () => {
    vi.spyOn(fetchClient, "POST").mockResolvedValue(
      ok({ matches: [{ manifestId: "urn:c2pa:demo", similarityScore: 100 }] }) as unknown as PostResult,
    );
    vi.spyOn(fetchClient, "GET").mockResolvedValue(
      ok({
        manifestId: "urn:c2pa:demo",
        assetSha256: "deadbeef",
        createdAt: "2026-06-27T00:00:00Z",
        systemProvenance: { model: "seedream-5.0-lite" },
        softBindings: [{ alg: "com.adobe.trustmark.P", value: "DEMO" }],
      }) as unknown as GetResult,
    );

    const { container } = renderWithClient(<RecoverPanel />);
    selectFile(container);

    expect(await screen.findByText("VERIFIED")).toBeTruthy();
    // the recovered manifest's real system provenance is rendered
    expect(await screen.findByText(/seedream-5.0-lite/)).toBeTruthy();
  });

  it("shows FAILED when no manifest matches", async () => {
    vi.spyOn(fetchClient, "POST").mockResolvedValue(ok({ matches: [] }) as unknown as PostResult);

    const { container } = renderWithClient(<RecoverPanel />);
    selectFile(container);

    expect(await screen.findByText("FAILED")).toBeTruthy();
  });

  it("shows the error state when the backend errors", async () => {
    vi.spyOn(fetchClient, "POST").mockResolvedValue({
      data: undefined,
      error: { detail: "boom" },
      response: new Response(null, { status: 500 }),
    } as unknown as PostResult);

    const { container } = renderWithClient(<RecoverPanel />);
    selectFile(container);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
