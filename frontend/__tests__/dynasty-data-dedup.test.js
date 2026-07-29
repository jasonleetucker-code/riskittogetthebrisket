/**
 * Request dedup + TTL cache tests for the contract data layer.
 *
 * ``useDynastyData`` mounts at least twice per page (AppShell + the
 * page component), and before these caches existed each mount issued
 * its own multi-MB ``GET /api/dynasty-data`` and pipeline-rebuilding
 * ``POST /api/rankings/overrides``.  Pinned here:
 *
 *   1. Concurrent default-path fetches share ONE network request.
 *   2. A second call within the 30s TTL makes ZERO network requests.
 *   3. TTL expiry triggers a revalidating refetch.
 *   4. Concurrent override-path fetches share one GET + one POST.
 *   5. ``_resetBaseContractCache`` drops everything.
 *   6. The base fetch uses ``cache: "no-cache"`` (revalidate, never
 *      silently replay) — NOT ``no-store`` (which would kill the 304
 *      path) and NOT default (which could serve without revalidating).
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  fetchDynastyData,
  prefetchBaseContract,
  _resetBaseContractCache,
  _resetValuationOverlayCache,
} from "@/lib/dynasty-data.js";

const BASE_PAYLOAD = {
  ok: true,
  source: "backend",
  data: {
    playersArray: [
      {
        displayName: "Player A",
        canonicalName: "Player A",
        position: "QB",
        team: "AAA",
        canonicalConsensusRank: 1,
        rankDerivedValue: 9800,
        sourceRanks: { ktc: 1 },
      },
    ],
  },
};

const DELTA_PAYLOAD = {
  mode: "delta",
  rankingsOverride: { isCustomized: true },
  rankingsDelta: {
    playerKey: "displayName",
    players: [
      {
        id: "Player A",
        canonicalConsensusRank: 1,
        rankDerivedValue: 9700,
        sourceRanks: { ktc: 1 },
      },
    ],
    activePlayerIds: ["Player A"],
  },
};

function mockFetchRouting() {
  return vi.fn(async (url) => {
    if (String(url).includes("/api/rankings/overrides")) {
      return { ok: true, json: async () => structuredClone(DELTA_PAYLOAD) };
    }
    return { ok: true, json: async () => structuredClone(BASE_PAYLOAD) };
  });
}

describe("contract data layer dedup + TTL", () => {
  const realFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = mockFetchRouting();
    _resetBaseContractCache();
    _resetValuationOverlayCache();
  });

  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("concurrent default-path fetches share one network request", async () => {
    const [a, b] = await Promise.all([fetchDynastyData(), fetchDynastyData()]);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect(a).toBe(b);
  });

  it("a second call within the TTL makes zero network requests", async () => {
    await fetchDynastyData();
    await fetchDynastyData();
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("TTL expiry triggers a refetch", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-28T12:00:00Z"));
    await fetchDynastyData();
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);

    vi.setSystemTime(new Date("2026-07-28T12:00:31Z"));
    await fetchDynastyData();
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("concurrent override-path fetches share one GET and one POST", async () => {
    const opts = { tepMultiplier: 1.15 };
    const [a, b] = await Promise.all([
      fetchDynastyData(opts),
      fetchDynastyData(opts),
    ]);
    const urls = globalThis.fetch.mock.calls.map(([u]) => String(u));
    const gets = urls.filter((u) => u.includes("/api/dynasty-data"));
    const posts = urls.filter((u) => u.includes("/api/rankings/overrides"));
    expect(gets).toHaveLength(1);
    expect(posts).toHaveLength(1);
    expect(a).toBe(b);
    expect(a.source).toBe("backend:override:delta");
  });

  it("a repeat override call within the TTL is served from the memo", async () => {
    const opts = { tepMultiplier: 1.15 };
    const first = await fetchDynastyData(opts);
    const second = await fetchDynastyData(opts);
    expect(second).toBe(first);
    const posts = globalThis.fetch.mock.calls
      .map(([u]) => String(u))
      .filter((u) => u.includes("/api/rankings/overrides"));
    expect(posts).toHaveLength(1);
  });

  it("a different override body misses the memo", async () => {
    await fetchDynastyData({ tepMultiplier: 1.15 });
    await fetchDynastyData({ tepMultiplier: 1.3 });
    const posts = globalThis.fetch.mock.calls
      .map(([u]) => String(u))
      .filter((u) => u.includes("/api/rankings/overrides"));
    expect(posts).toHaveLength(2);
  });

  it("_resetBaseContractCache drops base and merged caches", async () => {
    await fetchDynastyData({ tepMultiplier: 1.15 });
    _resetBaseContractCache();
    await fetchDynastyData({ tepMultiplier: 1.15 });
    const urls = globalThis.fetch.mock.calls.map(([u]) => String(u));
    expect(urls.filter((u) => u.includes("/api/dynasty-data"))).toHaveLength(2);
    expect(
      urls.filter((u) => u.includes("/api/rankings/overrides")),
    ).toHaveLength(2);
  });

  it("failed base fetches are never cached", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 503,
        text: async () => "boom",
      })
      .mockResolvedValue({
        ok: true,
        json: async () => structuredClone(BASE_PAYLOAD),
      });
    await expect(fetchDynastyData()).rejects.toThrow(/503/);
    const result = await fetchDynastyData();
    expect(result.ok).toBe(true);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("the base fetch revalidates with no-cache, never no-store", async () => {
    await fetchDynastyData();
    const [url, opts] = globalThis.fetch.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/dynasty-data/);
    expect(opts?.cache).toBe("no-cache");
  });

  it("override path fires base GET and overrides POST concurrently", async () => {
    // Make the base fetch slow; assert the POST is already on the wire
    // before the base resolves (they used to run serially, putting an
    // extra round-trip on every first page view).
    let resolveBase;
    const urls = [];
    globalThis.fetch = vi.fn((url) => {
      urls.push(String(url));
      if (String(url).includes("/api/rankings/overrides")) {
        return Promise.resolve({
          ok: true,
          json: async () => structuredClone(DELTA_PAYLOAD),
        });
      }
      return new Promise((resolve) => {
        resolveBase = () =>
          resolve({ ok: true, json: async () => structuredClone(BASE_PAYLOAD) });
      });
    });

    const resultPromise = fetchDynastyData({ tepMultiplier: 1.15 });
    // Give microtasks a chance to dispatch both requests.
    await new Promise((r) => setTimeout(r, 0));
    expect(
      urls.some((u) => u.includes("/api/rankings/overrides")),
      "overrides POST must start before the base GET resolves",
    ).toBe(true);
    resolveBase();
    const result = await resultPromise;
    expect(result.source).toBe("backend:override:delta");
  });

  it("prefetchBaseContract shares its in-flight request with the real fetch", async () => {
    prefetchBaseContract();
    const result = await fetchDynastyData();
    expect(result.ok).toBe(true);
    const gets = globalThis.fetch.mock.calls
      .map(([u]) => String(u))
      .filter((u) => u.includes("/api/dynasty-data"));
    expect(gets).toHaveLength(1);
  });

  it("prefetchBaseContract swallows failures and leaves the path retryable", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 401, text: async () => "no" })
      .mockResolvedValue({
        ok: true,
        json: async () => structuredClone(BASE_PAYLOAD),
      });
    prefetchBaseContract();
    // Let the rejected prefetch settle without surfacing.
    await new Promise((r) => setTimeout(r, 0));
    const result = await fetchDynastyData();
    expect(result.ok).toBe(true);
  });
});
