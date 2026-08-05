import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

/**
 * Proxy GET /api/league-comparison to the FastAPI backend.
 *
 * The backend may need to fetch ~4 seasons × thousands of stat rows on
 * a cold cache hit, so we use a generous 60s timeout instead of the
 * default 5s.  Subsequent calls hit the 7-day disk cache and return
 * immediately.
 *
 * Forwards the optional ``refresh`` query param so the user-facing
 * "Recalculate" button can bypass the cache.
 */
export async function GET(request) {
  try {
    const url = new URL(request.url);
    const refresh = url.searchParams.get("refresh");
    const searchParams = refresh ? { refresh } : undefined;
    const { data, status } = await proxyGet("/api/league-comparison", {
      cookie: request.headers.get("cookie") || "",
      timeoutMs: 60000,
      searchParams,
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      {
        error: "League comparison service unavailable",
        detail: err?.message || String(err),
      },
      { status: 503 },
    );
  }
}
