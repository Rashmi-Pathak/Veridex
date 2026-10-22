import { afterEach, describe, expect, it, vi } from "vitest";

import { GET, OPTIONS } from "./route";

// The badge JSON route drives the embeddable seal, so its contract is worth pinning: CORS is open
// (a badge embeds anywhere), verified reflects the live proof's serverVerified and nothing else,
// and the not-found / unknown states never claim verified. The upstream API is stubbed at fetch so
// the test is network-free; the shapes are the live ones this route reads.

function stubFetch(byUrl: (url: string) => Response) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) =>
    byUrl(String(input)),
  ) as unknown as typeof fetch;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const ID = "urn:c2pa:demo-0000-0000-0000-000000000001";
const params = Promise.resolve({ id: encodeURIComponent(ID) });

afterEach(() => vi.restoreAllMocks());

describe("GET /badge/[id]", () => {
  it("returns verified with the live proof facts and open CORS", async () => {
    stubFetch((url) => {
      if (url.includes("/manifests/") && !url.includes("/receipts")) {
        return json({
          manifestId: ID,
          systemProvenance: { model: "seedream-5.0-lite", provider: "gmicloud-image" },
          softBindings: [{ alg: "com.adobe.trustmark.P", value: "DEMO" }],
        });
      }
      if (url.includes("/transparency/proof/")) {
        return json({ leafIndex: 0, treeSize: 15, serverVerified: true });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    const res = await GET(new Request("http://t/badge"), { params });
    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("*");
    const body = await res.json();
    expect(body.status).toBe("found");
    expect(body.verified).toBe(true);
    expect(body.model).toBe("seedream-5.0-lite");
    expect(body.leafIndex).toBe(0);
    expect(body.treeSize).toBe(15);
    expect(body.receiptUrl).toBe(`/r/${encodeURIComponent(ID)}`);
  });

  it("never claims verified when the proof is not server-verified", async () => {
    stubFetch((url) => {
      if (url.includes("/manifests/") && !url.includes("/receipts")) {
        return json({ manifestId: ID, systemProvenance: {}, softBindings: [] });
      }
      return json({ leafIndex: 0, treeSize: 15, serverVerified: false });
    });
    const body = await (await GET(new Request("http://t/badge"), { params })).json();
    expect(body.status).toBe("found");
    expect(body.verified).toBe(false);
  });

  it("reports an honest not-found for an unknown id", async () => {
    stubFetch(() => json({ detail: "manifest not found" }, 404));
    const body = await (await GET(new Request("http://t/badge"), { params })).json();
    expect(body.status).toBe("notfound");
    expect(body.verified).toBe(false);
  });

  it("answers the CORS preflight", () => {
    const res = OPTIONS();
    expect(res.status).toBe(204);
    expect(res.headers.get("Access-Control-Allow-Methods")).toContain("GET");
  });
});
