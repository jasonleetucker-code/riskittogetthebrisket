import { NextResponse } from "next/server";

/**
 * Bridge for the backend's ``/api/health`` freshness probe.
 *
 * WHY THIS EXISTS
 * ---------------
 * ``StaleDataBanner`` (rendered on EVERY page — ``app/AppShellWrapper.jsx:94``)
 * polls ``/api/health`` on mount and every 60s to decide whether to warn that
 * the contract has gone stale. There was no route here, so on the Next origin
 * that request 404'd.
 *
 * The banner degrades gracefully by design — ``StaleDataBanner.jsx:57-64``
 * explicitly skips on a 404 rather than flashing a misleading "data stale"
 * warning off a broken probe. So nothing was visibly wrong. But the
 * consequence was that **the stale-data banner could never fire at all** in
 * any Next-fronted topology (local dev, CI). In production nginx routes
 * ``/api/*`` straight to FastAPI, so the banner works there and the gap was
 * invisible.
 *
 * A monitoring surface that silently cannot fire is worse than one that is
 * absent: the absence of a warning read as "data is fresh".
 *
 * It also put two 404s in the browser console on every single page load,
 * which is noise in exactly the place E2E failures are diagnosed — a real
 * CI failure logged ``404, 404, 502, 503, 503, 404, 404`` and each of those
 * 404s had to be run down before the real signal could be read.
 *
 * SCOPE NOTE, same as ``dynasty-data/route.js``: in production nginx sends
 * ``/api/*`` directly to Python, so this route only serves the dev / CI /
 * Next-fronted path. It brings that path in line with production rather than
 * changing production.
 *
 * The 503 pass-through is load-bearing: the backend uses it for its DEGRADED
 * state and still returns a valid JSON body carrying the freshness numbers.
 * ``StaleDataBanner`` special-cases exactly that (``if (!r.ok && r.status !==
 * 503)``), so collapsing it to a generic error would suppress the very
 * warning this endpoint exists to raise.
 */
const BACKEND = process.env.BACKEND_API_URL
  ? new URL(
      "/api/health",
      process.env.BACKEND_API_URL.replace(/\/api\/data$/, ""),
    ).toString()
  : "http://127.0.0.1:8000/api/health";

export async function GET() {
  try {
    const ctl = new AbortController();
    // 15s, matching auth/status. The backend's event loop is measured to
    // stall ~10s under a contract recompute, and a budget below that reports
    // a busy backend as unreachable — see dynasty-data/route.js's note on
    // why the short budgets were a problem. This probe is a tiny JSON body,
    // so waiting costs nothing.
    const timer = setTimeout(() => ctl.abort(), 15000);
    try {
      const res = await fetch(BACKEND, { cache: "no-store", signal: ctl.signal });
      const data = await res.json().catch(() => ({}));
      // Status passed through verbatim so the backend's 503 "degraded"
      // signal survives the hop.
      return NextResponse.json(data, { status: res.status });
    } finally {
      clearTimeout(timer);
    }
  } catch {
    // Deliberately NOT a 503: that code means "degraded, body has real
    // freshness numbers" to this endpoint's only consumer, and this body has
    // none. 502 says the bridge could not reach the backend, which is what
    // happened, and StaleDataBanner then skips instead of inventing a
    // staleness figure it does not have.
    return NextResponse.json(
      { error: "backend_unreachable", origin: "next-bridge" },
      { status: 502 },
    );
  }
}
