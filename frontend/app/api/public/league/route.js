import { NextResponse } from "next/server";

// Public league contract proxy — forwards to the FastAPI backend
// ``/api/public/league`` endpoint.  Used in dev (where nginx is not
// in front of the app) and to ensure the request carries the Next.js
// edge cache-control headers.  This route is INTENTIONALLY public
// (no auth check) because the backend endpoint itself is public.

const BACKEND_BASE = (() => {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    // Strip trailing /api/data if the env var was set for the private
    // route — we want just origin + /api/public/league.
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
})();

export async function GET(req) {
  const url = new URL(req.url);
  const qs = url.searchParams.toString();
  const target = `${BACKEND_BASE}/api/public/league${qs ? `?${qs}` : ""}`;
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
      { error: `Public league backend unreachable: ${err?.message || err}` },
      { status: 503 },
    );
  }
}
