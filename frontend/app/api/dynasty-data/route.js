import { NextResponse } from "next/server";

// Backend origin (scheme + host) resolved once at module load.  We
// build the ``/api/data`` URL per-request so the caller's view /
// leagueKey query params are forwarded to the backend.
const BACKEND_ORIGIN = (() => {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000/api/data";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
})();

// NOTE ON DEPLOYMENT SCOPE: in production, nginx routes every ``/api/*``
// request (including ``/api/dynasty-data``) straight to the Python
// backend — see ``deploy/nginx/chaseupside-proxy.conf`` (the shared
// location snippet) and ``deploy/nginx/riskittogetthebrisket.org.conf``,
// where ``server.py::get_dynasty_data_alias`` already honors the
// caller's ``view``/``leagueKey``.  This Next route only handles the dev
// flow (no nginx in front), the E2E stack, and any Next-fronted
// deployment.
//
// That asymmetry is exactly what let audit finding F-14 hide, and it is
// the same asymmetry documented in
// ``frontend/__tests__/bridge-routes-forward-cookies.test.js``:
// production is fine, so a defect here is quietly invisible.

// THE DISK FALLBACK IS GONE (audit F-14, 2026-08-18).
//
// This route used to answer ``NextResponse.json(loadFromDisk())`` — an
// unconditional **HTTP 200** — whenever the backend returned any non-2xx
// status, a non-JSON 200, or stalled at header time.  Two defects, and
// the first is the serious one:
//
//  (a) A REFUSAL WAS CONVERTED INTO A GRANT.  ``401`` is non-2xx, so an
//      unauthenticated caller received the board off disk under 200.
//      ``frontend/middleware.js``'s matcher excludes ``api/`` by design —
//      the backend's own ``/api/*`` gate is meant to be the authority —
//      so the fallback overrode the only gate there was.  Measured
//      against a live stack: unauthenticated request → 200 / 635,170
//      bytes while the backend answered 401, byte-identical to the disk
//      file.
//
//  (b) IT COULD NOT SERVE A BOARD ANYWAY.  Every candidate the loader
//      could reach — ``exports/latest/dynasty_data_*.json``,
//      ``data/dynasty_data_*.json`` and ``dynasty_data.js`` — is the RAW
//      SCRAPER EXPORT: measured 2026-08-18, all three carry no
//      ``contractVersion``, no ``playersArray`` and ZERO rank stamps,
//      which is precisely what ``buildRows``' fail-fast rejects.  So the
//      "resilience" path turned a diagnosable backend status into an
//      undiagnosable empty board, under a status code that said
//      everything was fine.
//
// The backend's answer is now propagated verbatim, and a genuine
// transport failure is reported AS a failure.  MISSING IS NEVER ZERO,
// at the HTTP layer: "here is the board" and "I could not get the
// board" must not share a status code.

// Idle (per-chunk) timeout: abort if the backend stalls for this long
// without sending data, at header time OR mid-body.  Using an inactivity
// timeout rather than a total-duration cap means a legitimately slow but
// live transfer isn't killed, while a genuine stall still unblocks.
const BACKEND_IDLE_TIMEOUT_MS = 4000;

// Headers worth forwarding from the backend response.  We intentionally
// DROP ``content-encoding``: undici exposes ``res.body`` as the DECODED
// stream, so re-advertising gzip would corrupt it — Next.js re-compresses
// on the way out.
const PASS_THROUGH_HEADERS = ["content-type", "cache-control", "etag", "vary"];

// Headers that must survive on an ERROR response too, or the caller
// cannot act on it.  ``www-authenticate`` is the one that matters: a 401
// without it is a refusal with no stated challenge.
const PASS_THROUGH_ERROR_HEADERS = ["content-type", "www-authenticate"];

function backendDataUrl(reqUrl) {
  const incoming = new URL(reqUrl);
  const target = new URL(`${BACKEND_ORIGIN}/api/data`);
  // Forward the params that actually change the payload the backend
  // serves.  ``view`` is the big one — mobile / slow-network callers
  // ask for the compact view, which the previous proxy silently dropped
  // by always requesting the default.
  for (const key of ["view", "leagueKey"]) {
    const val = incoming.searchParams.get(key);
    if (val) target.searchParams.set(key, val);
  }
  if (!target.searchParams.has("view")) target.searchParams.set("view", "app");
  return target.toString();
}

