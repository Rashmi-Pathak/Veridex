import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { RecoverStrip } from "@/components/recover-strip";

afterEach(() => {
  vi.restoreAllMocks();
});

// The credentialed -> stripped -> recovered VISUAL states depend on canvas re-encode and blob-image
// rendering that jsdom does not implement, so they are verified on the live deploy. Here we assert the
// component mounts the lead reveal and initiates the REAL recovery flow against the real endpoints.
describe("RecoverStrip", () => {
  it("renders the lead reveal and fetches the real demo sample on mount", async () => {
    const fetchSpy = vi.fn(
      async () => new Response("img", { status: 200, headers: { "content-type": "image/jpeg" } }),
    );
    globalThis.fetch = fetchSpy as unknown as typeof fetch;

    render(<RecoverStrip />);

    expect(screen.getByText("Strip and recover")).toBeTruthy();
    expect(screen.getByText(/The same image, stripped then recovered/)).toBeTruthy();
    expect(screen.getByText(/genuine canvas JPEG re-encode/)).toBeTruthy();
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith("/api/demo/sample", expect.anything()),
    );
  });

  it("degrades to an honest error when the sample is unreachable", async () => {
    globalThis.fetch = vi.fn(
      async () => new Response("", { status: 500 }),
    ) as unknown as typeof fetch;

    render(<RecoverStrip />);

    expect(await screen.findByText(/Backend unreachable/)).toBeTruthy();
  });
});
