import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. Manager Scout (C6-MGR-01) is private and league-scoped; the
// session cookie is forwarded so the backend's auth gate decides.
export async function GET(request) {
  try {
    const searchParams = {};
    const leagueKey = request?.nextUrl?.searchParams?.get("leagueKey");
    if (leagueKey) searchParams.leagueKey = leagueKey;
    const { data, status } = await proxyGet("/api/manager-scout", {
      cookie: request.headers.get("cookie") || "",
      searchParams,
      timeoutMs: 30000,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "manager_scout_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}
