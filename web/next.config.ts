import type { NextConfig } from "next";

// Proxy /api/* to the FastAPI backend so the browser talks to the SBR API same-origin (no CORS).
const rawTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";
const API_PROXY_TARGET = rawTarget.replace(/\/+$/, "");

// Content Security Policy for the whole app. Rooted is a provenance and trust tool, so the
// load-bearing directive is frame-ancestors 'none': no third party may iframe or overlay our
// VERIFIED seal (anti-clickjacking). object-src 'none' kills legacy plugin embeds. This is a
// self-hardening trust tool, so the security headers protect the very claim the product makes.
//
// Why 'unsafe-inline' and 'unsafe-eval' stay in script-src: Next.js App Router ships inline
// bootstrap and hydration scripts, and @contentauth/c2pa-web (the /inline build we use) compiles
// inlined WebAssembly in-process, which needs 'unsafe-eval' (or wasm-unsafe-eval). A nonce or
// middleware CSP would break static optimization and risk the live demo, so we deliberately do not
// attempt one. The real wins here are frame-ancestors 'none', object-src 'none', and the hardening
// headers below, not a locked-down script-src.
//
// Browser network is nearly all same-origin: /api/* is proxied (rewrites below), the c2pa trust
// files and static assets are local, so connect-src 'self' covers them. The API host is added
// explicitly for robustness even though the only cross-origin fetch to it is server-side. The one
// deliberate cross-origin fetch is the BYO panel's presigned PUT direct to the Backblaze B2 S3
// endpoint (the file must not pass through the API), so exactly that host is allowed. worker-src
// allows the blob worker c2pa-web may spawn; img-src allows data: and blob: for generated and
// decoded images.
const CONNECT_API_HOST = API_PROXY_TARGET;
const IOS_INSTALL_URL =
  process.env.IOS_TESTFLIGHT_URL ?? "https://github.com/placeholder-veridex/veridex/tree/main/mobile/ios";
const ANDROID_INSTALL_URL =
  process.env.ANDROID_RELEASE_URL ?? "https://github.com/placeholder-veridex/veridex/releases";

const contentSecurityPolicy = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  `connect-src 'self' ${CONNECT_API_HOST} https://s3.us-east-005.backblazeb2.com`,
  "worker-src 'self' blob:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

// Production HTTP security response headers applied to every route.
const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  // Legacy anti-clickjacking alongside frame-ancestors, for older browsers.
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // Deny the sensor APIs this app never uses.
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), browsing-topics=()",
  },
  // Vercel serves HTTPS only, so force HTTPS for two years including subdomains.
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
];

const nextConfig: NextConfig = {
  // three ships ESM that some bundler paths choke on; transpiling it keeps R3F builds reliable.
  transpilePackages: ["three"],
  async redirects() {
    return [
      { source: "/get/ios", destination: IOS_INSTALL_URL, permanent: false },
      { source: "/get/android", destination: ANDROID_INSTALL_URL, permanent: false },
    ];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_PROXY_TARGET}/:path*` }];
  },
  async headers() {
    return [
      // Security headers on all routes (the proxy below and dynamic routes still pass through).
      { source: "/:path*", headers: securityHeaders },
      {
        // The credentialed C2PA sample is a static, immutable asset (read by c2pa-web and
        // next/image), so cache it hard instead of revalidating on every visit.
        source: "/credentialed-sample.jpg",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
    ];
  },
};

export default nextConfig;