// Fetch the backend response with an idle timeout that covers ONLY the
// header phase.  A header-time stall aborts and returns null; the caller
// then reports a transport failure rather than inventing a body.  Once
// headers arrive the timer is cleared; the body phase gets its own
// per-read idle timeout (see ``streamWithUpstreamIdleAbort``) so header
// latency doesn't eat into the first body chunk's budget.
async function fetchFromBackendApi(request, backendUrl) {
  const ctl = new AbortController();
  const headerTimer = setTimeout(() => ctl.abort(), BACKEND_IDLE_TIMEOUT_MS);
  try {
    const headers = {};
    const cookie = request.headers.get("cookie");
    if (cookie) headers.Cookie = cookie;
    // Forward conditional-revalidation headers so an unchanged payload
    // can round-trip as a 304 instead of re-sending the full contract.
    const inm = request.headers.get("if-none-match");
    if (inm) headers["If-None-Match"] = inm;
    const res = await fetch(backendUrl, {
      cache: "no-store",
      signal: ctl.signal,
      headers,
    });
    clearTimeout(headerTimer);
    return { res, ctl };
  } catch (err) {
    clearTimeout(headerTimer);
    return { res: null, ctl, error: err };
  }
}

// Stream the backend body through unchanged, timing out only while an
// UPSTREAM read is actually in flight.  ``pull`` runs solely when the
// downstream (client) is ready for more, so a slow client applying
// backpressure never has a timer running against it — only a genuine
// backend stall between chunks trips the abort.  Each read gets a fresh
// full idle window, including the first body chunk after headers.
function streamWithUpstreamIdleAbort(res, ctl) {
  const reader = res.body.getReader();
  return new ReadableStream({
    async pull(controller) {
      let timer;
      try {
        const idle = new Promise((_, reject) => {
          timer = setTimeout(() => {
            ctl.abort();
            reject(new Error("backend idle timeout"));
          }, BACKEND_IDLE_TIMEOUT_MS);
        });
        const { done, value } = await Promise.race([reader.read(), idle]);
        clearTimeout(timer);
        if (done) {
          controller.close();
          return;
        }
        controller.enqueue(value);
      } catch (err) {
        clearTimeout(timer);
        try {
          ctl.abort();
        } catch {
          /* already aborted */
        }
        controller.error(err);
      }
    },
    cancel(reason) {
      try {
        ctl.abort();
      } catch {
        /* already aborted */
      }
      return reader.cancel(reason);
    },
  });
}

// Copy the response headers we forward downstream (content-type,
// cache-control, etag, vary — never content-encoding; see note above).
function passThroughHeaders(res, names = PASS_THROUGH_HEADERS) {
  const headers = new Headers();
  for (const h of names) {
    const v = res.headers.get(h);
    if (v) headers.set(h, v);
  }
  return headers;
}

export async function GET(request) {
  try {
    const backendUrl = backendDataUrl(request.url);
    const { res, ctl, error } = await fetchFromBackendApi(request, backendUrl);

    // Transport failure or a header-time stall.  We have no answer, and
    // saying so is the answer — never a 200 with a substitute body.
    if (!res) {
      return NextResponse.json(
        {
          ok: false,
          error: "backend unreachable or stalled",
          reason: error?.name === "AbortError" ? "backend_idle_timeout" : "backend_unreachable",
          timeoutMs: BACKEND_IDLE_TIMEOUT_MS,
        },
        { status: 503, headers: { "Cache-Control": "no-store" } },
      );
    }

    // Conditional hit — no body to stream.
    if (res.status === 304) {
      return new NextResponse(null, { status: 304, headers: passThroughHeaders(res) });
    }

    const contentType = res.headers.get("content-type") || "";
    const isJson = /\bapplication\/json\b/i.test(contentType);

    if (res.ok && isJson) {
      if (!res.body) {
        return new NextResponse(null, { status: res.status, headers: passThroughHeaders(res) });
      }
      // Stream the body with a per-read (upstream-only) idle timeout.
      return new NextResponse(streamWithUpstreamIdleAbort(res, ctl), {
        status: res.status,
        headers: passThroughHeaders(res),
      });
    }

    // A 200 that is not JSON — an HTML gateway page, an error
    // interstitial, a scalar.  The upstream answered, but not with the
    // contract, and that is a BAD GATEWAY, not a cue to invent one.
    if (res.ok) {
      try {
        ctl.abort();
      } catch {
        /* already aborted */
      }
      return NextResponse.json(
        {
          ok: false,
          error: "backend returned a non-JSON 200",
          reason: "backend_non_json",
          contentType,
        },
        { status: 502, headers: { "Cache-Control": "no-store" } },
      );
    }

    // Any other non-2xx — 401, 403, 404, 5xx — is the BACKEND'S ANSWER
    // and it is propagated.  A refusal is an answer, not a failure: the
    // backend's ``/api/*`` gate is the only authority here (Next's
    // middleware matcher deliberately excludes ``api/``), so converting
    // its 401 into anything else is an authentication bypass.
    const body = await res.text().catch(() => "");
    return new NextResponse(body || null, {
      status: res.status,
      headers: passThroughHeaders(res, PASS_THROUGH_ERROR_HEADERS),
    });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: err?.message || "Unknown server error", reason: "bridge_exception" },
      { status: 500, headers: { "Cache-Control": "no-store" } },
    );
  }
}
