/**
 * team-phase — classify each team in the league as
 * Win-now / Contender / Mixed / Rebuild based on roster age × value.
 *
 * Methodology
 * -----------
 * For every team in ``rawData.sleeper.teams``:
 *   1. Look up rankDerivedValue + age for each rostered player.
 *   2. Compute median age and total value (top-25 players, or all if
 *      shorter).
 *   3. Score along two dimensions:
 *        - value vs the league median (above / below)
 *        - age vs the league median (younger / older)
 *
 * Phase classification
 * --------------------
 *   high value × younger  →  Win-now    ("you're built to win now and later")
 *   high value × older    →  Contender  ("you're built to win now")
 *   low value × younger   →  Rebuild    ("you're young and still climbing")
 *   low value × older     →  Mixed      ("you should probably reset")
 *
 * Trade-partner suggestion: a Win-now/Contender team is a natural
 * buyer of older star talent from a Rebuild team.  We surface the
 * three most-complementary pairs in the UI.
 *
 * No I/O — pure function from the live contract.
 */

const TOP_N_FOR_VALUE = 25;

export const PHASES = Object.freeze({
  WIN_NOW: { key: "win_now", label: "Win-now", tone: "up", order: 0 },
  CONTENDER: { key: "contender", label: "Contender", tone: "up", order: 1 },
  MIXED: { key: "mixed", label: "Mixed", tone: "warn", order: 2 },
  REBUILD: { key: "rebuild", label: "Rebuild", tone: "down", order: 3 },
});

function median(values) {
  const arr = (values || [])
    .filter((v) => Number.isFinite(v))
    .sort((a, b) => a - b);
  if (!arr.length) return null;
  const mid = Math.floor(arr.length / 2);
  return arr.length % 2 ? arr[mid] : (arr[mid - 1] + arr[mid]) / 2;
}

function buildIndex(rows) {
  const ix = new Map();
  for (const r of rows || []) {
    if (!r?.name) continue;
    ix.set(String(r.name).toLowerCase(), {
      value: Number(r.rankDerivedValue || r.values?.full || 0),
      age: Number(r.age) || null,
    });
  }
  return ix;
}

function teamSnapshot(team, valueIndex) {
  const players = Array.isArray(team?.players) ? team.players : [];
  const lookup = players
    .map((n) => valueIndex.get(String(n).toLowerCase()))
    .filter((p) => p && p.value > 0);
  // Sort by value desc, take top N for the "starter-equivalent" total.
  const top = [...lookup].sort((a, b) => b.value - a.value).slice(0, TOP_N_FOR_VALUE);
  const totalValue = top.reduce((s, p) => s + p.value, 0);
  const ages = top.map((p) => p.age).filter((a) => Number.isFinite(a));
  return {
    name: team?.name || "Team",
    ownerId: String(team?.ownerId || ""),
    rosterId: String(team?.rosterId || ""),
    totalValue: Math.round(totalValue),
    medianAge: median(ages),
    rosterCount: players.length,
    valuedCount: top.length,
  };
}

function classifyPhase(snapshot, leagueMedians) {
  const { totalValue, medianAge } = snapshot;
  const isHighValue = leagueMedians.value != null && totalValue > leagueMedians.value;
  // ``younger`` is < median age (lower number = younger).  When
  // medianAge is null (no age data), default to "older" so a team
  // with missing data doesn't get pushed into the youth corner.
  const isYounger =
    medianAge != null && leagueMedians.age != null && medianAge < leagueMedians.age;

  if (isHighValue && isYounger) return PHASES.WIN_NOW;
  if (isHighValue && !isYounger) return PHASES.CONTENDER;
  if (!isHighValue && isYounger) return PHASES.REBUILD;
  return PHASES.MIXED;
}

export function analyzeLeaguePhases(rawData, rows) {
  const teams = rawData?.sleeper?.teams || [];
  if (!Array.isArray(teams) || teams.length === 0) {
    return { teams: [], leagueMedians: { value: null, age: null }, partnerships: [] };
  }
  const valueIndex = buildIndex(rows);
  const snapshots = teams.map((t) => teamSnapshot(t, valueIndex));

  const leagueMedians = {
    value: median(snapshots.map((s) => s.totalValue)),
    age: median(snapshots.map((s) => s.medianAge).filter((a) => a != null)),
  };

  const enriched = snapshots.map((s) => {
    const phase = classifyPhase(s, leagueMedians);
    return { ...s, phase };
  });

  enriched.sort((a, b) => {
    if (a.phase.order !== b.phase.order) return a.phase.order - b.phase.order;
    return b.totalValue - a.totalValue;
  });

  const winners = enriched.filter((t) => t.phase.key === "win_now" || t.phase.key === "contender");
  const rebuilders = enriched.filter((t) => t.phase.key === "rebuild");
  const partnerships = [];
  for (const w of winners) {
    for (const r of rebuilders) {
      // Score by complementarity: bigger value gap × bigger age gap = better fit.
      const valueGap = w.totalValue - r.totalValue;
      const ageGap = (r.medianAge || 0) - (w.medianAge || 0);
      const score = Math.max(0, valueGap) * Math.max(0, ageGap || 1);
      partnerships.push({
        winnerOwnerId: w.ownerId,
        winnerName: w.name,
        rebuilderOwnerId: r.ownerId,
        rebuilderName: r.name,
        valueGap,
        ageGap,
        score,
      });
    }
  }
  partnerships.sort((a, b) => b.score - a.score);

  return {
    teams: enriched,
    leagueMedians,
    partnerships: partnerships.slice(0, 6),
  };
}
