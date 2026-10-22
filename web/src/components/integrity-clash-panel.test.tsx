import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { IntegrityClashPanel } from "@/components/integrity-clash-panel";

function mockFetch(body: unknown, status = 200): void {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
}

const STAGED_NOTE =
  "The embedded/claimed provenance is a staged attack-demonstration fixture (a forged " +
  "human-capture claim), not read from a live asset. The recovered registry record and the " +
  "verdict are computed for real.";

// A live-shaped /demo/integrity-clash response (the fields the panel reads).
const CLASH = {
  staged: true,
  stagedNote: STAGED_NOTE,
  available: true,
  manifestId: "urn:c2pa:demo-0000-0000-0000-000000000001",
  recovered: {
    manifestId: "urn:c2pa:demo-0000-0000-0000-000000000001",
    assetSha256: "9b3fb52e3f2f0d7f6a2f6f9a3b1c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e",
    createdAt: "2026-07-01T12:00:00+00:00",
    systemProvenance: {
      model: "nano-banana-2",
      provider: "kie-ai",
      digitalSourceType: "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
    },
    personalProvenance: {},
    softBindings: [{ alg: "com.trustmark.P", value: "demo" }],
  },
  embedded: {
    digitalSourceType: "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture",
    model: "example-dslr-x100",
    provider: "example-camera-vendor",
    assetSha256: "05f2a1c3e5d7b9f00112233445566778899aabbccddeeff00112233445566778",
    claimGenerator: "example-photo-firmware/2.1 (staged fixture)",
  },
  verdict: {
    clash: true,
    contradictions: [
      {
        field: "digital_source_type",
        embedded: "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture",
        recovered:
          "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
        meaning:
          "The embedded manifest claims a real camera capture; the recovered registry record proves AI generation.",
      },
      {
        field: "model",
        embedded: "example-dslr-x100",
        recovered: "nano-banana-2",
        meaning: "The claimed capture device does not match the generating model in the registry.",
      },
    ],
    fieldsCompared: ["digital_source_type", "model", "provider", "asset_sha256"],
  },
  note: "2 contradiction(s) between the embedded claim and the recovered registry record: the embedded provenance is laundered or forged.",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("IntegrityClashPanel", () => {
  it("shows the clash badge, a contradiction row, and the staged label from the live response", async () => {
    mockFetch(CLASH);

    render(<IntegrityClashPanel />);

    // The clash badge comes from the real verdict.clash boolean, not a hardcoded string.
    expect(await screen.findByText("✗ PROVENANCE CLASH")).toBeTruthy();
    // The staged-demonstration label is visible and renders the server's stagedNote verbatim.
    expect(screen.getByText("STAGED DEMONSTRATION")).toBeTruthy();
    expect(screen.getByText(STAGED_NOTE)).toBeTruthy();
    // A contradiction row: field name, embedded value struck vs recovered value, and the meaning.
    expect(screen.getByText("digital_source_type")).toBeTruthy();
    expect(
      screen.getByText(
        "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture (embedded claim)",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia (recovered record)",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "The embedded manifest claims a real camera capture; the recovered registry record proves AI generation.",
      ),
    ).toBeTruthy();
    // The server's note line renders.
    expect(screen.getByText(CLASH.note)).toBeTruthy();
    // The side-by-side summary: embedded claimGenerator and the shortened digitalSourceType,
    // recovered model and manifestId.
    expect(screen.getByText("example-photo-firmware/2.1 (staged fixture)")).toBeTruthy();
    expect(screen.getByText("digitalCapture")).toBeTruthy();
    expect(screen.getByText("nano-banana-2")).toBeTruthy();
    expect(screen.getByText("urn:c2pa:demo-0000-0000-0000-000000000001")).toBeTruthy();
  });

  it("shows the agreement badge when the layers do not clash", async () => {
    mockFetch({
      ...CLASH,
      verdict: { clash: false, contradictions: [], fieldsCompared: CLASH.verdict.fieldsCompared },
      note: "The embedded claim and the recovered registry record agree on every compared field.",
    });

    render(<IntegrityClashPanel />);

    expect(await screen.findByText("✓ LAYERS AGREE")).toBeTruthy();
    expect(
      screen.getByText(
        "The embedded claim and the recovered registry record agree on every compared field.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("✗ PROVENANCE CLASH")).toBeNull();
    // The staged label is still visible.
    expect(screen.getByText("STAGED DEMONSTRATION")).toBeTruthy();
  });

  it("shows the honest empty state when the demonstration is unavailable", async () => {
    mockFetch({
      staged: true,
      stagedNote: STAGED_NOTE,
      available: false,
      manifestId: null,
      recovered: null,
      embedded: null,
      verdict: null,
      note: "No demo manifest is registered yet; the integrity-clash demonstration is unavailable.",
    });

    render(<IntegrityClashPanel />);

    expect(
      await screen.findByText(
        "No demo manifest is registered yet; the integrity-clash demonstration is unavailable.",
      ),
    ).toBeTruthy();
    // The staged label still renders; no verdict badge does.
    expect(screen.getByText("STAGED DEMONSTRATION")).toBeTruthy();
    expect(screen.queryByText("✗ PROVENANCE CLASH")).toBeNull();
    expect(screen.queryByText("✓ LAYERS AGREE")).toBeNull();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);

    render(<IntegrityClashPanel />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
