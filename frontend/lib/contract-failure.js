/**
 * Why the player contract did not load — as a state, not a sentence.
 *
 * THE DEFECT THIS REPLACES
 * ────────────────────────
 * `_fetchBaseContractNetwork` threw `new Error(\`Failed to load dynasty
 * data: ${res.status} ${txt}\`)`, and `useDynastyData` recovered the status
 * from it with a REGEX — `/\b401\b/` against the message text. Everything
 * else about the failure was gone by the time any component saw it:
 *
 *   * a 503 (backend degraded, or scoring identity unprovable — a real,
 *     expected state this app has a whole invariant about),
 *   * a 403 (no handling anywhere),
 *   * a 500,
 *   * and a network timeout
 *
 * were one indistinguishable string, so eight routes rendered the same
 * "something went wrong" for four different situations that want four
 * different things from the user. `/login` in particular turned a 429 or a
 * 503 into "Invalid username or password."
 *
 * A regex over a message is also fragile in the direction that fails
 * silently: a player named "401" in the response body would have
 * triggered the sign-out redirect.
 *
 * THE PATTERN
 * ───────────
 * Deliberately the same shape as `classifyBdvmFailure` (`lib/bdvm.js`) and
 * `classifyEdgeFailure` (`lib/consensus-edge.js`), which already do this
 * correctly for their endpoints. Three classifiers with one shape is a
 * pattern; a fourth shape would be a dialect.
 *
 * MISSING IS NOT FAILED
 * ─────────────────────
 * `empty` is its own kind. A contract that arrives, parses, and contains
 * no players is not an error — it is a backend that has not finished its
 * first scrape, and telling the user "something went wrong" invites them
 * to retry something that is already working. It is separated from
 * `no_data` (nothing arrived at all) for the same reason.
 */

/** Statuses that mean "the server is up and saying no", not "it broke". */
const AUTH_STATUSES = new Set([401, 403]);

/**
 * Classify a contract-fetch failure.
 *
 * @param {number|null} status HTTP status, or null when the request never
 *   produced one (network error, abort, DNS, TLS).
 * @param {object|string|null} body parsed body if there was one
 * @returns {{kind: string, message: string, retryable: boolean}}
 *
 * `kind` is one of:
 *   "auth"        — 401: signed out, or never signed in
 *   "forbidden"   — 403: signed in, not permitted
 *   "degraded"    — 503 with a body: the server is up and explaining itself
 *   "unavailable" — 503/502/504 with nothing useful: upstream is down
 *   "rate_limited"— 429
 *   "offline"     — no status at all: the request never reached a server
 *   "server"      — any other 5xx
 *   "error"       — anything else, including a 4xx we have no name for
 */
export function classifyContractFailure(status, body) {
  const code =
    body && typeof body === "object" && typeof body.error === "string"
      ? body.error
      : "";
  const message =
    (body && typeof body === "object" && (body.message || body.detail)) ||
    (typeof body === "string" ? body.slice(0, 300) : "") ||
    "";

  if (status == null) {
    return {
      kind: "offline",
      code,
      message: message || "Could not reach the server.",
      retryable: true,
    };
  }
  if (status === 401) {
    return { kind: "auth", code, message: message || "Sign in to continue.", retryable: false };
  }
  if (AUTH_STATUSES.has(status)) {
    return {
      kind: "forbidden",
      code,
      message: message || "This account cannot see this data.",
      retryable: false,
    };
  }
  if (status === 429) {
    return {
      kind: "rate_limited",
      code,
      message: message || "Too many requests — wait a moment and retry.",
      retryable: true,
    };
  }
  if (status === 503) {
    // A 503 that explains itself is DEGRADED, not down: the server is
    // running and declining for a stated reason — the scoring-identity
    // gate, a contract that is not loaded yet. Those want a different
    // sentence from "the backend is unreachable", and one of them is not
    // even a fault.
    if (code || message) {
      return { kind: "degraded", code, message, retryable: true };
    }
    return { kind: "unavailable", code, message: "", retryable: true };
  }
  if (status === 502 || status === 504) {
    return { kind: "unavailable", code, message, retryable: true };
  }
  if (status >= 500) {
    return { kind: "server", code, message: message || `Server error (${status}).`, retryable: true };
  }
  return { kind: "error", code, message: message || `HTTP ${status}`, retryable: false };
}

/**
 * Classify a contract that ARRIVED. Returns null when it is fine.
 *
 * Kept beside the transport classifier because a caller has to ask both
 * questions and there is no good reason to make them import from two
 * places to do it.
 */
export function classifyContractPayload(data) {
  if (!data || typeof data !== "object") {
    return {
      kind: "no_data",
      code: "",
      message: "No data received from the server.",
      retryable: true,
    };
  }
  const hasArray = Array.isArray(data.playersArray) && data.playersArray.length > 0;
  const hasDict =
    data.players && typeof data.players === "object" && Object.keys(data.players).length > 0;
  if (!hasArray && !hasDict) {
    return {
      kind: "empty",
      code: "",
      // Not phrased as a failure. The commonest cause is a backend that
      // has not completed its first scrape, which resolves on its own.
      message: "The board has no players yet — the pipeline may still be starting up.",
      retryable: true,
    };
  }
  return null;
}

/**
 * Should a 401 send the user to /login?
 *
 * Extracted so the rule is testable and stated once. It is deliberately
 * NARROW: the redirect exists for one bug — `useAuth`'s cache saying
 * "signed in" while every fetch 401s — and firing it more widely would
 * bounce anonymous visitors off the public routes that hydrate this hook
 * without requiring auth.
 */
export function shouldRedirectToLogin(failure, { hadAuthCache, pathname }) {
  if (!failure || failure.kind !== "auth") return false;
  if (!hadAuthCache) return false;
  const path = pathname || "";
  if (path === "/login" || path.startsWith("/login/")) return false;
  return true;
}
