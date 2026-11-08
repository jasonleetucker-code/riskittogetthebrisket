// Division-title odds for the /league Power tab (owner decision 2026-11-08).
//
// The backend (``src/ros/playoff_sim.py`` via the public ``playoffOdds``
// section) computes each team's chance to WIN ITS DIVISION from the same
// simulated seasons as its playoff odds.  The two are different questions:
// in a league whose divisions carry no playoff advantage (``dynasty_main``),
// a division champion can miss the playoffs and a non-champion can qualify.
// This module only groups and formats backend numbers — it computes no odds.

/**
 * A simulated share as a percent.  A Monte Carlo estimate of exactly 0 or 1
 * is not proof (the simulation ran a finite number of seasons), so it reads
 * "<1%" / ">99%" until the season is final, when the outcome is a fact.
 */
export function fmtSimulatedShare(p, { final = false } = {}) {
  if (typeof p !== "number" || !Number.isFinite(p)) return "—";
  const pct = Math.round(p * 100);
  if (!final) {
    if (pct <= 0) return "<1%";
    if (pct >= 100) return ">99%";
  }
  return `${pct}%`;
}

/**
 * ``[{ division, name, teams: [{ownerId, displayName, currentWins,
 * divisionChampionProbability, playoffProbability}] }]`` sorted by division,
 * teams by division-title odds — or ``null`` when the section publishes no
 * division odds (no divisions, or a reason in ``divisionOdds.reason``).
 */
export function divisionOddsGroups(data) {
  const odds = data?.divisionOdds;
  if (!odds || odds.state !== "available") return null;
  const owners = Array.isArray(data?.owners) ? data.owners : [];
  const names = odds.names || {};
  const byDivision = new Map();
  for (const o of owners) {
    if (typeof o?.division !== "number") continue;
    if (!byDivision.has(o.division)) byDivision.set(o.division, []);
    byDivision.get(o.division).push(o);
  }
  if (byDivision.size === 0) return null;
  return [...byDivision.entries()]
    .sort(([a], [b]) => a - b)
    .map(([division, teams]) => ({
      division,
      name: names[String(division)] || `Division ${division}`,
      teams: teams
        .slice()
        .sort(
          (a, b) =>
            (b.divisionChampionProbability ?? -1) - (a.divisionChampionProbability ?? -1) ||
            String(a.displayName || a.ownerId).localeCompare(String(b.displayName || b.ownerId)),
        ),
    }));
}

/** One line on how this league's divisions bear on the playoffs, or null. */
export function divisionRuleNote(data) {
  const rule = data?.divisionOdds?.championRule;
  if (!rule) return null;
  if (rule.affectsPlayoffs === false) {
    return "Division titles carry no playoff berth or seeding advantage here: the best overall records qualify.";
  }
  return null;
}
