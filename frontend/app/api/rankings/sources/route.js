import { NextResponse } from "next/server";

// Proxies GET requests to the Python backend's rankings source
// registry endpoint.  The frontend statically mirrors this registry
// in `frontend/lib/dynasty-data.js::RANKING_SOURCES`; this route
// exists so dev tools, tests, and registry-parity self-checks can
// fetch the authoritative server registry at runtime without
// reaching into module internals.
//
// Mirrored backend endpoint: server.py::get_rankings_sources()
// Canonical registry: src/api/data_contract.py::_RANKING_SOURCES

const SOURCES_URL = (() => {
  const base = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000").replace(
    /\/api\/data\/?$/,
    "",
  );
  return `${base}/api/rankings/sources`;
})();

export async function GET() {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 3000);
  try {
    const res = await fetch(SOURCES_URL, {
      cache: "no-store",
      signal: ctl.signal,
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, {
      status: res.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err) {
    return NextResponse.json(
      { error: "Rankings source registry unavailable", detail: err?.message },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}
