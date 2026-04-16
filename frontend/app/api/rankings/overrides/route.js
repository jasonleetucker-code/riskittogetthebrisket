import { NextResponse } from "next/server";

// Proxies POST requests to the Python backend's rankings override
// endpoint.  This is the single authoritative path for custom-source
// configurations — when a user toggles a source off or changes a
// weight in settings, the frontend POSTs the override map here, Next
// forwards it to the Python `POST /api/rankings/overrides` endpoint
// in `server.py`, and the response is either a full canonical
// contract (default) or a compact delta payload (``view=delta``)
// re-computed by `_compute_unified_rankings()` with the overrides
// threaded in.  There is no dual-engine frontend recompute.
//
// Mirrored backend endpoint: server.py::post_rankings_overrides()
// Canonical pipeline: src/api/data_contract.py::_compute_unified_rankings()

const BACKEND_BASE = (process.env.BACKEND_API_URL || "http://127.0.0.1:8000")
  .replace(/\/api\/data\/?$/, "");
const OVERRIDES_URL = `${BACKEND_BASE}/api/rankings/overrides`;

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    body = null;
  }

  // Forward the ``view`` query parameter so the frontend can opt in
  // to the compact ``view=delta`` response shape.  Everything else
  // is dropped on the floor — the backend ignores unknown params.
  const incomingUrl = new URL(request.url);
  const forwardedUrl = new URL(OVERRIDES_URL);
  const view = incomingUrl.searchParams.get("view");
  if (view) forwardedUrl.searchParams.set("view", view);

  const ctl = new AbortController();
  // Override responses rebuild the full canonical contract (~2-5MB
  // serialized for the full view, ~1MB for delta), which takes a
  // few seconds on the Python side.  A 15-second timeout gives the
  // backend room to complete the rebuild for the full dynasty
  // board without clipping legitimate responses.
  const timer = setTimeout(() => ctl.abort(), 15000);
  try {
    const res = await fetch(forwardedUrl.toString(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
      signal: ctl.signal,
      cache: "no-store",
    });
    // Stream the backend response body straight through without a
    // parse+re-serialize hop.  The backend already applies
    // GZipMiddleware so the body may arrive gzipped; fetch()
    // transparently decodes it for us, so we forward the decoded
    // body as plain JSON and let Next.js re-encode for the client.
    // We still read the body as text so we can return it via the
    // plain Response constructor, which preserves Content-Length.
    const bodyText = await res.text();
    return new Response(bodyText, {
      status: res.status,
      headers: {
        "Content-Type": "application/json",
        // Mirror the backend no-store cache policy.  Override
        // responses are per-user and must not be cached at the edge.
        "Cache-Control": "no-store",
        "X-Payload-View": res.headers.get("x-payload-view") || "",
      },
    });
  } catch (err) {
    return NextResponse.json(
      { error: "Rankings override service unavailable", detail: err?.message },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}
