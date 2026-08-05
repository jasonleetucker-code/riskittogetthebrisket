/**
 * Shared backend proxy utility for Next.js API routes.
 * All backend requests go through here for consistent URL resolution and error handling.
 */

const BACKEND_BASE = (() => {
  const raw = process.env.BACKEND_API_URL || "http://127.0.0.1:8000/api/data";
  // Strip trailing /api/data if present to get the base
  return raw.replace(/\/api\/data\/?$/, "");
})();

/**
 * Proxy a GET request to the backend.
 *
 * `cookie` is REQUIRED for any backend endpoint behind auth. This helper
 * sends no credentials of its own, so omitting it against an authenticated
 * endpoint yields a 401 — and only where Next actually serves `/api/*`
 * (dev, and the E2E stack, which runs no nginx). In production nginx routes
 * `/api/*` straight to the backend and these routes are never reached, so
 * the failure is invisible in prod and looks like a broken feature in dev.
 * Pass `request.headers.get("cookie")` from the route handler.
 *
 * @param {string} path — backend path (e.g. "/api/draft-capital")
 * @param {object} opts — { timeoutMs, searchParams, cookie }
 */
export async function proxyGet(path, { timeoutMs = 5000, searchParams, cookie } = {}) {
  const url = new URL(path, BACKEND_BASE);
  if (searchParams) {
    for (const [k, v] of Object.entries(searchParams)) {
      url.searchParams.set(k, v);
    }
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(url.toString(), {
      cache: "no-store",
      signal: ctl.signal,
      ...(cookie ? { headers: { Cookie: cookie } } : {}),
    });
    const data = await res.json();
    return { data, status: res.status };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Proxy a POST request to the backend.
 *
 * `cookie` carries the same requirement as `proxyGet` — see the note there.
 *
 * @param {string} path — backend path
 * @param {object} body — JSON body
 * @param {object} opts — { timeoutMs, cookie }
 */
export async function proxyPost(path, body, { timeoutMs = 8000, cookie } = {}) {
  const url = new URL(path, BACKEND_BASE);
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(url.toString(), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(cookie ? { Cookie: cookie } : {}),
      },
      body: JSON.stringify(body),
      signal: ctl.signal,
      cache: "no-store",
    });
    const data = await res.json();
    return { data, status: res.status };
  } finally {
    clearTimeout(timer);
  }
}
