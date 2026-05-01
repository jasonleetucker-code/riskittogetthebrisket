import { NextResponse } from "next/server";

// League articles proxy — forwards GET /api/league/articles[?season=&week=]
// to the FastAPI backend. Used in environments where Next.js serves
// the app without nginx in front (local dev, Vercel-style preview)
// since the client component fetches a relative ``/api/league/articles``
// path that would otherwise 404 against Next itself.
//
// Public (no auth) because the backend endpoint is public — articles
// are league-shareable content. Generation is admin-only; that path
// goes through a separate proxy.

const BACKEND_BASE = (() => {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
})();

export async function GET(req) {
  const url = new URL(req.url);
  const qs = url.searchParams.toString();
  const target = `${BACKEND_BASE}/api/league/articles${qs ? `?${qs}` : ""}`;
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
      { error: `League articles backend unreachable: ${err?.message || err}` },
      { status: 503 },
    );
  }
}
