"use client";

import type { ReactNode } from "react";

import { useInView } from "@/lib/use-in-view";

// Defer mounting a data panel until it scrolls near the viewport. Every panel fetches on mount, so
// without this the initial page load fires ~20 fetches at once. One of them (/demo/rebuild, which
// rebuilds the recovery index from B2) takes several seconds and saturates the single API instance,
// which 502s the concurrent light requests. Gating the mount gates the fetch, so the page loads only
// what is on screen and each panel fetches as the reader reaches it. A min-height reserves space so
// scroll position stays stable before the panel mounts. SSR / no-IntersectionObserver mount at once.
export function WhenVisible({
  children,
  minHeight = 160,
}: {
  children: ReactNode;
  minHeight?: number;
}) {
  const [ref, inView] = useInView<HTMLDivElement>();
  return (
    <div ref={ref} style={inView ? undefined : { minHeight }}>
      {inView ? children : null}
    </div>
  );
}
