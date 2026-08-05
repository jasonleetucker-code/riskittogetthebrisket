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
 * @param {string} path — backend path (e.g. "/api/draft-capital")
 * @param {object} opts — { timeoutMs, searchParams }
 */
export async function proxyGet(path, { timeoutMs = 5000, searchParams } = {}) {
  const url = new URL(path, BACKEND_BASE);
  if (searchParams) {
    for (const [k, v] of Object.entries(searchParams)) {
      url.searchParams.set(k, v);
    }
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(url.toString(), { cache: "no-store", signal: ctl.signal });
    const data = await res.json();
    return { data, status: res.status };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Proxy a POST request to the backend.
 * @param {string} path — backend path
 * @param {object} body — JSON body
 * @param {object} opts — { timeoutMs, headers }
 *
 * `headers` is merged over `Content-Type: application/json` and exists
 * for one reason: a backend route behind `_get_auth_session` answers 401
 * to a bridge that drops the session cookie.  Pass
 * `{ cookie: request.headers.get("cookie") }` for those.
 */
export async function proxyPost(path, body, { timeoutMs = 8000, headers } = {}) {
  const url = new URL(path, BACKEND_BASE);
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(url.toString(), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(headers || {}) },
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
