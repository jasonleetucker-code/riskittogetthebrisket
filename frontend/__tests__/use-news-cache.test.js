import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import {
  _getNewsForTests as getNews,
  _resetNewsCacheForTests,
  newsRetryDelayMs,
} from "@/components/useNews";

function okResponse(items) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ items, providersUsed: ["espn"] }),
  };
}

function errorResponse(status) {
  return { ok: false, status, json: async () => ({}) };
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

describe("getNews module cache — failure results don't block recovery", () => {
  it("caches a transient 503 only briefly, then refetches and recovers", async () => {
    const fail = vi.fn(async () => errorResponse(503));
    vi.stubGlobal("fetch", fail);

    const first = await getNews();
    expect(first.unavailable).toBe(true);

    // Within the failure TTL the cached failure is reused (dedupe
    // across panels mounting together) — no extra network call.
    const second = await getNews();
    expect(second.unavailable).toBe(true);
    expect(fail).toHaveBeenCalledTimes(1);

    // Backend recovers.  Past the (short) failure TTL the next call
    // must actually refetch and return live items — the failure must
    // NOT enjoy the 60s success TTL.
    const ok = vi.fn(async () => okResponse([{ id: "n1", headline: "hi" }]));
    vi.stubGlobal("fetch", ok);
    vi.advanceTimersByTime(15_000 + 1);

    const third = await getNews();
    expect(ok).toHaveBeenCalledTimes(1);
    expect(third.unavailable).toBe(false);
    expect(third.items).toHaveLength(1);
  });

  it("still caches successes for the full TTL", async () => {
    const ok = vi.fn(async () => okResponse([{ id: "n1" }]));
    vi.stubGlobal("fetch", ok);

    await getNews();
    vi.advanceTimersByTime(30_000); // half the success TTL
    const again = await getNews();
    expect(ok).toHaveBeenCalledTimes(1);
    expect(again.items).toHaveLength(1);

    vi.advanceTimersByTime(30_001); // past the success TTL
    await getNews();
    expect(ok).toHaveBeenCalledTimes(2);
  });

  it("network rejections are not cached at all", async () => {
    const boom = vi.fn(async () => {
      throw new TypeError("network down");
    });
    vi.stubGlobal("fetch", boom);
    // fetchNews converts network errors into an unavailable RESULT
    // (not a rejection), so this exercises the same failure-TTL path.
    const res = await getNews();
    expect(res.unavailable).toBe(true);
    expect(res.reason).toBe("fetch_failed");

    const ok = vi.fn(async () => okResponse([{ id: "n1" }]));
    vi.stubGlobal("fetch", ok);
    vi.advanceTimersByTime(15_001);
    const recovered = await getNews();
    expect(recovered.unavailable).toBe(false);
  });
});

describe("newsRetryDelayMs backoff", () => {
  it("backs off 15s → 30s → 60s and caps there", () => {
    expect(newsRetryDelayMs(1)).toBe(15_000);
    expect(newsRetryDelayMs(2)).toBe(30_000);
    expect(newsRetryDelayMs(3)).toBe(60_000);
    expect(newsRetryDelayMs(10)).toBe(60_000);
  });

  it("is defensive about weird attempt numbers", () => {
    expect(newsRetryDelayMs(0)).toBe(15_000);
    expect(newsRetryDelayMs(-3)).toBe(15_000);
  });
});
