// Dev-only bridge to the FastAPI backend.  In production nginx routes
// /api/* straight to the backend and this file is never reached.
import { NextResponse } from "next/server";

import { proxyGet } from "@/lib/backend-proxy";

export async function GET(request) {
  try {
    const searchParams = {};
    for (const key of ["leagueKey", "ownerId", "rosterId", "teamName"]) {
      const value = request?.nextUrl?.searchParams?.get(key);
      if (value) searchParams[key] = value;
    }
    // The cut ladder runs the lineup solver over a full roster; allow more
    // than the 5s default for a cold build.
    const { data, status } = await proxyGet("/api/draft/roster-context", {
      searchParams,
      timeoutMs: 30000,
    });
    // Upstream status passes through verbatim so the client's failure
    // classifier can tell "flag off" from "wrong league" from "broken".
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "draft_context_unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}
