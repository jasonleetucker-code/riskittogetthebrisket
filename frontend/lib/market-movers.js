"use client";

/**
 * market-movers — derive ticker items from the live contract.
 *
 * The signed-in terminal ticker needs to answer: "what moved?"  The
 * canonical contract stamps a ``rankChange`` field on every row
 * (positive = moved up on the consensus board, negative = down,
 * null = unranked or new).  That is a real, per-scrape delta — we
 * use it verbatim rather than recomputing from rank_history, because
 * buildRows does not currently project the per-player time series
 * down to the row shape.
 *
 * Three scopes:
 *   - "roster": players on the signed-in user's Sleeper team
 *   - "league": players on ANY Sleeper team in the league
 *   - "top150": the canonical top-150 board
 *
 * A ``null`` or ``0`` rankChange is treated as "quiet"; those rows
 * are NOT included in the ticker — a ticker full of "—" noise
 * isn't alive, it's static.
 */

function isMeaningfulChange(v) {
  return typeof v === "number" && Number.isFinite(v) && v !== 0;
}

function toRosterSet(selectedTeam) {
  const players = selectedTeam?.players;
  if (!Array.isArray(players)) return new Set();
  return new Set(players.map((p) => String(p).toLowerCase()));
}

function toLeagueSet(sleeperTeams) {
  const set = new Set();
  if (!Array.isArray(sleeperTeams)) return set;
  for (const t of sleeperTeams) {
    const players = t?.players;
    if (!Array.isArray(players)) continue;
    for (const p of players) set.add(String(p).toLowerCase());
  }
  return set;
}

/**
 * Compute ranked ticker items.
 * @param {object} args
 * @param {Array}  args.rows         flat row list from useDynastyData
 * @param {object} args.selectedTeam Sleeper team object (or null)
 * @param {Array}  args.sleeperTeams Full sleeper.teams[] from rawData
 * @param {string} args.scope        "roster" | "league" | "top150"
 * @param {number} args.limit        max items (default 20)
 * @returns {Array<{name, pos, value, rank, change, onRoster, key}>}
 */
export function computeMovers({
  rows,
  selectedTeam,
  sleeperTeams,
  scope = "roster",
  limit = 20,
}) {
  if (!Array.isArray(rows) || rows.length === 0) return [];

  const rosterSet = toRosterSet(selectedTeam);
  const leagueSet = toLeagueSet(sleeperTeams);

  let pool;
  if (scope === "roster") {
    pool = rows.filter((r) => rosterSet.has(String(r.name).toLowerCase()));
  } else if (scope === "league") {
    pool = rows.filter((r) => leagueSet.has(String(r.name).toLowerCase()));
  } else {
    // top150: use canonicalConsensusRank
    pool = rows.filter(
      (r) =>
        typeof r.canonicalConsensusRank === "number" &&
        r.canonicalConsensusRank > 0 &&
        r.canonicalConsensusRank <= 150,
    );
  }

  const moved = pool
    .filter((r) => isMeaningfulChange(r.rankChange))
    .map((r) => ({
      key: r.name,
      name: r.name,
      pos: r.pos || "?",
      value: Number(r.rankDerivedValue || r.values?.full || 0),
      rank: Number(r.canonicalConsensusRank) || null,
      change: Number(r.rankChange),
      onRoster: rosterSet.has(String(r.name).toLowerCase()),
    }));

  // Sort by magnitude of change, descending.  Ties resolved by
  // current value so the louder mover leads.
  moved.sort((a, b) => {
    const ma = Math.abs(a.change);
    const mb = Math.abs(b.change);
    if (mb !== ma) return mb - ma;
    return (b.value || 0) - (a.value || 0);
  });

  return moved.slice(0, limit);
}

/**
 * Render-friendly delta label, e.g. "▲ 12" or "▼ 3".
 */
export function formatChange(change) {
  if (!Number.isFinite(change) || change === 0) return "·";
  const abs = Math.abs(change);
  return change > 0 ? `▲ ${abs}` : `▼ ${abs}`;
}
