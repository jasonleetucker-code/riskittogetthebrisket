// Dev bridge for POST /api/waiver/perfect (Perfect Waivers, C7-WAIV-01).
//
// Mirrors frontend/app/api/waiver/best-available-idp/route.js — in
// production nginx routes /api/* straight to FastAPI and this file is never
// reached; it exists so `npm run dev` works without a reverse proxy.
//
// LEAGUE-SCOPED and TEAM-SCOPED. ``leagueKey`` and ``teamOwnerId`` ride in
// the body (the POST convention in this codebase) and are forwarded verbatim
// with the session cookie.
//
// Mirrored backend endpoint: server.py::post_waiver_perfect()
// Optimizer: src/trade/perfect_waivers.py::build_perfect_waivers()
import { NextResponse } from "next/server";

const PERFECT_WAIVERS_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/waiver/perfect`;
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
  // The exact search is bounded server-side; this only guards a hung backend.
  const timer = setTimeout(() => ctl.abort(), 30_000);
  try {
    const res = await fetch(PERFECT_WAIVERS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", Cookie: cookie },
      body: JSON.stringify(body),
      signal: ctl.signal,
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { error: "perfect_waivers_unavailable", detail: err?.message },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}
