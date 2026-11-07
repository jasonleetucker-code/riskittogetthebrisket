// Dev bridge for POST /api/waiver/streaming (Weekly IDP Streaming, owner
// directive 2026-10-29).
//
// Mirrors frontend/app/api/waiver/advisor/route.js — in production nginx
// routes /api/* straight to FastAPI and this file is never reached; it exists
// so `npm run dev` works without a reverse proxy.
//
// LEAGUE-SCOPED and TEAM-SCOPED: ``leagueKey`` / ``teamOwnerId`` / ``week`` /
// ``horizonWeeks`` / ``position`` / ``capacity`` / ``dynastyBudget`` ride in
// the body and are forwarded verbatim with the session cookie.  Status and
// body pass through unchanged — including the ``503 feature_disabled`` (flag
// ``waiver_advisor`` or ``idp_streaming`` off) and a plain 404 (route not
// registered yet), which the page reads as "no streaming mode".
//
// Mirrored backend endpoint: server.py::post_waiver_streaming()
// Composer: src/waivers/streaming.py::compute_streaming()
import { NextResponse } from "next/server";

const WAIVER_STREAMING_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/waiver/streaming`;
})();

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const cookie = request.headers.get("cookie") || "";
  const ctl = new AbortController();
  // The streaming solver is node-bounded server-side; this only guards a hung backend.
  const timer = setTimeout(() => ctl.abort(), 30_000);
  try {
    const res = await fetch(WAIVER_STREAMING_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", Cookie: cookie },
      body: JSON.stringify(body),
      signal: ctl.signal,
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status, headers: { "Cache-Control": "no-store" } });
  } catch {
    // A stable code only — the bridge never echoes an exception message.
    return NextResponse.json({ error: "idp_streaming_unavailable" }, { status: 503 });
  } finally {
    clearTimeout(timer);
  }
}
