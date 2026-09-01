// Dev bridge for POST /api/waiver/best-available-idp.
//
// Mirrors frontend/app/api/waiver/suggestions/route.js exactly — in
// production nginx routes /api/* straight to FastAPI and this file is
// never reached; it exists so `npm run dev` works without a reverse
// proxy in front.
//
// LEAGUE-SCOPED. ``leagueKey`` rides in the body (the POST convention in
// this codebase) and is forwarded verbatim along with the session cookie.
//
// Mirrored backend endpoint: server.py::post_waiver_best_available_idp()
// Payload builder: src/trade/waiver_idp_best_available.py::best_available_idp()
import { NextResponse } from "next/server";

const BEST_AVAILABLE_IDP_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/waiver/best-available-idp`;
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
  const timer = setTimeout(() => ctl.abort(), 10_000);
  try {
    const res = await fetch(BEST_AVAILABLE_IDP_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", Cookie: cookie },
      body: JSON.stringify(body),
      signal: ctl.signal,
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    // The caller treats any non-2xx as "unavailable" and shows a
    // degraded state, so a shaped 503 is enough — never an unhandled throw.
    return NextResponse.json(
      { error: "Best-available-IDP service unavailable", detail: err?.message },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}
