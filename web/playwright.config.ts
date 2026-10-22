import { defineConfig, devices } from "@playwright/test";

// End-to-end smoke for the recovery flow. It runs against a deployed (or local) base URL, NOT in the
// fast unit CI (a browser download is heavy); it is a manual / demo-day smoke. Point it at another
// target with E2E_BASE_URL (e.g. http://localhost:3000 with the dev server + the API running).
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 30_000 },
  retries: 1,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "https://veridex-web-phi.vercel.app",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
