// Dev bridge for POST /api/trade/best-offers (C7-BEST-TRADE).
//
// In production nginx routes /api/* straight to the backend; this file exists
// so `npm run dev` works without a reverse proxy.  It forwards the session
// cookie — the route is private and 401s without it.  A full-league scan
// evaluates every opponent, so the abort timeout matches the finder's long
// budget.
import { NextResponse } from "next/server";

const BEST_OFFERS_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/trade/best-offers`;
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
  const timer = setTimeout(() => ctl.abort(), 45_000);
  try {
    const res = await fetch(BEST_OFFERS_URL, {
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
  } catch (err) {
    return NextResponse.json(
      { error: "Best-offers service unavailable", detail: err?.message },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}
