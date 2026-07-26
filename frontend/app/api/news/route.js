import { NextResponse } from "next/server";

// Proxies GET /api/news to the Python backend's news aggregator.
//
// DEPLOYMENT SCOPE: in production, nginx routes every ``/api/*``
// request straight to FastAPI (see
// ``deploy/nginx/riskittogetthebrisket.org.conf``), so this route is
// never hit there.  It exists for the dev flow (Next dev server on
// port 3000, no nginx in front) and any Next-fronted deployment —
// without it, the relative ``/api/news`` fetch in
// ``frontend/lib/news-service.js`` 404s against the Next server and
// every news surface reports "unavailable" locally now that the
// mock-fixture fallback is gone.
//
// Mirrors the ``/api/rankings/sources`` proxy convention: build the
// backend URL (forwarding the params that change the payload —
// ``limit`` and the repeatable ``team``), fetch with a timeout,
// pass the backend's status + Cache-Control through.
//
// Mirrored backend endpoint: server.py::get_news()

const BACKEND_ORIGIN = (() => {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
})();

// A cold news cache runs the providers sequentially (each with its
// own ~5s cap), so the aggregate can legitimately take several
// seconds on first hit.  10s keeps a genuinely wedged backend from
// hanging the dev page while giving a cold aggregate room to finish;
// on abort the client sees 503 → its "news unavailable" state, and
// the retry lands on the backend's warm cache.
const BACKEND_TIMEOUT_MS = 10_000;

function backendNewsUrl(reqUrl) {
  const incoming = new URL(reqUrl);
  const target = new URL(`${BACKEND_ORIGIN}/api/news`);
  const limit = incoming.searchParams.get("limit");
  if (limit) target.searchParams.set("limit", limit);
  // ``team`` is repeatable on the backend route.
  for (const team of incoming.searchParams.getAll("team")) {
    target.searchParams.append("team", team);
  }
  return target.toString();
}

export async function GET(request) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), BACKEND_TIMEOUT_MS);
  try {
    const res = await fetch(backendNewsUrl(request.url), {
      cache: "no-store",
      signal: ctl.signal,
    });
    const data = await res.json().catch(() => ({}));
    const headers = {};
    const cacheControl = res.headers.get("cache-control");
    if (cacheControl) headers["Cache-Control"] = cacheControl;
    return NextResponse.json(data, { status: res.status, headers });
  } catch (err) {
    return NextResponse.json(
      {
        items: [],
        providersUsed: [],
        providerRuns: [],
        error: "news_backend_unreachable",
        detail: err?.message,
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  } finally {
    clearTimeout(timer);
  }
}
