import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// The 3D graph uses WebGL via r3f-forcegraph, which jsdom cannot render, so mock it out and exercise
// the panel's data layer (fetch -> transform -> the readable fallback list and badges) instead.
vi.mock("@/components/three/lineage-graph", () => ({
  default: () => null,
}));

import { LineagePanel } from "@/components/lineage-panel";

function mockFetch(body: unknown, status = 200): void {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
}

const SAMPLE = {
  validationState: "Trusted",
  nodes: [
    {
      id: "urn:c2pa:gen",
      title: "AI generation (seedream-5.0-lite)",
      action: "c2pa.created",
      kind: "generation",
      isActive: false,
    },
    {
      id: "urn:c2pa:crop",
      title: "Cropped",
      action: "c2pa.cropped",
      kind: "edit",
      isActive: false,
    },
    {
      id: "urn:c2pa:color",
      title: "Color adjusted",
      action: "c2pa.color_adjustments",
      kind: "edit",
      isActive: false,
    },
    {
      id: "urn:c2pa:comp",
      title: "Composited",
      action: "c2pa.composited",
      kind: "composite",
      isActive: true,
    },
  ],
  edges: [
    { source: "urn:c2pa:gen", target: "urn:c2pa:crop", relationship: "parentOf" },
    { source: "urn:c2pa:gen", target: "urn:c2pa:color", relationship: "parentOf" },
    { source: "urn:c2pa:crop", target: "urn:c2pa:comp", relationship: "parentOf" },
    { source: "urn:c2pa:color", target: "urn:c2pa:comp", relationship: "componentOf" },
  ],
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("LineagePanel", () => {
  it("renders the lineage node titles, the Trusted badge, and the test-only note", async () => {
    mockFetch(SAMPLE);
    render(<LineagePanel />);
    expect(await screen.findByText("AI generation (seedream-5.0-lite)")).toBeTruthy();
    expect(screen.getByText("Composited")).toBeTruthy();
    expect(screen.getByText("Cropped")).toBeTruthy();
    expect(screen.getByText("Color adjusted")).toBeTruthy();
    expect(screen.getByText("Trusted")).toBeTruthy();
    expect(screen.getByText(/FOR TESTING ONLY/)).toBeTruthy();
  });

  it("shows an error when the backend is unreachable", async () => {
    mockFetch("", 500);
    render(<LineagePanel />);
    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
