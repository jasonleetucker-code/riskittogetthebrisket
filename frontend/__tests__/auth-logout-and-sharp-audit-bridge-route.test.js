/**
 * Bridges for POST /api/auth/logout and GET /api/sharp/roster-percentage/audit
 * (CW-50 / CW-07).  Both forward the caller's cookie (the backend owns the
 * auth decision), preserve the backend status, and never cache.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const proxy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/backend-proxy", () => ({ proxyGet: proxy }));

import { POST as logout } from "@/app/api/auth/logout/route";
import { GET as audit } from "@/app/api/sharp/roster-percentage/audit/route";

beforeEach(() => {
  proxy.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("logout bridge", () => {
  it("forwards the session cookie to the backend logout and relays its answer", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => ({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const res = await logout({ headers: new Headers({ cookie: "jason_session=abc" }) });
    const [url, init] = fetchMock.mock.calls[0];
    expect(new URL(url).pathname).toBe("/api/auth/logout");
    expect(init.method).toBe("POST");
    expect(init.headers.Cookie).toBe("jason_session=abc");
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
  });

  it("works with no cookie at all (logout while logged out)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ status: 200, json: async () => ({ ok: true }) });
    vi.stubGlobal("fetch", fetchMock);
    const res = await logout({ headers: new Headers() });
    expect(fetchMock.mock.calls[0][1].headers.Cookie).toBe("");
    expect(res.status).toBe(200);
  });

  it("tolerates a non-JSON backend body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        json: async () => {
          throw new Error("not json");
        },
      }),
    );
    const res = await logout({ headers: new Headers() });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({});
  });

  it("an unreachable backend still lets the UI sign out locally (200 ok)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));
    const res = await logout({ headers: new Headers({ cookie: "x=1" }) });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
  });
});

describe("sharp roster-percentage audit bridge", () => {
  const req = (qs, cookie = "jason_session=abc") => ({
    url: `http://localhost/api/sharp/roster-percentage/audit${qs}`,
    headers: new Headers(cookie ? { cookie } : {}),
  });

  it("forwards cookie + query and never caches", async () => {
    proxy.mockResolvedValue({ data: { assetId: "p:1" }, status: 200 });
    const res = await audit(req("?assetId=p:1&qualification=curated"));
    expect(proxy).toHaveBeenCalledWith("/api/sharp/roster-percentage/audit", {
      cookie: "jason_session=abc",
      timeoutMs: 20000,
      searchParams: { assetId: "p:1", qualification: "curated" },
    });
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toContain("no-store");
  });

  it("preserves the backend's anonymous refusal (no data relayed)", async () => {
    proxy.mockResolvedValue({ data: { error: "auth_required" }, status: 401 });
    const res = await audit(req("?assetId=p:1", ""));
    expect(proxy.mock.calls[0][1].cookie).toBe("");
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ error: "auth_required" });
  });

  it("reports an unreachable backend as 503, never as data", async () => {
    proxy.mockRejectedValue(new Error("ECONNREFUSED"));
    const res = await audit(req("?assetId=p:1"));
    expect(res.status).toBe(503);
    expect((await res.json()).error).toBe("sharp_roster_percentage_unavailable");
  });
});
