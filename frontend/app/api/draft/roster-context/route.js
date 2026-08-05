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
    //
    // The session cookie has to be forwarded: this endpoint is behind auth,
    // and without it the backend answers 401, which the panel classifies as
    // a failure and silent-vanishes on. Production never noticed because
    // nginx routes /api/* past this file entirely — it only bites where Next
    // serves /api/* itself, which is dev and the E2E stack.
    const { data, status } = await proxyGet("/api/draft/roster-context", {
      searchParams,
      timeoutMs: 30000,
      cookie: request.headers.get("cookie") || "",
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
