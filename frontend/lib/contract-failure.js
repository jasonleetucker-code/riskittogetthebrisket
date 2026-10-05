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
 * A proxy's error PAGE is not a message.  When the backend restarts, nginx
 * answers 502 with an HTML document, and showing that verbatim put
 * "<html> <head><title>502 Bad Gateway</title>…" in /trade's error banner
 * (seen in production 2026-09-26, during a deploy restart).  Markup never
 * becomes user-facing text; the status's own plain sentence is used instead.
 */
function looksLikeMarkup(text) {
  return /<\s*(!doctype|html|head|body|title|center|h1)\b/i.test(String(text || ""));
}

const UNAVAILABLE_MESSAGE =
  "The server is restarting or briefly unavailable. Try again in a moment.";

/**
 * A machine-readable error code looks like one: `data_not_ready`,
 * `auth_required`.  Several routes put a SENTENCE in `error` instead ("No
 * data available yet. …") — that is the server's explanation, not a code,
 * and treating it as a code is how the Rankings banner said "for the
 * reason above" with no reason above it (production, 2026-10-05).
 */
const CODE_RE = /^[a-z][a-z0-9_.:-]{1,63}$/;

/**
 * Safe, human explanations for codes the backend is known to send.  Used
 * only when the server gave no explanation of its own — the server's words
 * win when present.  Never invents a cause for an unknown code.
 */
const CODE_EXPLANATIONS = {
  data_not_ready: "The rankings board is not loaded on the server yet.",
  contract_build_failed:
    "The server's latest rankings build failed, so it has no board to serve right now.",
  auth_required: "Sign in to continue.",
  forbidden: "This account cannot see this data.",
  rate_limited: "Too many requests — wait a moment and retry.",
  unknown_league: "That league is not recognised.",
  inactive_league: "That league is not active.",
  no_leagues_configured: "No leagues are configured on the server.",
};

/** The reason sentence for a refusal that stated no reason at all. */
export const NO_REASON_GIVEN = "The server did not say why. The cause is not available yet.";

function safeText(value) {
  if (typeof value !== "string") return "";
  const text = value.trim();
  if (!text || looksLikeMarkup(text)) return "";
  // A traceback or a filesystem path is not a user-facing reason.
  if (/Traceback \(most recent call last\)|\bFile "\/|^\s*at .+\(.+:\d+:\d+\)/m.test(text)) return "";
  return text.slice(0, 300);
}

/**
 * Normalise a response body into `{code, message}` deliberately:
 *   * `code`    — `body.error` when it is a code-shaped string (or `body.code`)
 *   * `message` — `message`, then `detail`, then `reason`, then an
 *                 `error` that is a sentence rather than a code, then a
 *                 non-markup plain-text body.
 */
export function normalizeFailureBody(body) {
  if (body && typeof body === "object") {
    const rawError = typeof body.error === "string" ? body.error.trim() : "";
    const errorIsCode = CODE_RE.test(rawError);
    const code = errorIsCode ? rawError : typeof body.code === "string" ? body.code : "";
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : body.detail && typeof body.detail === "object" && typeof body.detail.message === "string"
          ? body.detail.message
          : "";
    const message =
      safeText(body.message) ||
      safeText(detail) ||
      safeText(body.reason) ||
      (!errorIsCode ? safeText(rawError) : "");
    return { code, message };
  }
  return { code: "", message: safeText(typeof body === "string" ? body : "") };
}

/** The explanation to show: the server's words, else a known code's, else "". */
function explain(code, message) {
  return message || (code && CODE_EXPLANATIONS[code]) || "";
}

/**
 * Classify a contract-fetch failure.
 *
 * @param {number|null} status HTTP status, or null when the request never
 *   produced one (network error, abort, DNS, TLS).
 * @param {object|string|null} body parsed body if there was one
 * @returns {{kind: string, code: string, message: string, retryable: boolean}}
 *
 * `kind` is one of:
 *   "auth"        — 401: signed out, or never signed in
 *   "forbidden"   — 403: signed in, not permitted
 *   "degraded"    — 503 from a REACHABLE backend that answered in JSON
 *   "unavailable" — 502/504, or a 503 with no JSON body (the proxy could
 *                   not reach the backend, or it is restarting)
 *   "rate_limited"— 429
 *   "offline"     — no status at all: the request never reached a server
 *   "server"      — any other 5xx
 *   "error"       — anything else, including a 4xx we have no name for
 *
 * `message` is ALWAYS a sentence a person can read; it is never empty, so
 * a renderer never has to point at a reason that is not there.
 */
export function classifyContractFailure(status, body) {
  const { code, message: serverMessage } = normalizeFailureBody(body);
  const said = explain(code, serverMessage);
  const jsonBody = Boolean(body && typeof body === "object");

  if (status == null) {
    return { kind: "offline", code, message: said || "Could not reach the server.", retryable: true };
  }
  if (status === 401) {
    return { kind: "auth", code, message: said || "Sign in to continue.", retryable: false };
  }
  if (AUTH_STATUSES.has(status)) {
    return {
      kind: "forbidden",
      code,
      message: said || "This account cannot see this data.",
      retryable: false,
    };
  }
  if (status === 429) {
    return {
      kind: "rate_limited",
      code,
      message: said || "Too many requests — wait a moment and retry.",
      retryable: true,
    };
  }
  if (status === 503) {
    // A 503 the BACKEND answered (JSON) is DEGRADED, not down: the server is
    // running and declining — the scoring-identity gate, no board loaded.
    // A 503 with no JSON (a proxy's page, an empty body) means nothing
    // reachable answered, which is "unavailable".
    if (jsonBody && (code || serverMessage)) {
      return { kind: "degraded", code, message: said || NO_REASON_GIVEN, retryable: true };
    }
    return { kind: "unavailable", code, message: UNAVAILABLE_MESSAGE, retryable: true };
  }
  if (status === 502 || status === 504) {
    return { kind: "unavailable", code, message: said || UNAVAILABLE_MESSAGE, retryable: true };
  }
  if (status >= 500) {
    return { kind: "server", code, message: said || `Server error (${status}).`, retryable: true };
  }
  return { kind: "error", code, message: said || `HTTP ${status}`, retryable: false };
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
