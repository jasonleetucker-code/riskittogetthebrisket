import { NextResponse } from "next/server";

// Waiver Wire Comparison proxy — forwards to the FastAPI backend
// ``/api/public/waiver-compare``.  Used in dev (in production nginx sends
// /api/* straight to the backend).  INTENTIONALLY unauthenticated: the
// backend endpoint is on its public allowlist and the page is unlisted.

const BACKEND_BASE = (() => {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
})();

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_BASE}/api/public/waiver-compare`, { cache: "no-store" });
    const body = await res.text();
    const headers = new Headers({ "X-Robots-Tag": "noindex, nofollow" });
    const ct = res.headers.get("content-type");
    if (ct) headers.set("content-type", ct);
    const cc = res.headers.get("cache-control");
    if (cc) headers.set("cache-control", cc);
    return new NextResponse(body, { status: res.status, headers });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: `backend_unreachable: ${err?.message || err}` },
      { status: 502 },
    );
  }
}
