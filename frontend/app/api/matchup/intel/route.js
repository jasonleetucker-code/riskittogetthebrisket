import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. The backend fetches the league-week from Sleeper (through the
// shared 60s cache), resolves every roster and runs a league-wide
// simulation, so the timeout matches the other engine bridges rather than
// the fast ones.
//
// `no-store` on the way back out: this payload is projections, win
// probabilities and roster weaknesses, which CLAUDE.md §5 puts on the
// private side. The backend already sets it; setting it here too means a
// dev running through the bridge gets the same guarantee as production.
export async function GET(request) {
  try {
    const searchParams = {};
    for (const key of ["leagueKey", "team", "season", "week"]) {
      const value = request?.nextUrl?.searchParams?.get(key);
      if (value) searchParams[key] = value;
    }
    const { data, status } = await proxyGet("/api/matchup/intel", {
      cookie: request.headers.get("cookie") || "",
      searchParams,
      timeoutMs: 30000,
    });
    return NextResponse.json(data, {
      status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err) {
    return NextResponse.json(
      { error: "matchup_intel_unavailable", detail: err?.message },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
