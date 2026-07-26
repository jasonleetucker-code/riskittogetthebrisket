// player-filters.js — pure predicate engine for the player search /
// filter system (Phase 3).
//
// Design rules:
//   • Pure functions over materialized rows (buildRows output) — no
//     fetching, no React, no globals.  The rankings page (and, after
//     the redesign lands, the R2 terminal board) applies these
//     client-side over ~1.1k rows, which is fast enough that no
//     memoization layer is needed here.
//   • Owner filtering takes an externally-built name→team map
//     (buildTeamByPlayer from waiver-logic.js) because ownership is
//     league-scoped while rows are scoring-profile-scoped — the
//     CLAUDE.md split.  Rows never carry the owner.
//   • Every criterion is optional; an empty criteria object matches
//     every row.  Unknown/null row fields fail closed for range
//     filters (a player with unknown age is excluded by an age
//     filter) but match "any" (absent criterion) — filtering on a
//     field should never surface rows the filter can't evaluate.

/** Experience buckets keyed by yearsExp (0 = rookie). */
export const EXPERIENCE_BUCKETS = [
  { key: "rookie", label: "Rookie", match: (y) => y === 0 },
  { key: "sophomore", label: "2nd Year", match: (y) => y === 1 },
  { key: "vet", label: "3+ Years", match: (y) => y >= 2 },
];

const EXPERIENCE_BY_KEY = Object.fromEntries(
  EXPERIENCE_BUCKETS.map((b) => [b.key, b]),
);

function num(v) {
  // Number(null) === 0 — guard explicitly so unknown fields stay
  // unknown (fail-closed under range filters) instead of becoming 0.
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function norm(s) {
  return String(s || "").trim().toLowerCase();
}

/**
 * Build the option list for the NFL-team dropdown from live rows.
 * "FA" (matched free agents) sorts last; unknown-team rows are not an
 * option (they're excluded whenever a team filter is active).
 */
export function teamOptions(rows) {
  const teams = new Set();
  for (const r of rows || []) {
    const t = String(r?.team || "").trim().toUpperCase();
    if (t) teams.add(t);
  }
  const arr = Array.from(teams).sort();
  const i = arr.indexOf("FA");
  if (i >= 0) {
    arr.splice(i, 1);
    arr.push("FA");
  }
  return arr;
}

/**
 * criteria = {
 *   positions:   Set|array of position codes (row.pos exact match)
 *   ageMin/ageMax:       inclusive bounds (row.age)
 *   experience:  bucket key from EXPERIENCE_BUCKETS (row.yearsExp)
 *   nflTeam:     team abbreviation ("FA" = matched free agents)
 *   ownerTeam:   fantasy owner team name, or FREE_AGENT_OWNER for
 *                unrostered players (evaluated via teamByPlayer map)
 *   rankMin/rankMax:     inclusive bounds on canonicalConsensusRank
 *   valueMin/valueMax:   inclusive bounds on rankDerivedValue
 *   tier:        canonicalTierId exact match
 *   edge:        "buy" | "sell" (marketGapDirection mapping)
 *   rookieOnly:  boolean
 *   watchlist:   Set of lowercase names (row must be in it)
 *   query:       free-text token search (see matchesQuery)
 * }
 * extras = { teamByPlayer } — name → fantasy team name map.
 */
export const FREE_AGENT_OWNER = "__free_agent__";

export function rowMatches(row, criteria, extras = {}) {
  if (!row) return false;
  const c = criteria || {};

  if (c.positions && (c.positions.size ?? c.positions.length)) {
    const set = c.positions instanceof Set ? c.positions : new Set(c.positions);
    if (!set.has(row.pos)) return false;
  }

  const age = num(row.age);
  if (c.ageMin != null && (age === null || age < c.ageMin)) return false;
  if (c.ageMax != null && (age === null || age > c.ageMax)) return false;

  if (c.experience) {
    const bucket = EXPERIENCE_BY_KEY[c.experience];
    const y = num(row.yearsExp);
    if (!bucket || y === null || !bucket.match(y)) return false;
  }

  if (c.nflTeam) {
    const t = String(row.team || "").trim().toUpperCase();
    if (t !== String(c.nflTeam).trim().toUpperCase()) return false;
  }

  if (c.ownerTeam) {
    const owner = (extras.teamByPlayer || {})[norm(row.name)] || null;
    if (c.ownerTeam === FREE_AGENT_OWNER) {
      if (owner) return false;
    } else if (norm(owner) !== norm(c.ownerTeam)) {
      return false;
    }
  }

  const rank = num(row.canonicalConsensusRank);
  if (c.rankMin != null && (rank === null || rank < c.rankMin)) return false;
  if (c.rankMax != null && (rank === null || rank > c.rankMax)) return false;

  const value = num(row.rankDerivedValue);
  if (c.valueMin != null && (value === null || value < c.valueMin)) return false;
  if (c.valueMax != null && (value === null || value > c.valueMax)) return false;

  if (c.tier != null && num(row.canonicalTierId) !== num(c.tier)) return false;

  if (c.edge) {
    const dir = String(row.marketGapDirection || "none");
    const want = c.edge === "buy" ? "consensus_higher" : "market_higher";
    if (dir !== want) return false;
  }

  if (c.rookieOnly && !row.rookie) return false;

  if (c.watchlist && c.watchlist.size != null) {
    if (!c.watchlist.has(norm(row.name))) return false;
  }

  if (c.query && !matchesQuery(row, c.query, extras)) return false;

  return true;
}

/**
 * Token search: every whitespace token must match at least one of
 * name / NFL team / position / fantasy owner.  Supports explicit
 * prefixes: "owner:jason", "team:chi", "pos:wr".  "WR CHI" therefore
 * finds Chicago wide receivers; "owner:Jason RB" finds Jason's RBs.
 */
export function matchesQuery(row, query, extras = {}) {
  const tokens = String(query || "").split(/\s+/).map(norm).filter(Boolean);
  if (!tokens.length) return true;
  const name = norm(row.name);
  const team = norm(row.team);
  const pos = norm(row.pos);
  const owner = norm((extras.teamByPlayer || {})[name] || "");
  for (const token of tokens) {
    let ok;
    if (token.startsWith("owner:")) {
      ok = owner.includes(token.slice(6));
    } else if (token.startsWith("team:")) {
      ok = team === token.slice(5) || team.includes(token.slice(5));
    } else if (token.startsWith("pos:")) {
      ok = pos === token.slice(4);
    } else {
      ok = name.includes(token) || team === token || pos === token || owner.includes(token);
    }
    if (!ok) return false;
  }
  return true;
}

/** Apply criteria over all rows. */
export function filterRows(rows, criteria, extras = {}) {
  if (!Array.isArray(rows)) return [];
  const c = criteria || {};
  const active =
    (c.positions && (c.positions.size ?? c.positions.length)) ||
    c.ageMin != null || c.ageMax != null || c.experience || c.nflTeam ||
    c.ownerTeam || c.rankMin != null || c.rankMax != null ||
    c.valueMin != null || c.valueMax != null || c.tier != null ||
    c.edge || c.rookieOnly || c.watchlist || c.query;
  if (!active) return rows;
  return rows.filter((r) => rowMatches(r, c, extras));
}
