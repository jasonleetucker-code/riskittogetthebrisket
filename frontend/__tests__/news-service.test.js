import { afterEach, describe, it, expect, vi } from "vitest";
import {
  fetchNews,
  filterByScope,
  rankByRelevance,
  selectTickerAlerts,
  NEWS_FETCH_LIMIT,
} from "@/lib/news-service";

function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchNews fail-fast (no mock fallback)", () => {
  it("returns backend items on 200", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        items: [{ id: "n1", headline: "hi" }],
        providersUsed: ["espn"],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const res = await fetchNews();
    expect(res.unavailable).toBe(false);
    expect(res.source).toBe("backend");
    expect(res.items).toHaveLength(1);
    expect(res.providersUsed).toEqual(["espn"]);
  });

  it("requests the route's full limit so client-side filters see the whole feed", async () => {
    // The News tab's team/position/source/search filters run over
    // this payload — a lighter default would let the server truncate
    // matching items away before the filters run (Codex P2).
    expect(NEWS_FETCH_LIMIT).toBe(100);
    const fetchMock = vi.fn(async () => jsonResponse({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await fetchNews();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/news?limit=100",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("honors an explicit limit override", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await fetchNews({ limit: 25 });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/news?limit=25");
  });

  it("503 surfaces an explicit unavailable state, not fixture items", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({}, 503)));
    const res = await fetchNews();
    expect(res.unavailable).toBe(true);
    expect(res.reason).toBe("backend_unavailable");
    expect(res.items).toEqual([]);
    expect(res.source).not.toBe("mock");
    expect(res.providersUsed).toEqual([]);
  });

  it("404 surfaces backend_unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({}, 404)));
    const res = await fetchNews();
    expect(res.unavailable).toBe(true);
    expect(res.reason).toBe("backend_unavailable");
    expect(res.items).toEqual([]);
  });

  it("other HTTP errors carry the status in the reason", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({}, 500)));
    const res = await fetchNews();
    expect(res.unavailable).toBe(true);
    expect(res.reason).toBe("backend_error_500");
  });

  it("network failure surfaces fetch_failed with zero items", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network down");
      }),
    );
    const res = await fetchNews();
    expect(res.unavailable).toBe(true);
    expect(res.reason).toBe("fetch_failed");
    expect(res.items).toEqual([]);
  });

  it("rethrows AbortError so callers can cancel silently", async () => {
    const abort = new Error("aborted");
    abort.name = "AbortError";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw abort;
      }),
    );
    await expect(fetchNews()).rejects.toBe(abort);
  });
});

describe("scoring helpers still behave with backend-only data", () => {
  const items = [
    {
      id: "r1",
      ts: "2026-07-24T10:00:00Z",
      severity: "alert",
      headline: "Roster player hurt",
      players: [{ name: "Bijan Robinson" }],
    },
    {
      id: "g1",
      ts: "2026-07-25T10:00:00Z",
      severity: "info",
      headline: "General note",
      players: [],
    },
  ];

  it("rankByRelevance + filterByScope keep roster items under roster scope", () => {
    const scored = rankByRelevance(items, {
      rosterNames: ["Bijan Robinson"],
      leagueNames: [],
    });
    expect(filterByScope(scored, "roster").map((i) => i.id)).toEqual(["r1"]);
    expect(filterByScope(scored, "all")).toHaveLength(2);
  });

  it("selectTickerAlerts only picks roster-relevant alerts", () => {
    const scored = rankByRelevance(items, {
      rosterNames: ["Bijan Robinson"],
      leagueNames: [],
    });
    expect(selectTickerAlerts(scored).map((i) => i.id)).toEqual(["r1"]);
  });
});
