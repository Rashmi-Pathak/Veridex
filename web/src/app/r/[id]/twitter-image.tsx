// The Twitter card for a shared receipt link reuses the dynamic Open Graph image (same branded card,
// real API data, 1200x630). Re-exporting keeps a single source of truth for the receipt social card.
// runtime is declared locally because Next cannot statically read a re-exported route-segment config.
export const runtime = "nodejs";
export { default, alt, size, contentType } from "./opengraph-image";
