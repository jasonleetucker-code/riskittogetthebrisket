// Dev-proxy route for /api/news: without it the Next dev server has
// nothing mounted at /api/news (production nginx forwards /api/* to
// FastAPI directly) and every news surface 404s locally now that
// the mock fallback is gone.
import { afterEach, describe, it, expect, vi } from "vitest";
import { GET } from "@/app/api/news/route";

afterEach(() => {
  vi.unstubAllGlobals();
});

function backendResponse(payload, { status = 200, cacheControl } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (k) => (k.toLowerCase() === "cache-control" ? cacheControl || null : null) },
    json: async () => payload,
  };
}

describe("GET /api/news proxy route", () => {
  it("forwards limit and repeatable team params to the backend", async () => {
    const fetchMock = vi.fn(async () => backendResponse({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await GET({ url: "http://localhost:3000/api/news?limit=100&team=Alpha&team=Beta" });

    const target = new URL(fetchMock.mock.calls[0][0]);
    expect(target.pathname).toBe("/api/news");
    expect(target.searchParams.get("limit")).toBe("100");
    expect(target.searchParams.getAll("team")).toEqual(["Alpha", "Beta"]);
  });

  it("passes backend status + payload + Cache-Control through", async () => {
    const fetchMock = vi.fn(async () =>
      backendResponse(
        { items: [{ id: "n1" }], providersUsed: ["espn"] },
        { cacheControl: "public, max-age=60, stale-while-revalidate=180" },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const res = await GET({ url: "http://localhost:3000/api/news?limit=100" });
    expect(res.status).toBe(200);
    expect(res.headers.get("Cache-Control")).toContain("public");
    const body = await res.json();
    expect(body.items).toHaveLength(1);
  });

  it("backend unreachable degrades to a 503 news-shaped payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("connect ECONNREFUSED");
      }),
    );

    const res = await GET({ url: "http://localhost:3000/api/news" });
    expect(res.status).toBe(503);
    const body = await res.json();
    expect(body.items).toEqual([]);
    expect(body.error).toBe("news_backend_unreachable");
  });
});
