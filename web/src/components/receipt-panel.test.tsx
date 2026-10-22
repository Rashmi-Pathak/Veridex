import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { ReceiptPanel } from "@/components/receipt-panel";

function mockFetch(body: unknown, status = 200): void {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
}

// A live-shaped C2PA SBR 2.4 verifiedManifestReceipt (the fields the panel reads).
const RECEIPT = {
  "@context": {
    c2pa: "https://c2pa.org/ns/",
    receipt: "https://c2pa.org/ns/manifest-receipt#",
  },
  "@type": "org.c2pa.manifest-receipt",
  repository: {
    uri: "https://veridex-api.example",
    manifestId: "urn:c2pa:demo-0000-0000-0000-000000000001",
  },
  anchor: {
    uri: "https://veridex-api.example/transparency/proof/urn%3Ac2pa%3Ademo",
    parameters: { epoch: 13 },
    proof: {
      alg: "sha256",
      manifestId: "urn:c2pa:demo-0000-0000-0000-000000000001",
      leafIndex: 0,
      leafHash: "1e58030da5d9dd029875e490768da7938032dd3394b5a4027f1d95917c7f0430",
      treeSize: 13,
      rootHash: "f5ae7969d0e6e7ef855cd294ba11b2bdfa99285c2d0a715b5c193c02f7125da7",
      proof: { metadata: { algorithm: "sha256", size: 13 }, path: [] },
      checkpoint: {
        epoch: 13,
        treeSize: 13,
        rootHash: "f5ae7969d0e6e7ef855cd294ba11b2bdfa99285c2d0a715b5c193c02f7125da7",
        signedAt: "2026-07-01T19:54:44.420152+00:00",
        signatureB64: "0NLFxQwX",
      },
      publicKeyHex: "b1d184a5a5bc6de34de2eef791d15fffb0b585650fa20331ca61722e7321fe16",
      keySource: "configured",
      serverVerified: true,
    },
  },
  verified: true,
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ReceiptPanel", () => {
  it("shows the VERIFIED badge and proof fields from the live receipt", async () => {
    mockFetch(RECEIPT);

    render(<ReceiptPanel />);

    // VERIFIED comes from the real `verified` boolean, not a hardcoded string.
    expect(await screen.findByText("✓ VERIFIED")).toBeTruthy();
    // A proof field renders (composed string, unique vs the raw JSON dump).
    expect(screen.getByText("leaf 0 of 13")).toBeTruthy();
    // The anchor renders as a link to the transparency proof.
    const anchor = screen.getByRole("link", { name: /transparency\/proof/ });
    expect(anchor.getAttribute("href")).toBe(RECEIPT.anchor.uri);
    // The collapsible raw receipt JSON is present for inspection.
    expect(screen.getByText("raw receipt JSON")).toBeTruthy();
  });

  it("shows the not-verified state with the error text when verified is false", async () => {
    mockFetch({
      ...RECEIPT,
      verified: false,
      error: "inclusion proof does not recompute to the signed root",
      anchor: {
        ...RECEIPT.anchor,
        proof: { ...RECEIPT.anchor.proof, serverVerified: false },
      },
    });

    render(<ReceiptPanel />);

    expect(await screen.findByText("✗ NOT VERIFIED")).toBeTruthy();
    expect(
      screen.getByText("Not verified: inclusion proof does not recompute to the signed root"),
    ).toBeTruthy();
    expect(screen.queryByText("✓ VERIFIED")).toBeNull();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);

    render(<ReceiptPanel />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });

  it("degrades (no crash) when the log is empty and the proof is empty", async () => {
    // The empty-log fallback returns verified=false, an error, and an EMPTY proof object ({}).
    // Dereferencing proof.rootHash would throw; the panel must render the error state instead.
    mockFetch({
      "@context": RECEIPT["@context"],
      "@type": RECEIPT["@type"],
      repository: { uri: "https://veridex-api.example", manifestId: "" },
      anchor: {
        uri: "https://veridex-api.example/transparency/log",
        parameters: {},
        proof: {},
      },
      verified: false,
      error: "no manifest is available in the transparency log yet",
    });

    render(<ReceiptPanel />);

    expect(
      await screen.findByText("no manifest is available in the transparency log yet"),
    ).toBeTruthy();
    expect(screen.queryByText(/leaf/)).toBeNull();
  });
});
