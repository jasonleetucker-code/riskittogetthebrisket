// Dev bridge for POST /api/waiver/suggestions.
//
// Mirrors the angle/find + trade/finder proxies exactly — in production
// nginx routes /api/* straight to FastAPI and this file is never
// reached; it exists so `npm run dev` works without a reverse proxy in
// front, and so the /waivers FAAB column isn't dev-only-blank.
//
// LEAGUE-SCOPED.  ``leagueKey`` rides in the body (the POST convention
// in this codebase) and is forwarded verbatim along with the session
// cookie — the backend resolver needs both to answer for the right
// league's rosters.
//
// Mirrored backend endpoint: server.py::post_waiver_suggestions()
// Payload builder: src/trade/waiver.py::find_waiver_targets()
import { NextResponse } from "next/server";

const SUGGESTIONS_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/waiver/suggestions`;
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
  // One pass over playersArray plus the FAAB engine's anchor solve —
  // the same order of work as angle/find, so the same 10s ceiling.
  const timer = setTimeout(() => ctl.abort(), 10_000);
  try {
    const res = await fetch(SUGGESTIONS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", Cookie: cookie },
      body: JSON.stringify(body),
      signal: ctl.signal,
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    // The caller treats any non-2xx as "no bids" and hides the column,
    // so a shaped 503 is enough — never an unhandled throw.
    return NextResponse.json(
      { error: "Waiver suggestion service unavailable", detail: err?.message },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}
