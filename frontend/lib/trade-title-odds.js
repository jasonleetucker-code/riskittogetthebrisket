/**
 * trade-title-odds — wording for the War Room's "This season's odds" panel
 * (DYN10 #4, `POST /api/trade/title-odds`, `src/trade/title_odds_lens.py`).
 *
 * DISPLAY ONLY.  Every number is the route's: playoff and title probability
 * before and after the trade, the change, its interval and the `significant`
 * flag.  Nothing here simulates, re-derives or re-rounds a probability into a
 * different quantity, and nothing here feeds the recommendation (the lens is
 * context, never a vote).
 *
 * Missing stays missing: an absent number is a dash or a sentence, never 0 or
 * "0%".  Levels are whole percents through `fmtSimulatedShare` (the site's one
 * rule for simulated shares: <1% / >99% until final).  Changes are in
 * percentage points to one decimal, because a whole point would print a real
 * half-point move as "+0".
 */

import { fmtSimulatedShare } from "./odds-disclosure";

/** Plain words for every reason the route can give. */
export const TITLE_ODDS_REASON_WORDS = {
  league_not_configured:
    "this league's playoff rules are not on record, so its season is not simulated",
  league_not_best_ball:
    "this league sets weekly lineups, and the simulation only models best-ball weeks",
  league_snapshot_unavailable: "the league data the simulation needs is not available right now",
  league_snapshot_mismatch: "the available league data belongs to a different league",
  no_remaining_schedule:
    "no regular-season games are left on the schedule, so the trade cannot change this season",
  team_strength_unavailable: "no team rosters are available to simulate",
  full_roster_unavailable: "a team in this trade has no full roster on record",
  starter_slots_unavailable: "this league's starting lineup slots could not be read",
  roster_snapshot_mismatch:
    "a traded player is not on the sending team's roster in the latest data (rosters have changed)",
  trade_asset_unresolved: "a traded player could not be identified",
  counterparty_unresolved: "it is not clear which team receives the players you send",
  multiple_counterparties:
    "the players you receive come from more than one team, so this is a multi-team trade",
  strength_delta_unavailable: "a changed roster has too few projected players to simulate",
  no_team_distributions: "no team scoring ranges could be built",
  team_not_in_simulation: "this team is not in the season simulation",
  title_odds_error: "the calculation failed",
  title_odds_timeout: "it took too long; it is still finishing, so try again in a moment",
  asset_only_mode: "it is not included in Asset-only analysis",
  playoff_seed_type_unknown:
    "this league's settings do not say how its playoff bracket is seeded, so the bracket cannot be played",
};

const GENERIC_REASON = "the season simulation could not answer for this trade";

/** Plain words for a lens reason; an unknown code reads generically, never as a code. */
export function titleOddsReasonText(reason) {
  const r = typeof reason === "string" ? reason.trim() : "";
  if (Object.prototype.hasOwnProperty.call(TITLE_ODDS_REASON_WORDS, r)) {
    return TITLE_ODDS_REASON_WORDS[r];
  }
  return GENERIC_REASON;
}

/** Errors Retry can plausibly fix (a refusal by the request itself cannot). */
const RETRYABLE = new Set(["timeout", "network", "title_odds_timeout", "title_odds_error"]);

export function titleOddsRetryable(code) {
  return RETRYABLE.has(code) || /^HTTP 5\d\d$/.test(String(code || ""));
}

/** Plain words for a request that did not return a lens payload. */
export function titleOddsErrorText(code) {
  const c = typeof code === "string" ? code : "";
  if (c === "feature_disabled") return "season odds are switched off";
  if (c === "auth_required" || c === "HTTP 401") return "you are signed out";
  if (c === "timeout") return "the request took too long";
  if (c === "network") return "the connection failed";
  if (c === "data_not_ready" || c === "HTTP 503") return "the data is not ready yet";
  if (/^HTTP 5\d\d$/.test(c)) return "the server had a problem";
  if (Object.prototype.hasOwnProperty.call(TITLE_ODDS_REASON_WORDS, c)) {
    return TITLE_ODDS_REASON_WORDS[c];
  }
  return "the request was refused";
}

function finite(x) {
  return typeof x === "number" && Number.isFinite(x);
}

/** A probability change as signed percentage points, one decimal: "+7.0". */
export function formatPointChange(delta) {
  if (!finite(delta)) return null;
  const pts = Math.round(Math.abs(delta) * 1000) / 10;
  if (pts === 0) return "0.0";
  return `${delta > 0 ? "+" : "−"}${pts.toFixed(1)}`;
}

/**
 * One odds row (`{before, after, delta, deltaCi, significant}`) in words, or
 * null when the row is missing.
 *   levels  "40% → 47%"
 *   change  "+7.0 points"
 *   range   "+3.0 to +11.0" (null without an interval)
 *   noise   true only when the route says the change is NOT significant
 */
export function oddsCell(odds) {
  if (!odds || typeof odds !== "object") return null;
  const before = finite(odds.before) ? fmtSimulatedShare(odds.before) : "—";
  const after = finite(odds.after) ? fmtSimulatedShare(odds.after) : "—";
  const change = formatPointChange(odds.delta);
  const ci = Array.isArray(odds.deltaCi) ? odds.deltaCi : null;
  const lo = ci ? formatPointChange(ci[0]) : null;
  const hi = ci ? formatPointChange(ci[1]) : null;
  return {
    levels: `${before} → ${after}`,
    change: change ? `${change} points` : null,
    range: lo && hi ? `${lo} to ${hi}` : null,
    noise: odds.significant === false,
  };
}

/**
 * The panel's rows, the analysed team first.  A team the simulation could not
 * place carries `unavailable` words instead of numbers.
 */
export function titleOddsRows(payload, perspectiveOwnerId) {
  const teams = Array.isArray(payload?.teams) ? payload.teams : [];
  const champUnavailable = (team) =>
    team.championshipUnavailable
      ? titleOddsReasonText(team.championshipUnavailable?.reason || team.championshipUnavailable)
      : null;
  const rows = teams
    .filter((t) => t && typeof t === "object")
    .map((t) => {
      const mine = perspectiveOwnerId != null && t.ownerId === perspectiveOwnerId;
      const name = t.displayName || t.ownerId || "Team";
      if (!t.available) {
        return {
          key: String(t.ownerId || name),
          name,
          mine,
          unavailable: titleOddsReasonText(t.unavailableReason),
        };
      }
      return {
        key: String(t.ownerId || name),
        name,
        mine,
        playoff: oddsCell(t.playoff),
        championship: oddsCell(t.championship),
        championshipUnavailable: champUnavailable(t),
      };
    });
  return [...rows.filter((r) => r.mine), ...rows.filter((r) => !r.mine)];
}
