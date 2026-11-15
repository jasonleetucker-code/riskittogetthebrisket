// W20-F001: the /api/gameplan Next bridge forwards the session cookie and only the
// leagueKey / team query, so the backend enforces league access.
import { describe, it, expect, vi, beforeEach } from "vitest";

const proxyGet = vi.fn();
vi.mock("@/lib/backend-proxy", () => ({ proxyGet: (...a) => proxyGet(...a) }));

import { GET } from "@/app/api/gameplan/route";

function req(qs, cookie = "session=abc") {
  return {
    nextUrl: { searchParams: new URLSearchParams(qs) },
    headers: { get: (k) => (k.toLowerCase() === "cookie" ? cookie : null) },
  };
}

describe("/api/gameplan bridge", () => {
  beforeEach(() => {
    proxyGet.mockReset();
  });

  it("forwards cookie, leagueKey and team (and drops other params)", async () => {
    proxyGet.mockResolvedValue({ data: { ok: 1 }, status: 200 });
    const res = await GET(req("leagueKey=dynasty_main&team=o1&partner=o2&x=y"));
    expect(res.status).toBe(200);
    const [path, opts] = proxyGet.mock.calls[0];
    expect(path).toBe("/api/gameplan");
    expect(opts.cookie).toBe("session=abc");
    expect(opts.searchParams).toEqual({ leagueKey: "dynasty_main", team: "o1" });
  });

  it("passes backend auth/refusal statuses through unchanged", async () => {
    for (const status of [401, 403, 503]) {
      proxyGet.mockResolvedValue({ data: { error: "x" }, status });
      expect((await GET(req("team=o1"))).status).toBe(status);
    }
  });

  it("answers 503 when the backend is unreachable", async () => {
    proxyGet.mockImplementation(async () => {
      throw new Error("down");
    });
    const res = await GET(req("team=o1"));
    expect(res.status).toBe(503);
    expect((await res.json()).error).toBe("gameplan_unavailable");
  });
});
