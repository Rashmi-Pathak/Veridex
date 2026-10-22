"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import { useState, type ReactNode } from "react";

// One QueryClient per browser session, created in state so it is stable across re-renders and not
// shared between requests on the server.
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 60_000, refetchOnWindowFocus: false, retry: 1 },
        },
      }),
  );

  // reducedMotion="user" makes every motion/react animation drop transform/layout motion (keeping
  // opacity) when the OS prefers-reduced-motion is set, covering the DOM panel-reveal transitions
  // that the per-component code does not gate (the WebGL surfaces gate themselves).
  return (
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </QueryClientProvider>
  );
}
