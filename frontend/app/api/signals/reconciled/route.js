import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. The reconciler (C6-SIG-01) is private, so the session cookie is
// forwarded and the backend's own status (401 included) is passed through
// verbatim: the homepage ticker fails closed on it. The build reads every
// emitter's owner on a cold cache, hence the long timeout.
export async function GET(request) {
  try {
    const searchParams = {};
    for (const key of ["leagueKey", "team", "ownerId", "teamName", "scope", "player"]) {
      const value = request?.nextUrl?.searchParams?.get(key);
      if (value) searchParams[key] = value;
    }
    const { data, status } = await proxyGet("/api/signals/reconciled", {
      cookie: request.headers.get("cookie") || "",
      searchParams,
      timeoutMs: 30000,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "signals_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}
