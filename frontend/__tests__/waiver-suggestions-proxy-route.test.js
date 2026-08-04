// Dev-proxy route for POST /api/waiver/suggestions. Without it the
// Next dev server has nothing mounted there (production nginx forwards
// /api/* to FastAPI directly) and the /waivers FAAB column would be
// blank locally for a reason that has nothing to do with the backend.
//
// League-scoped: ``leagueKey`` rides in the body and the session cookie
// has to reach the backend resolver, so both are asserted here.

import { afterEach, describe, it, expect, vi } from "vitest";
import { POST } from "@/app/api/waiver/suggestions/route";

afterEach(() => {
  vi.unstubAllGlobals();
});

function request(body, { cookie = "" } = {}) {
  return {
    json: async () => {
      if (body === undefined) throw new SyntaxError("bad json");
      return body;
    },
    headers: { get: (k) => (k.toLowerCase() === "cookie" ? cookie : null) },
  };
}

function backendResponse(payload, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => payload };
}

describe("POST /api/waiver/suggestions proxy route", () => {
  it("forwards the body and the session cookie to the backend", async () => {
    const fetchMock = vi.fn(async () => backendResponse({ by_position: {}, total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await POST(
      request({ leagueKey: "dynasty_main", faabRemaining: 63 }, { cookie: "session=abc" }),
    );

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/waiver\/suggestions$/);
    expect(init.method).toBe("POST");
    expect(init.headers.Cookie).toBe("session=abc");
    expect(JSON.parse(init.body)).toEqual({ leagueKey: "dynasty_main", faabRemaining: 63 });
    expect(res.status).toBe(200);
  });

  it("passes a backend non-2xx straight through for the caller to hide", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => backendResponse({ error: "data_not_ready" }, 503)));

    const res = await POST(request({ leagueKey: "dynasty_main" }));
    expect(res.status).toBe(503);
    expect((await res.json()).error).toBe("data_not_ready");
  });

  it("rejects an unparseable request body with 400", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await POST(request(undefined));
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("an unreachable backend degrades to a shaped 503, never a throw", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("connect ECONNREFUSED");
      }),
    );

    const res = await POST(request({ leagueKey: "dynasty_main" }));
    expect(res.status).toBe(503);
    expect((await res.json()).error).toBe("Waiver suggestion service unavailable");
  });
});
