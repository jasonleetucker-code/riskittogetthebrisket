import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "@/app/api/auction/[...path]/route.js";
import { browserOrigin, isSameOriginRequest } from "@/lib/bridge-origin";

const params = (path) => ({ params: Promise.resolve({ path }) });

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response('{"ok":true}', { status: 200, headers: { "content-type": "application/json" } })),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("/api/auction dev bridge — same-origin check", () => {
  it("accepts a same-origin POST even when Next's request.url names a different bind host", async () => {
    // Under `next start` request.url can say localhost while the browser
    // (its Origin and Host) says 127.0.0.1 — the old check refused this.
    const req = new Request("http://localhost:3000/api/auction/rooms/r1/bids", {
      method: "POST",
      headers: {
        origin: "http://127.0.0.1:3000",
        host: "127.0.0.1:3000",
        cookie: "jason_session=x",
        "idempotency-key": "k1",
      },
      body: '{"amount":5}',
    });
    const res = await POST(req, params(["rooms", "r1", "bids"]));
    expect(res.status).toBe(200);
    const [url, init] = fetch.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/auction\/rooms\/r1\/bids$/);
    expect(init.headers.Cookie).toBe("jason_session=x");
    expect(init.headers["Idempotency-Key"]).toBe("k1");
    expect(init.headers.Origin).toBe(new URL(String(url)).origin); // backend's origin is presented
  });

  it("refuses a cross-site POST and a POST without Origin before reaching the backend", async () => {
    for (const origin of ["https://evil.example", null]) {
      const headers = { host: "127.0.0.1:3000" };
      if (origin) headers.origin = origin;
      const req = new Request("http://127.0.0.1:3000/api/auction/rooms/r1/bids", { method: "POST", headers, body: "{}" });
      const res = await POST(req, params(["rooms", "r1", "bids"]));
      expect(res.status).toBe(403);
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not origin-check GETs", async () => {
    const req = new Request("http://localhost:3000/api/auction/rooms/r1?wait=0", { headers: { host: "127.0.0.1:3000" } });
    const res = await GET(req, params(["rooms", "r1"]));
    expect(res.status).toBe(200);
    expect(String(fetch.mock.calls[0][0])).toMatch(/\/api\/auction\/rooms\/r1\?wait=0$/);
  });

  it("refuses dot segments instead of resolving out of /api/auction", async () => {
    const req = new Request("http://127.0.0.1:3000/api/auction/x", { headers: { host: "127.0.0.1:3000" } });
    const res = await GET(req, params(["..", "trade", "simulate"]));
    expect(res.status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("lib/bridge-origin", () => {
  it("prefers the forwarded host, then Host, then request.url", () => {
    const mk = (headers) => new Request("http://localhost:3000/x", { headers });
    expect(browserOrigin(mk({ "x-forwarded-host": "dev.test:3000", host: "127.0.0.1:3000" }))).toBe("http://dev.test:3000");
    expect(browserOrigin(mk({ host: "127.0.0.1:3000" }))).toBe("http://127.0.0.1:3000");
    expect(isSameOriginRequest(mk({ host: "127.0.0.1:3000", origin: "http://127.0.0.1:3000" }))).toBe(true);
    expect(isSameOriginRequest(mk({ host: "127.0.0.1:3000", origin: "http://127.0.0.1:3001" }))).toBe(false);
    expect(isSameOriginRequest(mk({ host: "127.0.0.1:3000" }))).toBe(false);
  });
});
