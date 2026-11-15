// Dev bridge for POST /api/trade/golden-upgrades (C7-GOLD-01).
//
// In production nginx routes /api/* straight to the backend; this file exists
// so `npm run dev` works without a reverse proxy.  It forwards the session
// cookie — the route is private and 401s without it.  The scan checks every
// opponent's roster, so it keeps the finder's long abort budget.
import { NextResponse } from "next/server";

const GOLDEN_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/trade/golden-upgrades`;
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
    const res = await fetch(GOLDEN_URL, {
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
      { error: "Golden-upgrades service unavailable", detail: err?.message },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}
