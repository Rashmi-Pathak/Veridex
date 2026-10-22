import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Unmount React trees between tests so they do not leak into each other.
afterEach(() => {
  cleanup();
});

// jsdom does not implement matchMedia; Motion (motion/react) reads it for reduced-motion detection.
// Provide a no-op stub so rendering motion components in tests does not throw.
if (typeof window !== "undefined" && !window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}
