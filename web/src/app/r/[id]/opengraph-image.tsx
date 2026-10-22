import { ImageResponse } from "next/og";

import { decodeManifestId, lookupManifest, receiptFacts } from "@/lib/receipt-manifest";

// The social-card image for a shared receipt link, /r/<manifestId>. At request time it looks up the
// manifest from the live SBR API (absolute URL, short timeout, never throws) and renders a branded
// card. When the manifest exists it shows a green VERIFIED badge plus the recovered model and the
// match score; when it does not (or the API is slow), it shows a neutral provenance-receipt card with
// no false VERIFIED. The VERIFIED state and the model come from real API data, never hardcoded.

export const runtime = "nodejs";
export const alt = "Veridex provenance receipt";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const BG = "#05060a";
const EMERALD = "#34d399";
const MUTED = "rgba(255,255,255,0.6)";
const FAINT = "rgba(255,255,255,0.4)";

export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const manifestId = decodeManifestId(id);
  const lookup = await lookupManifest(id);
  const facts = lookup.status === "found" ? receiptFacts(lookup.manifest) : null;
  const verified = facts !== null;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: BG,
          color: "#ffffff",
          padding: 72,
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <div style={{ display: "flex", width: 16, height: 16, borderRadius: 16, background: EMERALD }} />
            <span style={{ fontSize: 34, fontWeight: 700, letterSpacing: 0.5 }}>Veridex</span>
          </div>
          <span style={{ fontSize: 20, color: FAINT, letterSpacing: 4, textTransform: "uppercase" }}>
            open C2PA recovery
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <span style={{ fontSize: 22, color: EMERALD, letterSpacing: 8, textTransform: "uppercase" }}>
            Provenance receipt
          </span>
          <span style={{ fontSize: 44, fontWeight: 600, lineHeight: 1.1, wordBreak: "break-all" }}>
            {manifestId}
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
            {verified ? (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "12px 26px",
                  borderRadius: 999,
                  background: "rgba(52,211,153,0.12)",
                  border: `1px solid ${EMERALD}`,
                  color: EMERALD,
                  fontSize: 28,
                  fontWeight: 600,
                }}
              >
                <span>VERIFIED</span>
              </div>
            ) : (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  padding: "12px 26px",
                  borderRadius: 999,
                  border: "1px solid rgba(255,255,255,0.18)",
                  color: MUTED,
                  fontSize: 28,
                  fontWeight: 600,
                }}
              >
                <span>Provenance receipt</span>
              </div>
            )}
            <span style={{ fontSize: 24, color: MUTED }}>
              {verified
                ? facts?.watermark
                  ? "watermark match 100 / 100"
                  : "recovered and signed"
                : "No record in this registry yet"}
            </span>
          </div>

          {verified && (facts?.model || facts?.provider) ? (
            <div style={{ display: "flex", gap: 56 }}>
              {facts?.model ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <span style={{ fontSize: 18, color: FAINT, letterSpacing: 3, textTransform: "uppercase" }}>
                    model
                  </span>
                  <span style={{ fontSize: 28 }}>{facts.model}</span>
                </div>
              ) : null}
              {facts?.provider ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <span style={{ fontSize: 18, color: FAINT, letterSpacing: 3, textTransform: "uppercase" }}>
                    provider
                  </span>
                  <span style={{ fontSize: 28 }}>{facts.provider}</span>
                </div>
              ) : null}
            </div>
          ) : null}

          <span style={{ fontSize: 20, color: FAINT }}>Provenance proves origin, not truth.</span>
        </div>
      </div>
    ),
    { ...size },
  );
}
