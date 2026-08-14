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

/**
 * The board a request should be answered from.
 *
 * WITHDRAWN 2026-08-14 — always `MARKET`, which is now simply "the one
 * canonical board".
 *
 * This used to read `valuationMode` out of `next_settings_v2` in
 * localStorage. That is device-local and never server-synced, so one
 * account on two devices held two answers to "which methodology am I
 * looking at", and the lens overwrote `rankDerivedValue` in place — so
 * the same player rendered different values on phone and desktop with
 * nothing in the payload naming which was which. Measured on the live
 * overlay: +1.8% for QBs, up to +9.8% for DL.
 *
 * The league-aware methodology was evaluated for promotion to canonical
 * and rejected on the evidence (see
 * `docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md`). With one
 * methodology there is nothing to select, so the setting is inert rather
 * than removed: reading it and ignoring it is what makes an old phone
 * with `leagueAdjusted` stored converge automatically, with no migration
 * step and no user cleanup.
 *
 * Kept as a function, not inlined to a constant, because it is the one
 * seam a future *validated* methodology re-opens.
 */
export function readValuationMode() {
  return MARKET;
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
