import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. The double-positive scan runs on request (200k+ candidate
// packages server-side), hence the long timeout.
export async function GET(request) {
  try {
    const searchParams = {};
    for (const key of ["leagueKey", "team"]) {
      const value = request?.nextUrl?.searchParams?.get(key);
      if (value) searchParams[key] = value;
    }
    const { data, status } = await proxyGet("/api/bdvm/trades", {
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
