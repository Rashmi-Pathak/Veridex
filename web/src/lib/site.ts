// The production origin, used for absolute metadata URLs: metadataBase, the Open Graph image, robots,
// and the sitemap. Keep this in one place so every absolute link points at the same deployed app.
// Defaults to local development URL, or can be set via NEXT_PUBLIC_SITE_URL / deployed domain.
export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

