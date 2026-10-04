// Pick-ownership state — the frontend's ONE reader of the backend stamp.
//
// The backend owner is `src/identity/picks.py` (`pick_ownership_fields` /
// `team_pick_ownership_unavailable_reason`).  When Sleeper's /traded_picks
// fetch fails, every `sleeper.teams[]` entry carries
//   pickOwnershipState: "unavailable", pickOwnershipReason: "traded_picks_fetch_failed"
// and `picks` / `pickDetails` are `null` — UNKNOWN, never `[]` ("owns no
// picks").  Surfaces must render that as unknown, never as 0 picks.
//
// This module decides nothing: it reads the stamp.  The string constants are
// held in lockstep with the Python owner by
// `tests/identity/test_pick_ownership_fail_closed.py`.

export const PICK_OWNERSHIP_STATE_FIELD = "pickOwnershipState";
export const PICK_OWNERSHIP_REASON_FIELD = "pickOwnershipReason";
export const PICK_OWNERSHIP_UNAVAILABLE = "unavailable";
export const PICK_OWNERSHIP_REASON_TRADED_PICKS_FETCH_FAILED = "traded_picks_fetch_failed";
export const PICK_OWNERSHIP_UNAVAILABLE_ERROR = "pick_ownership_unavailable";

/** The one user-facing label for the unknown state. */
export const PICK_OWNERSHIP_UNAVAILABLE_LABEL = "Pick ownership unavailable";

/**
 * Why `team`'s picks are not usable, or `null` when they are.
 *
 * - explicit `pickOwnershipState: "unavailable"` → its reason;
 * - `picks === null` (explicit null — the producers' unknown) → its reason
 *   or `"pick_ownership_unstated"`;
 * - anything else (observed, or a legacy payload without the field) → null.
 *
 * An ABSENT `picks` key is deliberately not treated as unknown here: both
 * producers now always emit it, and pre-existing callers build team objects
 * without it.
 */
export function pickOwnershipUnavailableReason(team) {
  if (!team || typeof team !== "object") return null;
  if (team[PICK_OWNERSHIP_STATE_FIELD] === PICK_OWNERSHIP_UNAVAILABLE) {
    return team[PICK_OWNERSHIP_REASON_FIELD] || PICK_OWNERSHIP_UNAVAILABLE;
  }
  if (team.picks === null) {
    return team[PICK_OWNERSHIP_REASON_FIELD] || "pick_ownership_unstated";
  }
  return null;
}

/** Human sentence for a reason code (falls back to the generic label). */
export function describePickOwnershipReason(reason) {
  if (reason === PICK_OWNERSHIP_REASON_TRADED_PICKS_FETCH_FAILED) {
    return "Sleeper's traded-picks feed could not be read, so who owns which pick is unknown.";
  }
  return "Who owns which pick is unknown for this league right now.";
}
