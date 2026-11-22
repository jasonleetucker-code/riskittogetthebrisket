import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge for GET /api/team/plan (composed Team Advisor plan, owner
// directive 2026-11-21, DYN10 items #2 / #5).  In production nginx routes
// /api/* straight to FastAPI and this file is never reached; it exists so
// `npm run dev` and the E2E stack can show the home "This week" panel.
//
// PRIVATE, league-scoped and team-scoped: the session cookie is forwarded so
// the backend (not this bridge) enforces sign-in and league access.  Only
// `leagueKey` and `team` are passed on (an allowlist).  Status and body pass
// through unchanged — including `503 feature_disabled` (owner-held flag
// `team_advisor_plan`, default OFF), which the panel reads as "no plan".
// The plan runs roster intelligence and trade suggestions per request, so
// the timeout matches the other engine bridges.
//
// Mirrored backend endpoint: server.py::get_team_plan
// Composer: src/api/team_plan.py
export async function GET(request) {
  try {
    const searchParams = {};
    for (const key of ["leagueKey", "team"]) {
      const value = request?.nextUrl?.searchParams?.get(key);
      if (value) searchParams[key] = value;
    }
    const { data, status } = await proxyGet("/api/team/plan", {
      cookie: request.headers.get("cookie") || "",
      searchParams,
      timeoutMs: 30000,
    });
    return NextResponse.json(data, {
      status,
      headers: { "Cache-Control": "private, no-store" },
    });
  } catch {
    // A stable code only — the bridge never echoes an exception message.
    return NextResponse.json({ error: "team_plan_unavailable" }, { status: 503 });
  }
}
