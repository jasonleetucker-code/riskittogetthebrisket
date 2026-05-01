import { NextResponse } from "next/server";

// Single-article proxy — forwards
// GET /api/league/articles/<season>/<week>/<matchupId>/<mode>
// to the FastAPI backend. Mirrors the index proxy
// (../../../../route.js); see that file for the rationale.

const BACKEND_BASE = (() => {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
})();

export async function GET(req, { params }) {
  const { season, week, matchupId, mode } = await params;
  const target = `${BACKEND_BASE}/api/league/articles/${encodeURIComponent(season)}/${encodeURIComponent(week)}/${encodeURIComponent(matchupId)}/${encodeURIComponent(mode)}`;
  try {
    const res = await fetch(target, { cache: "no-store" });
    const body = await res.text();
    const headers = new Headers();
    const ct = res.headers.get("content-type");
    if (ct) headers.set("content-type", ct);
    const cc = res.headers.get("cache-control");
    if (cc) headers.set("cache-control", cc);
    return new NextResponse(body, { status: res.status, headers });
  } catch (err) {
    return NextResponse.json(
      { error: `League article backend unreachable: ${err?.message || err}` },
      { status: 503 },
    );
  }
}
