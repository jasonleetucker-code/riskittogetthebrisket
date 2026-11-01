// Dev bridge for GET /api/roster-construction (Roster Construction V1, owner
// directive 2026-10-30).
//
// In production nginx routes /api/* straight to FastAPI and this file is
// never reached; it exists so `npm run dev` and the E2E stack work without a
// reverse proxy.
//
// LEAGUE-SCOPED and TEAM-SCOPED: only ``leagueKey`` / ``season`` /
// ``rosterId`` are forwarded (an allowlist), with the session cookie.  Status
// and body pass through unchanged — including the ``503 feature_disabled``
// (flag ``roster_construction`` off) and a plain 404 (route not registered
// yet), which the page reads as "not available".
//
// Mirrored backend endpoint: GET /api/roster-construction
// Composer: src/api/roster_construction_api.py
import { NextResponse } from "next/server";

const ROSTER_CONSTRUCTION_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/roster-construction`;
})();

const FORWARDED = ["leagueKey", "season", "rosterId"];

export async function GET(request) {
  const query = new URLSearchParams();
  for (const key of FORWARDED) {
    const value = request?.nextUrl?.searchParams?.get(key);
    if (value) query.set(key, value);
  }
  const cookie = request.headers.get("cookie") || "";
  const ctl = new AbortController();
  // The season solve is server-side and cached; this only guards a hung backend.
  const timer = setTimeout(() => ctl.abort(), 30_000);
  try {
    const qs = query.toString();
    const res = await fetch(qs ? `${ROSTER_CONSTRUCTION_URL}?${qs}` : ROSTER_CONSTRUCTION_URL, {
      method: "GET",
      headers: { Cookie: cookie },
      signal: ctl.signal,
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, {
      status: res.status,
      headers: { "Cache-Control": "private, no-store" },
    });
  } catch {
    // A stable code only — the bridge never echoes an exception message.
    return NextResponse.json({ error: "roster_construction_unavailable" }, { status: 503 });
  } finally {
    clearTimeout(timer);
  }
}
