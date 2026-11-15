import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. Leaderboards (Manager Intelligence Batch F) are private; a
// league population reads one league in full, so it shares the league
// scouting bridge's timeout.
export async function GET(request) {
  try {
    const searchParams = {};
    for (const key of ["population", "leagueId", "window"]) {
      const value = request?.nextUrl?.searchParams?.get(key);
      if (value) searchParams[key] = value;
    }
    const { data, status } = await proxyGet("/api/manager-intel/leaderboard", {
      cookie: request.headers.get("cookie") || "",
      searchParams,
      timeoutMs: 90000,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      {
        error: "upstream_unavailable",
        message: "Manager Intelligence is unavailable.",
        detail: err?.message,
      },
      { status: 503 },
    );
  }
}
