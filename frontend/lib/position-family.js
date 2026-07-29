/**
 * position-family — the single coarse position → bucket map for the
 * frontend.
 *
 * It existed twice (lib/movers.js for /trending, lib/activity-feed.js
 * for the league activity feed) with DIFFERENT contents: the activity
 * copy was missing ``K`` and ``DEF``, so kickers and team defences
 * bucketed as "OTHER" on one surface and correctly on the other. Same
 * concept, one definition, one place to add a position alias.
 *
 * Buckets are the lineup families the UI filters on (QB/RB/WR/TE +
 * DL/LB/DB + K/DEF); anything unmapped is "OTHER" rather than passed
 * through, so a novel scraper position can never masquerade as a
 * filterable family.
 *
 * Related but deliberately separate:
 *   - ``src/utils/name_clean.py::POSITION_ALIASES`` — the backend's
 *     canonical position normalizer (alias → position, not position →
 *     family).
 *   - ``lib/player-name-match.js::positionFamily`` — first token of a
 *     slashed position string ("DL/EDGE" → "DL"), a string op with no
 *     bucket table.
 *
 * No "use client": server components must be able to import it.
 */

export const POS_FAMILY = Object.freeze({
  QB: "QB", RB: "RB", FB: "RB", WR: "WR", TE: "TE",
  K: "K", DEF: "DEF",
  DL: "DL", DT: "DL", DE: "DL", EDGE: "DL", NT: "DL",
  LB: "LB", ILB: "LB", OLB: "LB", MLB: "LB",
  DB: "DB", CB: "DB", S: "DB", FS: "DB", SS: "DB",
});

/** Coarse family for a position string; "OTHER" when unmapped. */
export function familyOf(pos) {
  return POS_FAMILY[String(pos || "").toUpperCase()] || "OTHER";
}
