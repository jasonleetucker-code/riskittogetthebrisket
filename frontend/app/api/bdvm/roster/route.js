import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. Roster analysis rides the cached values payload server-side
// but may trigger the first compute, hence the long timeout.
export async function GET(request) {
  try {
    const searchParams = {};
    const leagueKey = request?.nextUrl?.searchParams?.get("leagueKey");
    if (leagueKey) searchParams.leagueKey = leagueKey;
    const { data, status } = await proxyGet("/api/bdvm/roster", {
      cookie: request.headers.get("cookie") || "",
      searchParams,
      timeoutMs: 30000,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "bdvm_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}
