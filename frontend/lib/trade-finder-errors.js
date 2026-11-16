// Why a trade-tool request failed — as a readable sentence, with the backend's
// machine code kept only as a detail.
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

/** The plain message for a known code, else null. */
export function tradeToolCodeText(code) {
  return (code && CODE_TEXT[code]) || null;
}

/**
 * Classify a failed trade-tool response.
 *
 * @param {number|null} status HTTP status, or null when no response arrived.
 * @param {object|string|null} body the parsed response body, if any.
 * @param {{tool?: string}} [opts] the tool's name for the generic fallback.
 * @returns {{message: string, code: string}} `message` is always a readable
 *   sentence; `code` is the backend's machine code ("" when none), for a
 *   detail line only.
 */
export function tradeToolFailure(status, body, { tool = "The trade tool" } = {}) {
  const { code, message } = normalizeFailureBody(body);
  if (message) return { message, code };
  const known = tradeToolCodeText(code);
  if (known) return { message: known, code };
  // A success status carrying an unrecognised `error` (the /angle route can
  // answer 200 with one): no transport cause to name.
  if (status != null && status < 400) {
    return { message: `${tool} could not run. Try again.`, code };
  }
  const generic = classifyContractFailure(status ?? null, body);
  // The transport classifier's last resort is a bare "HTTP 400"; say which
  // tool failed instead.
  if (generic.kind === "error") {
    return {
      message: `${tool} could not run${status ? ` (HTTP ${status})` : ""}. Try again.`,
      code,
    };
  }
  return { message: generic.message, code };
}

/** An Error that carries a classified failure through a `throw`. */
export class TradeToolRequestError extends Error {
  constructor(failure) {
    super(failure.message);
    this.name = "TradeToolRequestError";
    this.failure = failure;
  }
}

/** The failure to show for anything a request's `catch` received. */
export function failureFromError(err) {
  if (err && err.failure) return err.failure;
  return { message: err?.message || "Request failed", code: "" };
}
