import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { TamperPanel } from "@/components/tamper-panel";

const ORIG_SHA = "abc123";
const ORIG_MODEL = "seedream-5.0-lite";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// Mock the two endpoints: /demo/signed-manifest serves the signed manifest; /demo/tamper-diff checks
// the signature AND returns the field-level diff vs the authentic registry manifest (a faithful
// stand-in: valid only when the signed fields are unchanged; otherwise it flags the changed field).
function mockApi(): void {
  globalThis.fetch = vi.fn(async (url: unknown, init?: { body?: unknown }) => {
    const u = String(url);
    if (u.includes("/demo/signed-manifest")) {
      return json({
        manifest: {
          manifestId: "urn:c2pa:demo",
          assetSha256: ORIG_SHA,
          createdAt: "2026-06-27T00:00:00Z",
          systemProvenance: { model: ORIG_MODEL },
        },
        signatureB64: "sig",
        publicKeyHex: "a".repeat(64),
      });
    }
    if (u.includes("/demo/tamper-diff")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      const m = body.manifest ?? {};
      const modelChanged = m.systemProvenance?.model !== ORIG_MODEL;
      const shaChanged = m.assetSha256 !== ORIG_SHA;
      const valid = !modelChanged && !shaChanged;
      return json({
        signatureValid: valid,
        tampered: !valid,
        authenticSource: "registry",
        fields: [
          {
            field: "system_provenance.model",
            authentic: ORIG_MODEL,
            submitted: m.systemProvenance?.model ?? "",
            changed: modelChanged,
          },
          {
            field: "asset_sha256",
            authentic: ORIG_SHA,
            submitted: m.assetSha256 ?? "",
            changed: shaChanged,
          },
        ],
      });
    }
    return json({}, 404);
  }) as unknown as typeof fetch;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TamperPanel", () => {
  it("verifies the untouched manifest, then shows TAMPERED + the changed field after an edit", async () => {
    mockApi();
    render(<TamperPanel />);

    // initial auto-verify: VALID
    expect(await screen.findByText(/SIGNATURE VALID/)).toBeTruthy();

    // edit the model (a signed field), then re-verify -> TAMPERED + the forensic diff
    const modelInput = screen.getByDisplayValue(ORIG_MODEL);
    fireEvent.change(modelInput, { target: { value: "evil-model" } });
    fireEvent.click(screen.getByText("Re-verify"));

    expect(await screen.findByText(/TAMPERED/)).toBeTruthy();
    expect(await screen.findByText(/seedream-5.0-lite \(authentic\)/)).toBeTruthy();
    expect(screen.getByText("evil-model")).toBeTruthy();
  });

  it("shows an error, never SIGNATURE VALID, when tamper-diff returns a non-ok response", async () => {
    // A 500 from /demo/tamper-diff must be treated as an error, not parsed into a green verdict.
    globalThis.fetch = vi.fn(async (url: unknown) => {
      const u = String(url);
      if (u.includes("/demo/signed-manifest")) {
        return json({
          manifest: {
            manifestId: "urn:c2pa:demo",
            assetSha256: ORIG_SHA,
            createdAt: "2026-06-27T00:00:00Z",
            systemProvenance: { model: ORIG_MODEL },
          },
          signatureB64: "sig",
          publicKeyHex: "a".repeat(64),
        });
      }
      if (u.includes("/demo/tamper-diff")) {
        return json({ detail: "internal error" }, 500);
      }
      return json({}, 404);
    }) as unknown as typeof fetch;

    render(<TamperPanel />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
    expect(screen.queryByText(/SIGNATURE VALID/)).toBeNull();
  });
});
