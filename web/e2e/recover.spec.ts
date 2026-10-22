import { expect, test } from "@playwright/test";

// The headline judge-facing flow, end to end against the live stack: open the site, recover the
// seeded demo asset, and confirm it resolves to VERIFIED with the recovered manifest's real
// generation model. This exercises the front end, the /api proxy, and the SBR recovery together.
test("recovers the demo asset to VERIFIED", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /recover the demo asset/i }).click();
  await expect(page.getByText("VERIFIED")).toBeVisible();
  // the recovered manifest names the real Genblaze generation model
  await expect(page.getByText(/seedream-5\.0-lite/)).toBeVisible();
});

// The Backblaze B2 storage panel reflects where the demo asset lives.
test("shows the Backblaze B2 storage panel", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Backblaze B2 storage/i })).toBeVisible();
});
