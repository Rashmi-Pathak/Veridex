import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ByoUploadPanel } from "@/components/byo-upload-panel";

// The three calls in the loop are distinguishable by URL: the presign and register routes are
// same-origin API paths, and the PUT goes to the presigned B2 URL. The mock routes per URL so each
// test controls exactly one step, and the stage tracker is asserted against the real responses.
const PRESIGN = {
  uploadUrl:
    "https://s3.us-west-004.backblazeb2.com/rooted-dev/byo/0123456789abcdef0123456789abcdef.png?X-Amz-Signature=sig",
  objectKey: "byo/0123456789abcdef0123456789abcdef.png",
  bucket: "rooted-dev",
  contentType: "image/png",
  expiresInSeconds: 600,
  maxBytes: 26214400,
};

const REGISTERED = {
  manifestId: "urn:c2pa:b2-deadbeefdeadbeef",
  objectKey: PRESIGN.objectKey,
  bucket: "rooted-dev",
  backend: "backblaze-b2",
  sizeBytes: 3,
  assetSha256: "aa11bb22cc33dd44ee55ff66aa11bb22cc33dd44ee55ff66aa11bb22cc33dd44",
  alreadyRegistered: false,
  recoverable: true,
  note: "registered: the asset is fingerprinted, appended to the transparency log, and recoverable via /matches/byContent",
};

function jsonRes(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

type FetchMock = ReturnType<typeof vi.fn>;

function mockRoutes(
  routes: (url: string, init?: RequestInit) => Response | Promise<Response>,
): FetchMock {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
    routes(String(input), init),
  );
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
}

function selectFile(container: HTMLElement, file: File): void {
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ByoUploadPanel", () => {
  it("rejects a disallowed type client-side without any request", async () => {
    const mock = mockRoutes(() => jsonRes({}));

    const { container } = render(<ByoUploadPanel />);
    selectFile(container, new File(["gif"], "a.gif", { type: "image/gif" }));

    expect(await screen.findByText(/Unsupported type "image\/gif"/)).toBeTruthy();
    expect(mock).not.toHaveBeenCalled();
    // No stage ran or failed; the tracker stays pending.
    expect(screen.queryByText("✗ failed")).toBeNull();
    expect(screen.queryByText("✓ done")).toBeNull();
  });

  it("runs presign, direct PUT to B2, and register, then shows the manifest and receipt link", async () => {
    const mock = mockRoutes((url) => {
      if (url === "/api/demo/byo/upload-url") return jsonRes(PRESIGN);
      if (url === PRESIGN.uploadUrl) return new Response(null, { status: 200 });
      if (url === "/api/demo/byo/register") return jsonRes(REGISTERED);
      throw new Error(`unexpected fetch: ${url}`);
    });

    const file = new File(["png"], "mine.png", { type: "image/png" });
    const { container } = render(<ByoUploadPanel />);
    selectFile(container, file);

    expect(await screen.findByText("✓ REGISTERED")).toBeTruthy();

    // 1. presign is called with the declared type and exact size.
    const [presignUrl, presignInit] = mock.mock.calls[0] as [string, RequestInit];
    expect(presignUrl).toBe("/api/demo/byo/upload-url");
    expect(presignInit.method).toBe("POST");
    expect(JSON.parse(presignInit.body as string)).toEqual({
      contentType: "image/png",
      sizeBytes: file.size,
    });

    // 2. the PUT goes to the presigned B2 URL with the exact Content-Type header.
    const [putUrl, putInit] = mock.mock.calls[1] as [string, RequestInit];
    expect(putUrl).toBe(PRESIGN.uploadUrl);
    expect(putInit.method).toBe("PUT");
    expect((putInit.headers as Record<string, string>)["Content-Type"]).toBe("image/png");

    // 3. register is called with the objectKey from the presign response.
    const [registerUrl, registerInit] = mock.mock.calls[2] as [string, RequestInit];
    expect(registerUrl).toBe("/api/demo/byo/register");
    expect(JSON.parse(registerInit.body as string)).toEqual({ objectKey: PRESIGN.objectKey });

    // The success block shows the live manifestId and links to the receipt permalink.
    expect(screen.getByText(REGISTERED.manifestId)).toBeTruthy();
    const link = screen.getByRole("link", { name: /provenance receipt/ });
    expect(link.getAttribute("href")).toBe(`/r/${encodeURIComponent(REGISTERED.manifestId)}`);
    // All three stages flipped to done on real responses.
    expect(screen.getAllByText("✓ done")).toHaveLength(3);
    expect(screen.getByText(/transparency log explorer below/)).toBeTruthy();
  });

  it("shows the honest CORS message when the direct PUT to B2 fails on the network", async () => {
    const mock = mockRoutes((url) => {
      if (url === "/api/demo/byo/upload-url") return jsonRes(PRESIGN);
      if (url === PRESIGN.uploadUrl) throw new TypeError("Failed to fetch");
      throw new Error(`unexpected fetch: ${url}`);
    });

    const { container } = render(<ByoUploadPanel />);
    selectFile(container, new File(["png"], "mine.png", { type: "image/png" }));

    expect(
      await screen.findByText(/blocked in the browser.*registration flow are unaffected/),
    ).toBeTruthy();
    // Stage 1 completed for real, stage 2 failed, and register was never attempted.
    expect(screen.getAllByText("✓ done")).toHaveLength(1);
    expect(screen.getByText("✗ failed")).toBeTruthy();
    expect(mock).toHaveBeenCalledTimes(2);
  });

  it("shows the not-configured detail when the presign route returns 503", async () => {
    const mock = mockRoutes((url) => {
      if (url === "/api/demo/byo/upload-url")
        return jsonRes({ detail: "BYO upload is not configured: B2 credentials are unset" }, 503);
      throw new Error(`unexpected fetch: ${url}`);
    });

    const { container } = render(<ByoUploadPanel />);
    selectFile(container, new File(["png"], "mine.png", { type: "image/png" }));

    expect(
      await screen.findByText("BYO upload is not configured: B2 credentials are unset"),
    ).toBeTruthy();
    expect(screen.getByText("✗ failed")).toBeTruthy();
    expect(mock).toHaveBeenCalledTimes(1);
  });
});
