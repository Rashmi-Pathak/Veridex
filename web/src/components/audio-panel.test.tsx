import type { ReactElement } from "react";

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { fetchClient } from "@/lib/api/client";
import { AudioPanel } from "@/components/audio-panel";

// The demo clip bytes and the recovered manifest GET are stubbed at the network boundary. The raw
// fetches (/demo/audio and /matches/byAudioContent) go through global.fetch; the typed manifest GET
// goes through fetchClient.GET (openapi-react-query wraps it), so it is spied separately. jsdom has no
// real AudioContext, so stripAudio takes its documented fallback and the loop closes deterministically.
const AUDIO_ID = "urn:c2pa:demo-audio-0000-0000-0000-000000000001";

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
    matchBody = { matches: [{ manifestId: AUDIO_ID, similarityScore: 100 }] },
    matchStatus = 200,
  } = opts;

  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = urlOf(input);
    if (url.includes("/demo/audio")) {
      return new Response(new Uint8Array([1, 2, 3, 4]), {
        status: 200,
        headers: { "content-type": "audio/mpeg" },
      });
    }
    if (url.includes("/matches/byAudioContent")) {
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
      manifestId: AUDIO_ID,
      assetSha256: "deadbeef",
      createdAt: "2026-06-28T00:00:00Z",
      systemProvenance: { model: "suno-v5", provider: "kie.ai-suno", generator: "kie.ai" },
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

describe("AudioPanel", () => {
  it("renders the audio player pointed at the demo clip", () => {
    mockFetch();
    const { container } = renderWithClient(<AudioPanel />);

    const player = container.querySelector("audio");
    expect(player).toBeTruthy();
    expect(player?.getAttribute("src")).toBe("/api/demo/audio");
  });

  it("strips, recovers, and reveals VERIFIED with the suno-v5 provenance", async () => {
    mockFetch();
    stubManifest();

    renderWithClient(<AudioPanel />);
    fireEvent.click(screen.getByText("Strip and recover"));

    expect(await screen.findByText("VERIFIED")).toBeTruthy();
    expect(await screen.findByText(new RegExp(AUDIO_ID))).toBeTruthy();
    // the recovered manifest's real system provenance is rendered
    expect(await screen.findByText(/suno-v5/)).toBeTruthy();
    expect(await screen.findByText(/kie\.ai-suno/)).toBeTruthy();
  });

  it("shows FAILED when no manifest matches the audio fingerprint", async () => {
    mockFetch({ matchBody: { matches: [] } });

    renderWithClient(<AudioPanel />);
    fireEvent.click(screen.getByText("Strip and recover"));

    expect(await screen.findByText("FAILED")).toBeTruthy();
  });

  it("shows an honest amber note on a non-2xx recovery response", async () => {
    mockFetch({ matchBody: { detail: "fingerprint index offline" }, matchStatus: 503 });

    renderWithClient(<AudioPanel />);
    fireEvent.click(screen.getByText("Strip and recover"));

    expect(await screen.findByText(/fingerprint index offline/)).toBeTruthy();
  });
});
