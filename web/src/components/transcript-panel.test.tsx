import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { TranscriptPanel } from "@/components/transcript-panel";

function mockFetch(body: unknown, status = 200): void {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
}

const SAMPLE = {
  available: true,
  transcript: "That is verifiable content provenance.",
  wordCount: 6,
  wordTimings: [
    { word: "That", start: 0.1, end: 0.3, confidence: 0.9 },
    { word: "is", start: 0.3, end: 0.4, confidence: 0.9 },
  ],
  language: "en",
  audioDuration: 18,
  sourceAudioUrl: "/demo/speech",
  assetSha256: "a699e1329ddb5488",
  genblaze: {
    available: true,
    runId: "dfd1013f-1098-4f0c-a357-380947ab916e",
    canonicalHash: "226d28ba49d12af6",
    verifyHash: true,
    outputAssetSha256: "a699e1329ddb5488",
    generator: "genblaze",
    storedOnB2: true,
    b2Keys: [
      "genblaze-transcripts/dfd1013f/manifest.json",
      "genblaze-transcripts/dfd1013f/transcript.txt",
    ],
  },
  rooted: {
    manifestId: "urn:c2pa:genblaze-transcript-0000-0000-0000-000000000001",
    assetSha256: "a699e1329ddb5488",
    systemProvenance: { model: "universal-3-pro", provider: "assemblyai", kind: "transcript" },
    signatureValid: true,
    publicKeyHex: "b1d184a5",
  },
  reconciled: true,
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TranscriptPanel", () => {
  it("renders the reconciled transcript with both trust layers", async () => {
    mockFetch(SAMPLE);
    render(<TranscriptPanel />);
    expect(
      await screen.findByText(/reconciled: same transcript, both layers verify/),
    ).toBeTruthy();
    expect(screen.getByText(/verifiable content provenance/)).toBeTruthy();
    expect(screen.getByText(/Genblaze · transcript integrity/)).toBeTruthy();
    expect(screen.getByText(/Veridex · signed/)).toBeTruthy();
    expect(screen.getByText(/assemblyai · universal-3-pro/)).toBeTruthy();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);
    render(<TranscriptPanel />);
    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
