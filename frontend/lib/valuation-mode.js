/**
 * Which board an engine request should be answered from.
 *
 * The problem this solves
 * ──────────────────────
 * The valuation toggle used to reach exactly one surface. `/rankings`
 * applies the league-adjusted overlay client-side, but every engine —
 * trade suggestions, the arbitrage finder, angles, the simulator, FAAB —
 * runs server-side off the loaded contract and never saw it. So the
 * board switched and the advice did not: adjusted rankings, market-priced
 * trades, in the same session, with nothing on screen saying so.
 *
 * The backend now accepts `valuation_mode` on every engine endpoint and
 * stamps back the mode it ACTUALLY served (see
 * `server.py::_valuation_scoped_contract`). This is the client half:
 * one place that answers "which board did the user pick", so six call
 * sites cannot drift into six different answers.
 *
 * Why localStorage and not React state
 * ────────────────────────────────────
 * These are fetch helpers, not components — `useTerminal` and
 * `useTradeSimulator` already read the active league key exactly this
 * way. Threading a setting through as a prop to reach a module-level
 * fetch function would mean rewriting the callers around a value they
 * do not otherwise use.
 *
 * Reading during SSR returns the default, which is correct: the server
 * render has no user preference, and the market board is the one the
 * server always has.
 */

import { SETTINGS_KEY } from "@/lib/trade-logic";

export const MARKET = "market";
export const LEAGUE_ADJUSTED = "leagueAdjusted";

/** The board the user has selected, or `market` when unknowable. */
export function readValuationMode() {
  if (typeof window === "undefined") return MARKET;
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return MARKET;
    const parsed = JSON.parse(raw);
    return parsed?.valuationMode === LEAGUE_ADJUSTED ? LEAGUE_ADJUSTED : MARKET;
  } catch {
    // A corrupt settings blob must not take down a trade request.
    return MARKET;
  }
}

/**
 * Add `valuation_mode` to an engine POST body.
 *
 * Only when the adjusted board is selected: sending `market`
 * explicitly would be identical in effect and would churn every
 * request body in the tests and logs for no behavioural difference.
 * An explicit mode already on the body always wins — a caller that
 * pins its lens means it.
 */
export function withValuationMode(body) {
  const payload = { ...(body || {}) };
  if (payload.valuation_mode || payload.valuationMode) return payload;
  const mode = readValuationMode();
  if (mode === LEAGUE_ADJUSTED) payload.valuation_mode = mode;
  return payload;
}

/**
 * Set `valuationMode` on a GET query string, and return the mode so
 * the caller can key its cache on it.
 *
 * Returning the mode is the point: a cache keyed without it serves the
 * market payload after the user switches boards, which looks exactly
 * like the toggle not working.
 */
export function applyValuationModeParam(params) {
  const mode = readValuationMode();
  if (mode === LEAGUE_ADJUSTED) params.set("valuationMode", mode);
  return mode;
}
