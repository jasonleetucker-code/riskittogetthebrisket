// Dev / E2E bridge for POST /api/trade/analyze (the 2-team War Room's one
// decision call, src/trade/analyze_trade.py).
//
// In production nginx routes /api/* straight to the backend; this file exists
// so `npm run dev` / `next start` without a reverse proxy — the E2E stack —
// can reach it.  Without it the War Room's request hit Next itself, which has
// no such page, and the room rendered "the server refused the request" on
// every real (unmocked) 2-team trade in the E2E stack.  It forwards the
// session cookie (the route is private and 401s without it) and passes status
// and body through verbatim.  The abort timeout matches the War Room's 90 s
// ceiling, the same as the analyze-multi bridge beside it.
import { NextResponse } from "next/server";

const ANALYZE_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/trade/analyze`;
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
  const timer = setTimeout(() => ctl.abort(), 90_000);
  try {
    const res = await fetch(ANALYZE_URL, {
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
      { error: "upstream_unavailable", message: "The analysis service is unavailable." },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  } finally {
    clearTimeout(timer);
  }
}
