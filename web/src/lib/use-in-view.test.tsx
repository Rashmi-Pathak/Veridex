import { act } from "react";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { useInView } from "@/lib/use-in-view";

// Capture the IntersectionObserver instances so a test can drive the callback and assert what was
// observed. This is the only way to prove the gated child mounts, since jsdom has no real observer.
let lastCallback: IntersectionObserverCallback | null = null;
const observe = vi.fn();
const disconnect = vi.fn();

class MockIO {
  constructor(cb: IntersectionObserverCallback) {
    lastCallback = cb;
  }
  observe = observe;
  disconnect = disconnect;
  unobserve = vi.fn();
  takeRecords = vi.fn(() => []);
  root = null;
  rootMargin = "";
  thresholds = [];
}

function fireIntersect(): void {
  act(() => {
    lastCallback?.([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
  });
}

// The gated container renders only when `present` is true, mirroring the real panels, which render
// the ref'd graph container only after their data loads (the late-attach case the hook must handle).
function Gated({ present }: { present: boolean }) {
  const [ref, inView] = useInView<HTMLDivElement>();
  return (
    <div>
      {present && (
        <div ref={ref} data-testid="container">
          {inView && <span>CHILD</span>}
        </div>
      )}
    </div>
  );
}

beforeEach(() => {
  lastCallback = null;
  vi.stubGlobal("IntersectionObserver", MockIO);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("useInView", () => {
  it("mounts the gated child only after the container intersects", () => {
    render(<Gated present={true} />);
    expect(observe).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("CHILD")).toBeNull();
    fireIntersect();
    expect(screen.getByText("CHILD")).toBeTruthy();
  });

  it("observes a container that attaches LATE (after the first render)", () => {
    // The regression guard: the container is absent on first render, so a non-reactive ref would
    // never get observed. The callback ref must observe it once it appears.
    const { rerender } = render(<Gated present={false} />);
    expect(observe).not.toHaveBeenCalled();
    rerender(<Gated present={true} />);
    expect(observe).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("CHILD")).toBeNull();
    fireIntersect();
    expect(screen.getByText("CHILD")).toBeTruthy();
  });
});
