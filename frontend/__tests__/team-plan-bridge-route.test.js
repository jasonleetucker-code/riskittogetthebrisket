// The /api/team/plan Next bridge (dev / E2E only): forwards the session cookie
// and only the leagueKey / team query, so the backend enforces sign-in, league
// access and the owner-held flag; statuses pass through unchanged so the home
// panel can read a 503 feature_disabled as "no plan".
import { beforeEach, describe, expect, it, vi } from "vitest";

const proxyGet = vi.fn();
vi.mock("@/lib/backend-proxy", () => ({ proxyGet: (...a) => proxyGet(...a) }));

import { GET } from "@/app/api/team/plan/route";
import { TEAM_PLAN_HOOK_ENDPOINT } from "@/components/terminal/useTeamPlan";

function req(qs, cookie = "session=abc") {
  return {
    nextUrl: { searchParams: new URLSearchParams(qs) },
    headers: { get: (k) => (k.toLowerCase() === "cookie" ? cookie : null) },
  };
}

describe("/api/team/plan bridge", () => {
  beforeEach(() => {
    proxyGet.mockReset();
  });

  it("forwards cookie, leagueKey and team on the hook's path (and drops other params)", async () => {
    proxyGet.mockResolvedValue({ data: { ok: 1 }, status: 200 });
    const res = await GET(req("leagueKey=dynasty_main&team=o1&ownerId=o2&x=y"));
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("private, no-store");
    const [path, opts] = proxyGet.mock.calls[0];
    expect(path).toBe("/api/team/plan");
    expect(path).toBe(TEAM_PLAN_HOOK_ENDPOINT);
    expect(opts.cookie).toBe("session=abc");
    expect(opts.searchParams).toEqual({ leagueKey: "dynasty_main", team: "o1" });
  });

  it("passes backend statuses and bodies through unchanged (flag off included)", async () => {
    for (const [status, error] of [
      [503, "feature_disabled"],
      [401, "auth_required"],
      [404, "team_not_found"],
      [400, "team_required"],
    ]) {
      proxyGet.mockResolvedValue({ data: { error }, status });
      const res = await GET(req("team=o1"));
      expect(res.status).toBe(status);
      expect((await res.json()).error).toBe(error);
    }
  });

  it("answers a stable 503 code without echoing the exception", async () => {
    proxyGet.mockImplementation(async () => {
      throw new Error("connect ECONNREFUSED 10.0.0.1:8000");
    });
    const res = await GET(req("team=o1"));
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "team_plan_unavailable" });
  });
});
