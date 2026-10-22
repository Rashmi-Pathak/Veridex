import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { RemarkPanel } from "@/components/remark-panel";

function mockFetch(body: unknown, status = 200): void {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
}

// The live production shape: the lean deploy carries no TrustMark model, so the watermark half
// reports attempted:false with an honest note, while the fingerprint recovery is computed live.
const LIVE = {
  available: true,
  staged: true,
  stagedNote:
    "The removal attack is staged live on the demo asset and the fingerprint recovery is computed live on the attacked bytes. This deployment does not carry the TrustMark model (the `watermark` extra), so the watermark half is not run here; that the same attack defeats the real TrustMark decoder is verified by the repository's real-model integration test, not asserted by this response.",
  attack: {
    name: "gaussian blur + JPEG q30 (ReMark-class watermark removal)",
    parameters: { gaussianBlurRadius: 3, jpegQuality: 30 },
    note: "models the ReMark class of watermark-removal attacks (regeneration/diffusion): it destroys the high-frequency invisible-watermark carrier while preserving the low/mid-frequency perceptual structure the fingerprint hashes",
  },
  watermark: {
    attempted: false,
    recovered: false,
    decodedId: null,
    expectedId: "DEMO",
    note: "not run: the TrustMark model is not installed in this deployment. The repository's real-model integration test (test_real_removal_attack_defeats_trustmark_but_fingerprint_survives) verifies this exact attack defeats the real decoder.",
  },
  fingerprint: {
    attempted: true,
    recovered: true,
    hammingDistance: 6,
    threshold: 31,
    matchedManifestId: "urn:c2pa:demo-0000-0000-0000-000000000001",
  },
  verdict:
    "the perceptual fingerprint recovered the manifest under the ReMark-class attack (computed live); the watermark half was not run here because the TrustMark model is not deployed, and is verified by the repository's real-model integration test",
};

// The full-model interesting case: the deploy runs the real TrustMark decoder, the attack destroys
// the watermark (attempted true, recovered false, decodedId null), and the fingerprint survives.
const FULL_MODEL = {
  ...LIVE,
  watermark: {
    attempted: true,
    recovered: false,
    decodedId: null,
    expectedId: "DEMO",
    note: null,
  },
  verdict:
    "recovery survives watermark removal via the perceptual fingerprint: the attack destroyed the watermark but the fingerprint matched the manifest",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RemarkPanel", () => {
  it("renders the live lean-deploy shape: attack card, not-run watermark, fingerprint recovery, verdict, staged box", async () => {
    mockFetch(LIVE);

    render(<RemarkPanel />);

    // The attack card names the attack and its parameters.
    expect(
      await screen.findByText("gaussian blur + JPEG q30 (ReMark-class watermark removal)"),
    ).toBeTruthy();
    expect(screen.getByText("blur radius")).toBeTruthy();
    expect(screen.getByText("JPEG quality")).toBeTruthy();

    // The watermark half is honestly rendered as not run, with the server's note, not as an error.
    expect(screen.getByText("not run in this deployment")).toBeTruthy();
    expect(
      screen.getByText(/test_real_removal_attack_defeats_trustmark_but_fingerprint_survives/),
    ).toBeTruthy();
    expect(screen.queryByText("✗ destroyed")).toBeNull();

    // The fingerprint recovered, with the Hamming distance rendered against the threshold.
    expect(screen.getByText("✓ recovered")).toBeTruthy();
    expect(screen.getByText("6")).toBeTruthy();
    expect(screen.getByText("31")).toBeTruthy();
    expect(screen.getByText("urn:c2pa:demo-0000-0000-0000-000000000001")).toBeTruthy();

    // The verdict sentence comes verbatim from the live response.
    expect(screen.getByText(LIVE.verdict)).toBeTruthy();

    // The staged-demonstration box is always shown when data is present.
    expect(screen.getByText("STAGED DEMONSTRATION")).toBeTruthy();
    expect(screen.getByText(/staged live on the demo asset/)).toBeTruthy();
  });

  it("renders the full-model case: watermark destroyed, fingerprint recovered", async () => {
    mockFetch(FULL_MODEL);

    render(<RemarkPanel />);

    expect(await screen.findByText("✗ destroyed")).toBeTruthy();
    expect(screen.getByText("✓ recovered")).toBeTruthy();
    // The decoded/expected pair renders from the response.
    expect(screen.getByText("(none)")).toBeTruthy();
    expect(screen.getByText("DEMO")).toBeTruthy();
    expect(screen.getByText(FULL_MODEL.verdict)).toBeTruthy();
    expect(screen.queryByText("not run in this deployment")).toBeNull();
  });

  it("renders the honest reason when the demonstration is unavailable", async () => {
    mockFetch({
      available: false,
      staged: true,
      stagedNote: "The removal attack is staged on the demo asset when it is available.",
      reason: "the demo asset is not present in this deployment",
      attack: null,
      watermark: null,
      fingerprint: null,
      verdict: null,
    });

    render(<RemarkPanel />);

    expect(await screen.findByText("the demo asset is not present in this deployment")).toBeTruthy();
    expect(screen.getByText("STAGED DEMONSTRATION")).toBeTruthy();
    expect(screen.queryByText("✓ recovered")).toBeNull();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);

    render(<RemarkPanel />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
