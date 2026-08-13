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
  // serialized for the full view, ~1MB for delta) on the Python side.
  //
  // ⚠ THE OLD 15s BUDGET WAS THE ROTATING E2E FLAKE.  Measured on this
  // machine 2026-08-06, a cold `view=delta` recompute took **13.27s** —
  // 88% of the budget, on hardware faster than a GitHub runner.  Over
  // the line the abort below fires and this route synthesizes a 503,
  // which is INDISTINGUISHABLE at the caller from the backend's own
  // 503, so `journey-settings-overrides` reported "overrides endpoint
  // should recompute the blend successfully: expected 200, received
  // 503" and every investigation went looking in `server.py`.
  //
  // It is not there.  `post_rankings_overrides` has exactly two 503
  // branches and NEITHER can fire here: one needs `latest_data` falsy,
  // which implies `has_data: false` and so would have held the CI
  // readiness gate shut (`_prime_latest_payload` swaps the contract to
  // empty for falsy data), and the other needs two scoring profiles to
  // differ, while both registry leagues are `superflex_tep15_ppr1`.
  //
  // 45s is chosen against the measurement (3.4x the observed cold
  // recompute), not by feel.  It is a floor under the flake, NOT a fix
  // for the latency: 13s is a real user-facing wait and the recompute
  // still blocks the event loop (`run_in_threadpool` does not help —
  // the work is CPU-bound pure Python holding the GIL).  That is the
  // architectural item; this is the part that stops a slow response
  // being reported as a broken one.
  const OVERRIDES_TIMEOUT_MS = 45000;
  let aborted = false;
  const startedAt = Date.now();
  const timer = setTimeout(() => {
    aborted = true;
    ctl.abort();
  }, OVERRIDES_TIMEOUT_MS);
  try {
    const cookie = request.headers.get("cookie") || "";
    const headers = { "Content-Type": "application/json" };
    if (cookie) headers.Cookie = cookie;
    const res = await fetch(forwardedUrl.toString(), {
      method: "POST",
      headers,
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
    // Name which side failed.  An unlabelled 503 here reads exactly like
    // the backend's own, and that ambiguity is what made this flake
    // survive three investigations — see the note on the timeout above.
    const elapsedMs = Date.now() - startedAt;
    const isTimeout = aborted || err?.name === "AbortError";
    return NextResponse.json(
      {
        error: isTimeout ? "bridge_timeout" : "backend_unreachable",
        message: isTimeout
          ? `The Next bridge aborted the overrides recompute after ${elapsedMs}ms ` +
            `(budget ${OVERRIDES_TIMEOUT_MS}ms). The backend did not answer in time; ` +
            `this 503 was synthesized HERE, not by server.py.`
          : "Rankings override service unavailable",
        origin: "next-bridge",
        elapsedMs,
        detail: err?.message,
      },
      { status: 503 },
    );
  } finally {
    clearTimeout(timer);
  }
}
