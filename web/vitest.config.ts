import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Component tests run in jsdom via Vitest. The @ alias mirrors tsconfig's paths so tests import the
// same way the app does. The R3F/WebGL and c2pa-web (WASM) surfaces are not unit-tested here (they
// are covered by the live demo and the Playwright run); these cover the 2D recovery + storage UI.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // The typed client builds a Request() internally; Node/undici cannot parse a relative URL the
    // way a browser can, so point the client at an absolute base in tests (the fetch is mocked, so
    // nothing actually hits the network).
    env: { NEXT_PUBLIC_API_BASE_URL: "http://localhost/api" },
  },
});
