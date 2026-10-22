import { ImageResponse } from "next/og";

// The default social card for the app, used wherever a more specific image is not generated. A static
// branded card: the Veridex wordmark and the one-line thesis over the cosmic background.

export const runtime = "nodejs";
export const alt = "Veridex: recover stripped C2PA provenance";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const BG = "#05060a";
const EMERALD = "#34d399";
const FAINT = "rgba(255,255,255,0.4)";

export default function Image() {
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
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", width: 18, height: 18, borderRadius: 18, background: EMERALD }} />
          <span style={{ fontSize: 36, fontWeight: 700, letterSpacing: 0.5 }}>Veridex</span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <span style={{ fontSize: 22, color: EMERALD, letterSpacing: 8, textTransform: "uppercase" }}>
            open C2PA recovery
          </span>
          <span style={{ fontSize: 64, fontWeight: 600, lineHeight: 1.05 }}>
            Recover stripped C2PA provenance.
          </span>
          <span style={{ fontSize: 28, color: "rgba(255,255,255,0.6)", lineHeight: 1.35, maxWidth: 900 }}>
            A vendor-neutral C2PA Soft Binding Resolution server on Backblaze B2, with a tamper-evident
            transparency-log proof.
          </span>
        </div>

        <span style={{ fontSize: 22, color: FAINT }}>Provenance proves origin, not truth.</span>
      </div>
    ),
    { ...size },
  );
}
