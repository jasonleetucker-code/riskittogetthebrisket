import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. The backend recomputes the whole league's meaningful core,
// Team Strength, weakness and age portfolio on a cache miss, so the
// timeout matches the other engine bridges rather than the fast ones.
export async function GET(request) {
  try {
    const searchParams = {};
    for (const key of ["leagueKey", "team", "droppability"]) {
      const value = request?.nextUrl?.searchParams?.get(key);
      if (value) searchParams[key] = value;
    }
    const { data, status } = await proxyGet("/api/roster/intelligence", {
      cookie: request.headers.get("cookie") || "",
      searchParams,
      timeoutMs: 30000,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "roster_intelligence_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}
