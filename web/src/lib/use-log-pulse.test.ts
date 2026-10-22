import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLogPulse } from "@/lib/use-log-pulse";

// The pulse must report only a REAL growth in the live tree size: the first observed size is the
// baseline (a fresh page load never pulses), and the window closes on its own after pulseMs.

type Props = { size: number | undefined };

function renderPulse(initialSize: number | undefined, pulseMs?: number) {
  return renderHook(({ size }: Props) => useLogPulse(size, pulseMs), {
    initialProps: { size: initialSize },
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useLogPulse", () => {
  it("does not pulse on the first observed tree size", () => {
    const { result, rerender } = renderPulse(undefined);
    expect(result.current).toBeNull();
    rerender({ size: 5 });
    expect(result.current).toBeNull();
  });

  it("pulses with the new leaf range when the tree grows, then clears after pulseMs", () => {
    const { result, rerender } = renderPulse(3, 1000);
    rerender({ size: 5 });
    expect(result.current).toEqual({ from: 3, to: 5 });
    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(result.current).toEqual({ from: 3, to: 5 });
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBeNull();
  });

  it("does not pulse when the size is unchanged or smaller, and re-baselines", () => {
    const { result, rerender } = renderPulse(4);
    rerender({ size: 4 });
    expect(result.current).toBeNull();
    rerender({ size: 2 });
    expect(result.current).toBeNull();
    // a later growth pulses only the delta from the moved baseline
    rerender({ size: 3 });
    expect(result.current).toEqual({ from: 2, to: 3 });
  });
});
