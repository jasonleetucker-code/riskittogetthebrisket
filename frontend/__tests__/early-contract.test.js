/**
 * Early base-contract request (lib/early-contract.js).
 *
 * The inline head script starts the Rankings/Trade board request during HTML
 * parse; the fetch layer adopts it. Pinned here:
 *
 *   1. The script records EXACTLY the key `_fetchBaseContract` looks up, and
 *      requests exactly the URL the normal path would — so adoption happens.
 *   2. Adopted → ONE network request total, and the normal result.
 *   3. Inert on every other route.
 *   4. A different league (key mismatch) or a stale early request is NOT
 *      adopted; the normal request runs.
 *   5. A rejected early request surfaces exactly like a normal network error.
 *   6. Consumed at most once; a reset spends it.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { EARLY_CONTRACT_SCRIPT, EARLY_CONTRACT_MAX_AGE_MS, LEAGUE_LOCAL_KEY } from "@/lib/early-contract.js";
import { fetchDynastyData, _resetBaseContractCache } from "@/lib/dynasty-data.js";

const BASE = {
  ok: true,
  source: "backend",
  data: {
    playersArray: [
      { displayName: "Player A", canonicalName: "Player A", position: "QB", team: "AAA", canonicalConsensusRank: 1, rankDerivedValue: 9800, sourceRanks: { ktc: 1 } },
    ],
  },
};

function response(body = BASE) {
  return { ok: true, status: 200, json: async () => structuredClone(body) };
}

/** Stub the browser globals both the script and the fetch layer read. */
function stubBrowser({ pathname, league = "", fetchImpl }) {
  const store = league ? { [LEAGUE_LOCAL_KEY]: league } : {};
  const fetchMock = vi.fn(fetchImpl || (async () => response()));
  const win = { innerWidth: 1920, location: { pathname }, fetch: fetchMock, addEventListener() {} };
  vi.stubGlobal("window", win);
  vi.stubGlobal("location", win.location);
  vi.stubGlobal("navigator", { deviceMemory: 16 });
  vi.stubGlobal("localStorage", { getItem: (k) => store[k] ?? null });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function runHeadScript() {
  // Same execution the browser gives an inline <script> in <head>.
  new Function(EARLY_CONTRACT_SCRIPT)();
}

describe("early base-contract request", () => {
  beforeEach(() => {
    _resetBaseContractCache();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  for (const pathname of ["/rankings", "/trade"]) {
    for (const league of ["league-a", ""]) {
      it(`${pathname} ${league ? "with" : "without"} a league: one request, adopted by the fetch layer`, async () => {
        const fetchMock = stubBrowser({ pathname, league });
        runHeadScript();
        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [url, init] = fetchMock.mock.calls[0];
        const u = new URL(url, "https://example.test");
        expect(u.pathname).toBe("/api/dynasty-data");
        expect(u.searchParams.get("view")).toBe("compact");
        expect(u.searchParams.get("leagueKey")).toBe(league || null);
        expect(init).toEqual({ cache: "no-cache" });

        const payload = await fetchDynastyData();
        expect(fetchMock).toHaveBeenCalledTimes(1); // adopted, not re-requested
        expect(payload.data.playersArray[0].displayName).toBe("Player A");
      });
    }
  }

  it("the adopted request is byte-identical to the one the normal path makes", async () => {
    const early = stubBrowser({ pathname: "/rankings", league: "league-a" });
    runHeadScript();
    const earlyUrl = early.mock.calls[0][0];
    vi.unstubAllGlobals();
    _resetBaseContractCache();
    const normal = stubBrowser({ pathname: "/rankings", league: "league-a" });
    await fetchDynastyData();
    expect(normal).toHaveBeenCalledTimes(1);
    const a = new URL(earlyUrl, "https://example.test");
    const b = new URL(normal.mock.calls[0][0], "https://example.test");
    expect(a.pathname).toBe(b.pathname);
    expect([...a.searchParams].sort()).toEqual([...b.searchParams].sort());
    expect(normal.mock.calls[0][1]).toEqual({ cache: "no-cache" });
  });

  it("is inert on every other route", () => {
    for (const pathname of ["/", "/draft", "/league", "/game-day", "/login", "/rankings/extra"]) {
      const fetchMock = stubBrowser({ pathname, league: "league-a" });
      runHeadScript();
      expect(fetchMock).not.toHaveBeenCalled();
      vi.unstubAllGlobals();
    }
  });

  it("a league switched before the fetch layer runs is not adopted", async () => {
    const fetchMock = stubBrowser({ pathname: "/rankings", league: "league-a" });
    runHeadScript();
    vi.stubGlobal("localStorage", { getItem: (k) => (k === LEAGUE_LOCAL_KEY ? "league-b" : null) });
    await fetchDynastyData();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const second = new URL(fetchMock.mock.calls[1][0], "https://example.test");
    expect(second.searchParams.get("leagueKey")).toBe("league-b");
  });

  it("a response that arrived longer ago than the TTL is not adopted", async () => {
    vi.useFakeTimers();
    const t0 = Date.parse("2026-09-28T12:00:00Z");
    vi.setSystemTime(t0);
    const fetchMock = stubBrowser({ pathname: "/trade", league: "league-a" });
    runHeadScript();
    await Promise.resolve(); // the early response arrives at t0
    await Promise.resolve();
    vi.setSystemTime(t0 + EARLY_CONTRACT_MAX_AGE_MS + 1);
    await fetchDynastyData();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("a request still in flight is adopted whatever its age — a slow network never pays twice", async () => {
    vi.useFakeTimers();
    const t0 = Date.parse("2026-09-28T12:00:00Z");
    vi.setSystemTime(t0);
    let release;
    const fetchMock = stubBrowser({
      pathname: "/rankings",
      league: "league-a",
      fetchImpl: () => new Promise((resolve) => { release = () => resolve(response()); }),
    });
    runHeadScript();
    vi.setSystemTime(t0 + 5 * EARLY_CONTRACT_MAX_AGE_MS); // chunks + hydration took minutes
    const pending = fetchDynastyData();
    // Release only once the fetch layer has TAKEN the early request, so it is
    // judged while still in flight (the layer awaits a dynamic import first).
    await vi.waitFor(() => expect(window.__riskitEarlyContract).toBeUndefined());
    release();
    const payload = await pending;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(payload.data.playersArray).toHaveLength(1);
  });

  it("an adopted response is fresh from its arrival, not from its adoption", async () => {
    vi.useFakeTimers();
    const t0 = Date.parse("2026-09-28T12:00:00Z");
    vi.setSystemTime(t0);
    const fetchMock = stubBrowser({ pathname: "/rankings", league: "league-a" });
    runHeadScript();
    await Promise.resolve();
    await Promise.resolve(); // arrived at t0
    vi.setSystemTime(t0 + 20_000); // adopted 20 s later
    await fetchDynastyData();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    vi.setSystemTime(t0 + 31_000); // 31 s after ARRIVAL: past the 30 s TTL
    await fetchDynastyData();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("a rejected early request surfaces like a normal network error", async () => {
    stubBrowser({ pathname: "/rankings", league: "league-a", fetchImpl: async () => { throw new TypeError("Failed to fetch"); } });
    runHeadScript();
    const err = await fetchDynastyData().catch((e) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err.status).toBeNull();
    expect(err.message).toMatch(/^Could not reach the server: Failed to fetch/);
  });

  it("an HTTP error from the early request keeps its status", async () => {
    stubBrowser({
      pathname: "/rankings",
      league: "league-a",
      fetchImpl: async () => ({ ok: false, status: 401, text: async () => '{"error":"auth"}' }),
    });
    runHeadScript();
    const err = await fetchDynastyData().catch((e) => e);
    expect(err.status).toBe(401);
    expect(err.body).toEqual({ error: "auth" });
  });

  it("is consumed at most once, and a reset spends it", async () => {
    const fetchMock = stubBrowser({ pathname: "/rankings", league: "league-a" });
    runHeadScript();
    _resetBaseContractCache();
    await fetchDynastyData();
    expect(fetchMock).toHaveBeenCalledTimes(2); // spent by the reset → normal request
    _resetBaseContractCache();
    await fetchDynastyData();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
