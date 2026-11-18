// Why a trade-tool request failed — as a readable sentence, with the backend's
// machine code and any technical text kept only as details.
//
// THE DEFECT THIS REPLACES
// ────────────────────────
// Market Disagreement's Package Scan, Golden Upgrades, Best Offers and /angle
// put `data.error` straight into their error banner.  Several of the routes
// they call answer with a bare CODE (`{"error": "unknown_team"}`, the auth
// gate's `auth_required`, the league gate's `data_not_ready`), so the user read
// "auth_required" where a sentence belonged.
//
// Reuses the one body normaliser (`normalizeFailureBody`, lib/contract-failure)
// so a code-shaped `error` and a sentence-shaped `error` are told apart the same
// way everywhere.  The server's own words win when it gave some; a known code
// gets its plain message; anything else falls back to the shared transport
// classifier's sentence — never to the code alone.
//
// TRANSPORT TEXT IS A DETAIL, NOT A MESSAGE
// ─────────────────────────────────────────
// When the backend restarts or does not answer in time, the Next bridge route
// (app/api/**/route.js) answers 503 `{"error": "<Tool> service unavailable",
// "detail": err.message}` — `detail` being Node's "fetch failed" or "This
// operation was aborted".  The body normaliser prefers `detail`, so that text
// became the banner.  It is the transport's words, not the server's: the
// banner says the tool is temporarily unavailable and the technical text stays
// a detail.  The same holds for a request the browser could not send at all
// ("Failed to fetch").
//
// A DETERMINISTIC REFUSAL IS NOT "TRY AGAIN"
// ──────────────────────────────────────────
// A 4xx the backend sent with a code we have no copy for (`invalid_refinement`,
// `invalid_numbers`, …) will fail identically on a retry, so it reads "did not
// accept this request", never "Try again".

import { classifyContractFailure, normalizeFailureBody } from "@/lib/contract-failure";

const CODE_TEXT = {
  auth_required: "Sign in to use the trade tools.",
  forbidden: "This account cannot use the trade tools.",
  guest_read_only: "Guest passes cannot run the trade tools.",
  data_not_ready:
    "This league's rosters and values are not loaded on the server yet — try again in a moment.",
  contract_build_failed:
    "The server's latest rankings build failed, so the trade tools have no board to work from right now.",
  unknown_team: "That team is not in this league's rosters — choose your team again.",
  unknown_opponent: "That opponent is not in this league's rosters — choose a different team.",
  unknown_league: "That league is not recognised.",
  inactive_league: "That league is not active.",
  no_leagues_configured: "No leagues are configured on the server.",
  rate_limited: "Too many requests — wait a moment and retry.",
  feature_disabled: "This trade tool is switched off on the server.",
};

/** Node / browser fetch failures: transport text, never a server's reason. */
const TRANSPORT_TEXT_RE =
  /\b(fetch failed|failed to fetch|load failed|networkerror|network request failed|operation was aborted|aborterror|econnrefused|econnreset|etimedout|eai_again|socket hang up|other side closed|und_err\w*)\b/i;

/** The bridge route's own "could not reach the backend" sentence. */
const BRIDGE_UNAVAILABLE_RE = /\bservice unavailable\b/i;

const UNAVAILABLE_STATUSES = new Set([502, 503, 504]);

function technicalText(...parts) {
  return parts
    .filter((p) => typeof p === "string" && p.trim())
    .map((p) => p.trim())
    .join(": ")
    .slice(0, 300);
}

function temporarilyUnavailable(tool) {
  return `${tool} is temporarily unavailable — the server is restarting or did not answer in time. Try again shortly.`;
}

/** The plain message for a known code, else null. */
export function tradeToolCodeText(code) {
  return (code && CODE_TEXT[code]) || null;
}

/**
 * Did the Next bridge answer for a backend it could not reach?  Its shape is
 * `{error: "<Tool> service unavailable", detail: <transport text>}` with no
 * `message` and no code — a backend refusal always carries one or the other.
 */
function isBridgeTransportFailure(status, body) {
  if (!UNAVAILABLE_STATUSES.has(status)) return false;
  if (!body || typeof body !== "object") return false;
  if (typeof body.message === "string" && body.message.trim()) return false;
  const { code } = normalizeFailureBody(body);
  if (code) return false;
  const error = typeof body.error === "string" ? body.error : "";
  const detail = typeof body.detail === "string" ? body.detail : "";
  return BRIDGE_UNAVAILABLE_RE.test(error) || TRANSPORT_TEXT_RE.test(detail);
}

/**
 * Classify a failed trade-tool response.
 *
 * @param {number|null} status HTTP status, or null when no response arrived.
 * @param {object|string|null} body the parsed response body, if any.
 * @param {{tool?: string}} [opts] the tool's name for the generic fallbacks.
 * @returns {{message: string, code: string, detail: string}} `message` is
 *   always a readable sentence; `code` is the backend's machine code ("" when
 *   none) and `detail` any technical text ("" when none) — both for a detail
 *   line only.
 */
export function tradeToolFailure(status, body, { tool = "The trade tool" } = {}) {
  if (isBridgeTransportFailure(status, body)) {
    return {
      message: temporarilyUnavailable(tool),
      code: "",
      detail: technicalText(body.error, body.detail),
    };
  }
  const { code, message } = normalizeFailureBody(body);
  if (message) return { message, code, detail: "" };
  const known = tradeToolCodeText(code);
  if (known) return { message: known, code, detail: "" };
  // A success status carrying an unrecognised `error` (the /angle route can
  // answer 200 with one): no transport cause to name.
  if (status != null && status < 400) {
    return { message: `${tool} could not run. Try again.`, code, detail: "" };
  }
  const generic = classifyContractFailure(status ?? null, body);
  if (generic.kind === "error") {
    // The transport classifier's last resort is a bare "HTTP 400".  Any other
    // 4xx is a DETERMINISTIC refusal of this request — retrying sends the
    // same request and gets the same answer, so it never says "Try again".
    return {
      message: `${tool} did not accept this request${status ? ` (HTTP ${status})` : ""}.`,
      code,
      detail: "",
    };
  }
  return { message: generic.message, code, detail: "" };
}

/** An Error that carries a classified failure through a `throw`. */
export class TradeToolRequestError extends Error {
  constructor(failure) {
    super(failure.message);
    this.name = "TradeToolRequestError";
    this.failure = failure;
  }
}

/**
 * The failure to show for anything a request's `catch` received.  A fetch the
 * browser could not complete ("Failed to fetch") reads as unreachable, with
 * its text kept as a detail; any other error keeps its own message.
 */
export function failureFromError(err, { tool = "The trade tool" } = {}) {
  if (err && err.failure) return err.failure;
  const text = typeof err?.message === "string" ? err.message : "";
  if (err?.name === "AbortError" || TRANSPORT_TEXT_RE.test(text)) {
    return {
      message: `${tool} could not reach the server. Check your connection and try again shortly.`,
      code: "",
      detail: technicalText(text),
    };
  }
  return { message: text || "Request failed", code: "", detail: "" };
}
