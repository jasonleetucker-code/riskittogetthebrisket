// Dev / E2E bridge for POST /api/trade/title-odds (the War Room's season-odds
// panel, DYN10 #4; src/trade/title_odds_lens.py behind the owner-held flag
// `trade_title_odds_lens`).
//
// In production nginx routes /api/* straight to the backend; this file exists
// so `npm run dev` / `next start` without a reverse proxy — the E2E stack —
// can reach it, exactly like the analyze bridges beside it.  It forwards the
// session cookie (the route is private and 401s without it) and passes status
// and body through verbatim, never caching.  The abort timeout matches the
// panel's 60 s ceiling (the backend bounds its own computation at 40 s).
import { NextResponse } from "next/server";

const TITLE_ODDS_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/trade/title-odds`;
})();

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    body = null;
  }
  const cookie = request.headers.get("cookie") || "";
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 60_000);
  try {
    const res = await fetch(TITLE_ODDS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", Cookie: cookie },
      body: JSON.stringify(body),
      signal: ctl.signal,
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, {
      status: res.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { error: "upstream_unavailable", message: "The season-odds service is unavailable." },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  } finally {
    clearTimeout(timer);
  }
}
