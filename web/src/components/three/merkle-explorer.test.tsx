import type { ReactElement } from "react";

import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// The 3D graph is WebGL (r3f-forcegraph), which jsdom cannot render, so mock it with a probe that
// records which node ids the explorer asked to highlight. The live-update logic under test (poll,
// growth detection, pulse, indicator) all lives in the explorer and its hook, not in the graph.
vi.mock("@/components/three/merkle-graph", () => ({
  default: ({ highlightIds }: { highlightIds?: ReadonlySet<string> | null }) => (
    <div data-testid="merkle-graph" data-highlights={[...(highlightIds ?? [])].join(" ")} />
  ),
}));

// Mock the reduced-motion preference so both motion paths are testable.
vi.mock("@/lib/use-reduced-motion-pref", () => ({
  usePrefersReducedMotion: vi.fn(() => false),
}));

import { fetchClient } from "@/lib/api/client";
import { usePrefersReducedMotion } from "@/lib/use-reduced-motion-pref";
import { MerkleExplorer } from "@/components/three/merkle-explorer";

type GetResult = Awaited<ReturnType<typeof fetchClient.GET>>;

function ok<T>(data: T): { data: T; error: undefined; response: Response } {
  return { data, error: undefined, response: new Response() };
}

// A live-shaped /transparency/log response for a tree of the given size.
function logResponse(treeSize: number) {
  return {
    entries: Array.from({ length: treeSize }, (_, i) => ({
      leafIndex: i,
      manifestId: `urn:c2pa:demo-${i}`,
      leafHash: `hash-${i}`,
    })),
    treeSize,
    rootHash: "root-abc",
  };
}

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return { client, container: view.container };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MerkleExplorer", () => {
  it("shows the live indicator on first load without playing the new-leaf pulse", async () => {
    vi.mocked(usePrefersReducedMotion).mockReturnValue(false);
    vi.spyOn(fetchClient, "GET").mockResolvedValue(ok(logResponse(2)) as unknown as GetResult);

    const { container } = renderWithClient(<MerkleExplorer />);

    expect(await screen.findByText("live")).toBeTruthy();
    expect(screen.getByText(/checked/)).toBeTruthy();
    expect(container.querySelector(".animate-ping")).toBeTruthy();

    // the first response is the baseline: no "+N new" chip, no highlighted node
    expect(screen.queryByText(/\+\d+ new/)).toBeNull();
    const graph = await screen.findByTestId("merkle-graph");
    expect(graph.getAttribute("data-highlights")).toBe("");
  });

  it("pulses the new leaf and the counter when the live tree grows between polls", async () => {
    vi.mocked(usePrefersReducedMotion).mockReturnValue(false);
    const get = vi.spyOn(fetchClient, "GET");
    get.mockResolvedValueOnce(ok(logResponse(2)) as unknown as GetResult);
    get.mockResolvedValueOnce(ok(logResponse(3)) as unknown as GetResult);

    const { client, container } = renderWithClient(<MerkleExplorer />);
    await screen.findByText("live");

    // the poll interval fires the same query function; drive one refetch directly
    await act(async () => {
      await client.refetchQueries();
    });

    const chip = await screen.findByText("+1 new");
    expect(chip.className).toContain("animate-pulse");
    expect(chip.closest("dd")?.textContent).toContain("3");
    expect(screen.getByTestId("merkle-graph").getAttribute("data-highlights")).toBe("leaf-2");
    expect(container.querySelector(".animate-ping")).toBeTruthy();
  });

  it("keeps the pulse and dot static under prefers-reduced-motion", async () => {
    vi.mocked(usePrefersReducedMotion).mockReturnValue(true);
    const get = vi.spyOn(fetchClient, "GET");
    get.mockResolvedValueOnce(ok(logResponse(2)) as unknown as GetResult);
    get.mockResolvedValueOnce(ok(logResponse(3)) as unknown as GetResult);

    const { client, container } = renderWithClient(<MerkleExplorer />);
    await screen.findByText("live");

    await act(async () => {
      await client.refetchQueries();
    });

    // the new-leaf state still shows (it is a state change, not motion), with no animation classes
    expect(await screen.findByText("+1 new")).toBeTruthy();
    expect(container.querySelector(".animate-ping")).toBeNull();
    expect(container.querySelector(".animate-pulse")).toBeNull();
  });

  it("shows the error state and no live indicator when the backend is unreachable", async () => {
    vi.mocked(usePrefersReducedMotion).mockReturnValue(false);
    vi.spyOn(fetchClient, "GET").mockResolvedValue({
      data: undefined,
      error: { detail: "boom" },
      response: new Response(null, { status: 500 }),
    } as unknown as GetResult);

    renderWithClient(<MerkleExplorer />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
    expect(screen.queryByText("live")).toBeNull();
  });
});
