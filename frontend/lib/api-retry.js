/**
 * Fetch helper with retry + timeout + graceful degradation.
 *
 * Frontend-side partner to src/utils/http_fetch.py — every API
 * call that a failure would visibly break should use this to
 * get consistent retry + timeout semantics without each caller
 * reinventing them.
 *
 * Usage:
 *   const { ok, data, error } = await fetchWithRetry(
 *     "/api/data",
 *     { retries: 1, timeoutMs: 8000, label: "data_fetch" }
 *   );
 *   if (!ok) { showFallback(error); return; }
 *
 * Why not just axios? Axios is 15KB gzipped. For 4 call sites
 * this helper stays at ~60 LOC using native fetch + AbortController.
 */

const DEFAULT_TIMEOUT_MS = 10_000;


export async function fetchWithRetry(url, opts = {}) {
  const {
    retries = 0,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    retryDelayBaseMs = 500,
    label = "fetch",
    init = {},
  } = opts;

  let lastError = null;
  let lastStatus = 0;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(url, { ...init, signal: controller.signal });
      clearTimeout(timer);
      lastStatus = res.status;
      if (!res.ok) {
        // Don't retry on 4xx — caller's fault.
        if (res.status < 500) {
          const body = await _safeJson(res);
          return { ok: false, status: res.status, error: body, data: null };
        }
        lastError = `HTTP ${res.status}`;
        if (attempt < retries) {
          await _sleep(retryDelayBaseMs * Math.pow(2, attempt));
          continue;
        }
        return { ok: false, status: res.status, error: lastError, data: null };
      }
      const data = await _safeJson(res);
      return { ok: true, status: res.status, error: null, data };
    } catch (err) {
      clearTimeout(timer);
      lastError = err?.name === "AbortError" ? "timeout" : (err?.message || "network_error");
      if (attempt < retries) {
        await _sleep(retryDelayBaseMs * Math.pow(2, attempt));
        continue;
      }
      return { ok: false, status: lastStatus, error: lastError, data: null };
    }
  }
  return { ok: false, status: lastStatus, error: lastError || "unknown", data: null };
}


async function _safeJson(res) {
  try {
    return await res.json();
  } catch {
    return null;
  }
}


function _sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
