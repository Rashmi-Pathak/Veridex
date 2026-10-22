import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { Hero } from "@/components/hero";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Hero", () => {
  it("renders the thesis headline, eyebrow, and the live ribbon", () => {
    // Hero mounts MetricsRibbon, which fetches /api/status; stub it so the test has no live call.
    globalThis.fetch = vi.fn(
      async () => new Response("{}", { status: 500 }),
    ) as unknown as typeof fetch;

    render(<Hero />);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain(
      "Recover stripped C2PA provenance",
    );
    expect(screen.getByText(/open C2PA recovery/)).toBeTruthy();
    expect(screen.getByText("live")).toBeTruthy();
  });
});
