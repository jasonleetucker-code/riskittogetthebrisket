// The one way a SERVER component talks to the FastAPI backend.
//
// Every server-side caller had the same shape:
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

const DEFAULT_TIMEOUT_MS = 8000;

// 8 s is `VERIFY_CURL_TIMEOUT` from `deploy/verify-deploy.sh` — this
// repo's already-declared "the backend should have answered by now"
// budget for the deploy's own probes.  Reused rather than invented so
// there is one number to move.
//
// It is deliberately NOT the 20 s that `deploy.yml`'s smoke test allows
// `/api/public/league`.  That allowance exists because the public-league
// snapshot is ALWAYS cold right after a restart — the first request
// kicks a multi-season Sleeper rebuild "that can take minutes" — and the
// deploy is willing to WAIT for warm because it is verifying, once.  A
// visitor is not.  When the snapshot is cold the right answer is to give
// up in seconds and let the client fetch it, which is the path this page
// already takes on any other failure.
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
