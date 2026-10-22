import type { ReactElement } from "react";

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { fetchClient } from "@/lib/api/client";
import { VideoPanel } from "@/components/video-panel";

// The demo clip bytes and the recovered manifest GET are stubbed at the network boundary. The raw
// fetches (/demo/video and /matches/byVideoContent) go through global.fetch; the typed manifest GET
// goes through fetchClient.GET (openapi-react-query wraps it), so it is spied separately. jsdom does
// not decode video, so the fetched demo blob is uploaded as-is and the stubbed backend closes the loop
// deterministically.
const VIDEO_ID = "urn:c2pa:demo-video-0000-0000-0000-000000000001";

type GetResult = Awaited<ReturnType<typeof fetchClient.GET>>;

function ok<T>(data: T): { data: T; error: undefined; response: Response } {
  return { data, error: undefined, response: new Response() };
}

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return (input as Request).url;
}

function mockFetch(opts: { matchBody?: unknown; matchStatus?: number } = {}): void {
  const {
    matchBody = { matches: [{ manifestId: VIDEO_ID, similarityScore: 96 }] },
    matchStatus = 200,
  } = opts;

  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = urlOf(input);
    if (url.includes("/demo/video")) {
      return new Response(new Uint8Array([1, 2, 3, 4]), {
        status: 200,
        headers: { "content-type": "video/mp4" },
      });
    }
    if (url.includes("/matches/byVideoContent")) {
      const body = typeof matchBody === "string" ? matchBody : JSON.stringify(matchBody);
      return new Response(body, {
        status: matchStatus,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response("", { status: 404 });
  }) as unknown as typeof fetch;
}

function stubManifest(): void {
  vi.spyOn(fetchClient, "GET").mockResolvedValue(
    ok({
      manifestId: VIDEO_ID,
      assetSha256: "deadbeef",
      createdAt: "2026-06-28T00:00:00Z",
      systemProvenance: { model: "veo3", provider: "kie.ai-veo3", generator: "kie.ai" },
    }) as unknown as GetResult,
  );
}

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("VideoPanel", () => {
  it("renders the video player pointed at the demo clip", () => {
    mockFetch();
    const { container } = renderWithClient(<VideoPanel />);

    const player = container.querySelector("video");
    expect(player).toBeTruthy();
    expect(player?.getAttribute("src")).toBe("/api/demo/video");
  });

  it("recovers the demo clip and reveals VERIFIED with the veo3 provenance", async () => {
    mockFetch();
    stubManifest();

    renderWithClient(<VideoPanel />);
    fireEvent.click(screen.getByText("or recover the demo clip"));

    expect(await screen.findByText("VERIFIED")).toBeTruthy();
    expect(await screen.findByText(new RegExp(VIDEO_ID))).toBeTruthy();
    // the recovered manifest's real system provenance is rendered
    expect(await screen.findByText(/veo3/)).toBeTruthy();
    expect(await screen.findByText(/kie\.ai-veo3/)).toBeTruthy();
  });

  it("shows FAILED when no manifest matches the keyframe fingerprints", async () => {
    mockFetch({ matchBody: { matches: [] } });

    renderWithClient(<VideoPanel />);
    fireEvent.click(screen.getByText("or recover the demo clip"));

    expect(await screen.findByText("FAILED")).toBeTruthy();
  });

  it("shows an honest amber note on a non-2xx recovery response", async () => {
    mockFetch({ matchBody: { detail: "invalid video container" }, matchStatus: 415 });

    renderWithClient(<VideoPanel />);
    fireEvent.click(screen.getByText("or recover the demo clip"));

    expect(await screen.findByText(/invalid video container/)).toBeTruthy();
  });
});
