import type { MetadataRoute } from "next";

// The web app manifest makes Veridex installable from the browser (Add to Home Screen on any
// phone, Install on desktop): the zero-friction mobile surface that needs no store account.
// Colors match the rooted-sky backdrop; the icons carry the emerald shield.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Veridex: C2PA provenance recovery",
    short_name: "Veridex",
    description:
      "Recover stripped C2PA provenance for AI-generated media, with a tamper-evident transparency-log proof.",
    start_url: "/",
    display: "standalone",
    background_color: "#060a09",
    theme_color: "#060a09",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
