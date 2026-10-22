// The default Twitter card reuses the static homepage Open Graph image so a summary_large_image card
// unfurls with the branded card rather than a bare link. runtime is declared locally because Next
// cannot statically read a re-exported route-segment config.
export const runtime = "nodejs";
export { default, alt, size, contentType } from "./opengraph-image";
