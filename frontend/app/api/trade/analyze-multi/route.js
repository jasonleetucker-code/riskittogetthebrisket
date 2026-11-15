// Dev bridge for POST /api/trade/analyze-multi (N-team Analyze Trade, owner
// directive 2026-10-20 §7; spec docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §3.1).
//
// In production nginx routes /api/* straight to the backend; this file exists
// so `npm run dev` / `next start` without a reverse proxy can reach it.  It
// forwards the session cookie (the route is private and 401s without it) and
// passes status and body through verbatim — including the
// `503 multi_team_analysis_disabled` answer the /trade page probes for.  The
// abort timeout matches the War Room's 90 s ceiling.
import { NextResponse } from "next/server";

const ANALYZE_MULTI_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/trade/analyze-multi`;
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
    const res = await fetch(ANALYZE_MULTI_URL, {
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
