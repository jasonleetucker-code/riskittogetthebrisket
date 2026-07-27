import { NextResponse } from "next/server";

// Proxies the league-adjusted valuation overlay to the Python backend.
//
// In production nginx routes every `/api/*` path straight to the
// backend, so this shim is never hit.  It exists for the dev flow,
// where Next serves `/api/*` itself and the route would otherwise 404 —
// the same reason `rankings/overrides/route.js` and
// `dynasty-data/route.js` exist.
//
// LEAGUE-SCOPED.  The overlay is driven by positional scarcity measured
// from one league's rosters, so `leagueKey` must be forwarded; two
// leagues sharing a scoring profile get different overlays.
//
// Mirrored backend endpoint: server.py::get_league_adjusted_values()
// Payload builder: src/league_intel/publish.py::build_league_adjusted_payload()

const BACKEND_BASE = (
  process.env.BACKEND_API_URL || "http://127.0.0.1:8000"
).replace(/\/api\/data\/?$/, "");
const OVERLAY_URL = `${BACKEND_BASE}/api/valuation/league-adjusted`;

export async function GET(request) {
  const incomingUrl = new URL(request.url);
  const forwardedUrl = new URL(OVERLAY_URL);
  for (const key of ["leagueKey", "explanations"]) {
    const v = incomingUrl.searchParams.get(key);
    if (v) forwardedUrl.searchParams.set(key, v);
  }

  const ctl = new AbortController();
  // The overlay reuses /api/gameplan's cached league bundle, so it is
  // near-free warm but pays the ~1.35 s replacement solve cold. 15 s
  // matches the overrides proxy and leaves room for a cold league.
  const timer = setTimeout(() => ctl.abort(), 15000);
  try {
    const cookie = request.headers.get("cookie") || "";
    const headers = {};
    if (cookie) headers.Cookie = cookie;
    const res = await fetch(forwardedUrl.toString(), {
      headers,
      signal: ctl.signal,
      cache: "no-store",
    });
    const text = await res.text();
    return new Response(text, {
      status: res.status,
      headers: {
        "Content-Type": "application/json",
        // Private, league-scoped data. Never cache at the edge.
        "Cache-Control": "no-store, private",
      },
    });
  } catch (err) {
    // A failed overlay is not a failed page: the caller degrades to the
    // market board. Answer with a shape the client can read rather than
    // an unhandled throw.
    return NextResponse.json(
      { error: "overlay_unavailable", message: String(err?.message || err) },
      { status: 502, headers: { "Cache-Control": "no-store, private" } },
    );
  } finally {
    clearTimeout(timer);
  }
}
