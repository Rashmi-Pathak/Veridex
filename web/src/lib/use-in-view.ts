"use client";

import { useCallback, useEffect, useState } from "react";

// Mount a heavy (WebGL) child only once its container scrolls near the viewport, so an off-screen
// canvas does not spin up a GL context and animate while the user is reading elsewhere. Once seen it
// stays mounted (no remount churn). rootMargin pre-mounts it just before it scrolls into view.
//
// The ref is a CALLBACK ref held in state, not useRef, on purpose: the consumers render the gated
// container late (only after their data loads), so the observed node attaches after the first render.
// A useRef would not re-run the effect when the node appears, leaving the observer wired to nothing
// and the child never mounting. Tracking the node in state makes attachment a reactive dependency.
// SSR and browsers without IntersectionObserver fall back to mounting immediately.
export function useInView<T extends Element>(
  rootMargin = "200px",
): [(node: T | null) => void, boolean] {
  const [node, setNode] = useState<T | null>(null);
  const [inView, setInView] = useState(false);
  const ref = useCallback((next: T | null) => setNode(next), []);

  useEffect(() => {
    if (inView || !node) return;
    if (typeof IntersectionObserver === "undefined") {
      setInView(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setInView(true);
      },
      { rootMargin },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [inView, node, rootMargin]);

  return [ref, inView];
}
