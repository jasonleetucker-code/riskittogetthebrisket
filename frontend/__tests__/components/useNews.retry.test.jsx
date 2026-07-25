// Hook-level recovery test: a mounted consumer that saw a backend
// failure must automatically re-fetch (backoff timer) and flip to
// live items once the backend recovers — without a remount.
import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useNews, _resetNewsCacheForTests } from "@/components/useNews";

function okResponse(items) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ items, providersUsed: ["espn"] }),
  };
}

beforeEach(() => {
  _resetNewsCacheForTests();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  _resetNewsCacheForTests();
});

describe("useNews automatic retry", () => {
  it("recovers from a transient 503 while mounted", async () => {
    const fail = vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) }));
    vi.stubGlobal("fetch", fail);

    const { result } = renderHook(() => useNews());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.unavailable).toBe(true);

    // Backend recovers.  The scheduled retry (15s backoff, past the
    // 15s failure TTL) must refetch and clear the unavailable state.
    const ok = vi.fn(async () => okResponse([{ id: "n1", headline: "hi" }]));
    vi.stubGlobal("fetch", ok);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_001);
    });

    expect(ok).toHaveBeenCalledTimes(1);
    expect(result.current.unavailable).toBe(false);
    expect(result.current.items).toHaveLength(1);
  });

  it("stops retrying after unmount", async () => {
    const fail = vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) }));
    vi.stubGlobal("fetch", fail);

    const { unmount } = renderHook(() => useNews());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fail).toHaveBeenCalledTimes(1);

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    // No mounted consumer → the cleanup cleared the retry timer, so
    // no further fetches fire.
    expect(fail).toHaveBeenCalledTimes(1);
  });
});
