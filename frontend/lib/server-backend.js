// Bounded backend reads for SERVER-RENDERED pages and metadata.
//
// Scope, stated narrowly because it was overstated once: this covers the
// server components and metadata functions that read the backend during
// a render or a build — `app/league/page.jsx` and `app/sitemap.js`
// today.  It is NOT a consolidation of every frontend-to-backend call.
// The Next API bridge routes under `app/api/**/route.js` also read
// `BACKEND_API_URL` and are deliberately untouched: they run per request
// on behalf of a browser that has its own timeout and retry behaviour,
// they never run during `next build`, and rewriting them would be a
// broad proxy change with none of the evidence that motivated this one.
//
// Every server-side render caller had the same shape:
//
//     try { const res = await fetch(url, {next:{revalidate}}); … }
//     catch { return null }
//
// which handles a REFUSED connection — microseconds, `catch`, `null` —
// and does nothing at all about SILENCE.  Node's `fetch` bounds the
// connect phase and not the response, so a backend that accepts the
// socket and never writes leaves the await pending forever.
//
// That is not hypothetical.  On 2026-08-12 the production FastAPI
// process exhausted its file descriptors (`OSError: [Errno 24] Too many
// open files`, raised from `socket.accept()`), so the kernel completed
// every handshake into the listen backlog and the application answered
// nothing.  `next build` then hung generating /league, gave up after
// 3 x 60 s, and failed the deploy — the deploy that would have restarted
// the wedged process.  Reproduced locally against
// `scripts/hanging-backend.mjs`: byte-identical failure, 225 s.
//
// So: one helper, one bounded budget, one place to change it.
//
// `null` means "no usable answer" and deliberately does not distinguish
// refused / timed out / 500 / malformed.  Every call site already
// branches on exactly that, and the callers' fallback — let the client
// fetch it — is the same in all four cases.  The reason is logged, not
// returned, because a page that renders differently per failure mode is
// four render paths nobody tests.

const DEFAULT_TIMEOUT_MS = 3000;

// This is a VISITOR-FACING budget, so it comes from the site's
// interactive performance standard, not from an operational one:
//
//   <=1 s  warm/cached target
//   <=2 s  normal production p95 where architectural
//   <=3 s  preferred supported cold/useful path
//   <=5 s  absolute interactive useful-state failure ceiling
//
// 3 s is the "cold but still useful" rung, and this fetch is exactly
// that case: the page has a working client-side fallback, so the cost of
// giving up early is one extra client round trip, while the cost of
// waiting is the whole document.  Measured against a hanging backend the
// document completes in ~3.1 s, inside the 5 s ceiling with room spare.
//
// An earlier revision used 8 s, taken from `VERIFY_CURL_TIMEOUT` in
// `deploy/verify-deploy.sh`.  That was the wrong source: it is a DEPLOY
// VERIFICATION budget — a machine confirming a release, once, willing to
// wait — and reusing it here quietly imported an operational tolerance
// into a human-facing path.  It also blew the 5 s ceiling outright
// (8.05 s measured).  Deploy and verification budgets stay independent
// and may be longer; they are not evidence about what a visitor should
// wait.
//
// Same reasoning rules out the 20 s `deploy.yml` allows
// `/api/public/league`.  That exists because the public-league snapshot
// is ALWAYS cold after a restart — the first request kicks a
// multi-season Sleeper rebuild "that can take minutes" — and the deploy
// polls until warm. A visitor cannot be asked to hold that open.
//
// Overridable for an operator who wants to trade latency for SSR
// coverage on a slow box; not something a page should choose per call.
function defaultTimeoutMs() {
  const raw = process.env.BACKEND_SERVER_FETCH_TIMEOUT_MS;
  if (!raw) return DEFAULT_TIMEOUT_MS;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : DEFAULT_TIMEOUT_MS;
}

// Origin only — path and query come from the caller.  Was copy-pasted
// into sitemap.js, league/page.jsx and every league sub-route.
export function backendOrigin() {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

/**
 * Fetch JSON from the backend with a bounded response budget.
 *
 * @param {string} path      absolute path, e.g. "/api/public/league"
 * @param {object} [opts]
 * @param {number} [opts.revalidate]  seconds for Next's Data Cache
 * @param {number} [opts.timeoutMs]   override the default budget
 * @returns {Promise<any|null>} parsed JSON, or null on any failure
 */
export async function fetchBackendJson(path, opts = {}) {
  const { revalidate, timeoutMs } = opts;
  const url = `${backendOrigin()}${path}`;
  const budget = timeoutMs ?? defaultTimeoutMs();

  const init = { signal: AbortSignal.timeout(budget) };
  if (revalidate !== undefined) init.next = { revalidate };

  // `signal` composes with Next's Data Cache: `patch-fetch` forwards it
  // on a live request and drops it when revalidating in the background,
  // and the cache opt-out conditions key on `cache: no-store|no-cache`,
  // not on the presence of a signal.  Verified against next@16.2.12
  // rather than assumed — a helper that silently disabled caching would
  // trade a hang for a 2 MB re-fetch on every render.
  try {
    const res = await fetch(url, init);
    if (!res.ok) {
      console.warn(`[server-backend] ${path} -> HTTP ${res.status}`);
      return null;
    }
    return await res.json();
  } catch (err) {
    // TimeoutError is the case this helper exists for; name it, because
    // "the backend is slow" and "the backend is gone" want different
    // operator responses even though the page renders identically.
    const kind = err?.name === "TimeoutError" ? `no response in ${budget}ms` : err?.name || "error";
    console.warn(`[server-backend] ${path} -> ${kind}`);
    return null;
  }
}
