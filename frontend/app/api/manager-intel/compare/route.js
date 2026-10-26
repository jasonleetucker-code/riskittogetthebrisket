import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

// Dev-flow bridge only — in production nginx routes /api/* straight to
// FastAPI. The compare view (Manager Intelligence Batch E) is private; the
// session cookie is forwarded so the backend's auth gate decides. It runs
// two full manager lookups, so it gets the longest bridge timeout.
export async function GET(request) {
  try {
    const searchParams = {};
    for (const key of ["a", "b", "leagueId", "scope", "window"]) {
      const value = request?.nextUrl?.searchParams?.get(key);
      if (value) searchParams[key] = value;
    }
    const { data, status } = await proxyGet("/api/manager-intel/compare", {
      cookie: request.headers.get("cookie") || "",
      searchParams,
      timeoutMs: 180000,
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
