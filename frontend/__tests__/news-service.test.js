import { afterEach, describe, it, expect, vi } from "vitest";
import {
  fetchNews,
  filterByScope,
  rankByRelevance,
  selectTickerAlerts,
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
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          items: [{ id: "n1", headline: "hi" }],
          providersUsed: ["espn"],
        }),
      ),
    );
    const res = await fetchNews();
    expect(res.unavailable).toBe(false);
    expect(res.source).toBe("backend");
    expect(res.items).toHaveLength(1);
    expect(res.providersUsed).toEqual(["espn"]);
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
