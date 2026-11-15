import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI.  `/api/gameplan` is league-scoped, team-scoped and PRIVATE: the
// session cookie MUST be forwarded so the backend (not this bridge) enforces
// who may read which league.  Only `leagueKey` and `team` are passed on; the
// `partner` parameter (package generator) is deliberately not bridged — the
// /rosters Team Gameplan section does not use it.  A cold league build is
// ~1.9 s, so the timeout matches the other engine bridges.
export async function GET(request) {
  try {
    const searchParams = {};
    for (const key of ["leagueKey", "team"]) {
      const value = request?.nextUrl?.searchParams?.get(key);
      if (value) searchParams[key] = value;
    }
    const { data, status } = await proxyGet("/api/gameplan", {
      cookie: request.headers.get("cookie") || "",
      searchParams,
      timeoutMs: 30000,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "gameplan_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}
