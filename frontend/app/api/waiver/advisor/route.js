// Dev bridge for POST /api/waiver/advisor (Waiver Advisor, Workstream E).
//
// Mirrors frontend/app/api/waiver/perfect/route.js — in production nginx
// routes /api/* straight to FastAPI and this file is never reached; it exists
// so `npm run dev` works without a reverse proxy.
//
// LEAGUE-SCOPED and TEAM-SCOPED: ``leagueKey`` / ``teamOwnerId`` /
// ``position`` / ``limit`` ride in the body and are forwarded verbatim with the
// session cookie.  Status and body pass through unchanged — including the
// ``503 feature_disabled`` (flag ``waiver_advisor`` off) and a plain 404 (route
// not registered yet), which the page reads as "not available".
//
// Mirrored backend endpoint: server.py::post_waiver_advisor() (coordinator hook)
// Composer: src/waivers/advisor.py::compute_waiver_advisor()
import { NextResponse } from "next/server";

const WAIVER_ADVISOR_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/waiver/advisor`;
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
  // Perfect Waivers' exact search is bounded server-side; this only guards a hung backend.
  const timer = setTimeout(() => ctl.abort(), 30_000);
  try {
    const res = await fetch(WAIVER_ADVISOR_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", Cookie: cookie },
      body: JSON.stringify(body),
      signal: ctl.signal,
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status, headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    return NextResponse.json(
      { error: "waiver_advisor_unavailable", detail: err?.message },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}
