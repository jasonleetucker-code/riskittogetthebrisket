// The Ring Club — pure formatting helpers for verified Brisket Dynasty
// championship rings (owner directive 2026-11-23, "BUILD THE RING CLUB").
//
// A player earns one ring for each season he was on the championship-
// winning roster when the championship concluded.  The backend decides
// every fact — who holds a ring, how many, rank, ties, prestige, coverage
// and the empty-state message.  These helpers FORMAT those facts for the
// two public surfaces that show them; they count, sort and rank nothing.
//
// Consumers:
//   * app/league/sections/_ring-club.jsx — the History tab card (client)
//   * app/league/player/[playerId]/championship-rings.jsx — the player
//     journey card (server-rendered)
//
// No JSX and no CSS here on purpose: the player journey is a server page,
// and a CSS-module import from it ships the class map as client JS and
// regroups that route's chunks (measured: page chunk 150 B -> 8.6 KB).

export const RING_CLUB_TITLE = "THE RING CLUB";
export const RING_CLUB_SUBTITLE = "Players with Multiple Championships";
export const HISTORY_INCOMPLETE_NOTE = "Earlier league seasons could not all be read.";

/** A ring count the payload actually stated, or 0.  Never NaN, never negative. */
export function ringCount(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
}

/** "3 championship rings" — what a screen reader hears instead of 🏆🏆🏆. */
export function ringsAriaLabel(rings) {
  const n = ringCount(rings);
  return `${n} championship ring${n === 1 ? "" : "s"}`;
}

/** One 🏆 per ring. */
export function trophyRun(rings) {
  return "🏆".repeat(ringCount(rings));
}

/** The backend's rank as a marker: "1", or "T-1" for a shared rank. */
export function rankLabel(member) {
  const rank = Number(member?.rank);
  if (member?.rank == null || !Number.isFinite(rank)) return null;
  return member.tied === true ? `T-${rank}` : String(rank);
}

function present(v) {
  return v !== null && v !== undefined && String(v).trim() !== "";
}

/** Season labels from a list of strings or `{season}` objects. */
export function seasonLabels(values) {
  if (!Array.isArray(values)) return [];
  return values
    .map((v) => (v && typeof v === "object" ? v.season : v))
    .filter(present)
    .map((v) => String(v));
}

/** Position and NFL team, missing parts omitted (never "null"). */
export function playerIdentityParts(member) {
  return [member?.position, member?.nflTeam].filter(present).map((v) => String(v));
}

/**
 * The History card's coverage footnote: which championship rosters are
 * verified and — when coverage is incomplete — what is not.
 * `historyComplete: false` makes coverage incomplete even with no season
 * listed (the walk back through the league's history did not reach its
 * first season), so the incomplete line never assumes a season list.
 */
export function coverageNotes(coverage) {
  if (!coverage || typeof coverage !== "object") {
    return { verifiedLine: null, incompleteLine: null };
  }
  const verified = seasonLabels(coverage.verifiedSeasons);
  const verifiedLine = verified.length
    ? `Verified championship rosters: ${verified.join(", ")}`
    : null;
  let incompleteLine = null;
  if (coverage.state === "incomplete") {
    const parts = [];
    const unverified = seasonLabels(coverage.unverifiedSeasons);
    const partial = seasonLabels(coverage.partialSeasons);
    if (unverified.length) parts.push(`Not verified: ${unverified.join(", ")}.`);
    if (partial.length) parts.push(`Partially verified: ${partial.join(", ")}.`);
    if (coverage.historyComplete === false || !parts.length) parts.push(HISTORY_INCOMPLETE_NOTE);
    incompleteLine = `Coverage is incomplete. ${parts.join(" ")}`;
  }
  return { verifiedLine, incompleteLine };
}

/**
 * The player card's note when its coverage is incomplete: the count is a
 * floor over verified rosters, never presented as the whole answer.
 */
export function playerCoverageNote(championshipRings) {
  if (championshipRings?.coverageState !== "incomplete") return null;
  const unverified = seasonLabels(championshipRings.unverifiedSeasons);
  return unverified.length
    ? `Counts verified championship rosters only. Not verified: ${unverified.join(", ")}.`
    : `Counts verified championship rosters only. ${HISTORY_INCOMPLETE_NOTE}`;
}
