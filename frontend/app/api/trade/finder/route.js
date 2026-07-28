// Dev bridge for POST /api/trade/finder.
//
// Mirrors the angle/find proxy exactly — in production nginx routes
// /api/* straight to the backend and this file is never reached; it
// exists so `npm run dev` works without a reverse proxy in front.
//
// The finder scans every roster pair and can take a few seconds on a
// full 12-team "all opponents" run, so the abort timeout is longer than
// the 10s the angle routes use.
import { NextResponse } from "next/server";

const FINDER_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/trade/finder`;
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
  const timer = setTimeout(() => ctl.abort(), 30_000);
  try {
    const res = await fetch(FINDER_URL, {
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
      { error: "Trade finder service unavailable", detail: err?.message },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}
