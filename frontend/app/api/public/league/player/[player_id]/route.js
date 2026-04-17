import { NextResponse } from "next/server";

// Proxy for /api/public/league/player/<player_id>.

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
  const { player_id } = await params;
  const url = new URL(req.url);
  const qs = url.searchParams.toString();
  const target = `${BACKEND_BASE}/api/public/league/player/${encodeURIComponent(player_id)}${qs ? `?${qs}` : ""}`;
  try {
    const res = await fetch(target, { cache: "no-store" });
    const body = await res.text();
    const headers = new Headers();
    for (const h of ["content-type", "cache-control"]) {
      const v = res.headers.get(h);
      if (v) headers.set(h, v);
    }
    return new NextResponse(body, { status: res.status, headers });
  } catch (err) {
    return NextResponse.json(
      { error: `Public league backend unreachable: ${err?.message || err}` },
      { status: 503 },
    );
  }
}
