/**
 * team-phase — classify each team in the league as
 * Win-now / Contender / Mixed / Rebuild from the canonical Team
 * Strength + age-value portfolio owners.
 *
 * V1-31 audit finding F-3 (`docs/roster-intelligence/V1_35_METRIC_SEPARATION_AUDIT.md`):
 * this module used to derive its own "how good is this team" number —
 * a client-side top-25 `rankDerivedValue` sum plus a raw per-player age
 * lookup — independently of `src/roster_intel/strength.py` (feature
 * inventory row 1.1, THE canonical Team Strength owner). Two production
 * surfaces disagreeing about "how strong is this roster" is exactly the
 * defect V1-31 exists to remove.
 *
 * Retired: the top-25 value sum and the raw age lookup. Kept: the
 * classification RULE itself (value vs. league median, age vs. league
 * median → 4 quadrants) and the trade-partner complementarity scoring —
 * neither is a "position weight" or a "weakness threshold" the owner
 * has decided; they are a generic bucketing of two axes that now come
 * from canonical sources:
 *
 *   value  <- strengthTotal          (src/roster_intel/strength.py, meaningful core)
 *   age    <- valueWeightedCoreAge   (src/roster_intel/age_portfolio.py)
 *
 * Both are already served, league-wide, by `GET /api/roster/intelligence`
 * (`payload.leagueContext`, reshaped by `lib/roster-intelligence.js::teamStrengthLadder`)
 * — no second backend call and no new backend field.
 *
 * No I/O here — pure function over the ladder `useRosterIntelligence`
 * already fetched.
 */

const PHASES = Object.freeze({
  WIN_NOW: { key: "win_now", label: "Win-now", tone: "up", order: 0 },
  CONTENDER: { key: "contender", label: "Contender", tone: "up", order: 1 },
  MIXED: { key: "mixed", label: "Mixed", tone: "warn", order: 2 },
  REBUILD: { key: "rebuild", label: "Rebuild", tone: "down", order: 3 },
});
export { PHASES };

function median(values) {
  const arr = (values || [])
    .filter((v) => Number.isFinite(v))
    .sort((a, b) => a - b);
  if (!arr.length) return null;
  const mid = Math.floor(arr.length / 2);
  return arr.length % 2 ? arr[mid] : (arr[mid - 1] + arr[mid]) / 2;
}

function classifyPhase(snapshot, leagueMedians) {
  const { totalValue, medianAge } = snapshot;
  const isHighValue = leagueMedians.value != null && totalValue != null && totalValue > leagueMedians.value;
  // ``younger`` is < the league's median age. When either side is
  // unmeasured, default to "older" so a team with missing data doesn't
  // get pushed into the youth corner.
  const isYounger =
    medianAge != null && leagueMedians.age != null && medianAge < leagueMedians.age;

  if (isHighValue && isYounger) return PHASES.WIN_NOW;
  if (isHighValue && !isYounger) return PHASES.CONTENDER;
  if (!isHighValue && isYounger) return PHASES.REBUILD;
  return PHASES.MIXED;
}

/**
 * @param {Array} ladder — `teamStrengthLadder(payload, {myOwnerId})` rows:
 *   `{ownerId, teamName, strengthTotal, valueWeightedCoreAge, isMe, ...}`
 */
export function analyzeLeaguePhases(ladder) {
  const rows = Array.isArray(ladder) ? ladder : [];
  if (!rows.length) {
    return { teams: [], leagueMedians: { value: null, age: null }, partnerships: [] };
  }

  const snapshots = rows.map((t) => ({
    name: t.teamName || "Team",
    ownerId: String(t.ownerId || ""),
    isMe: Boolean(t.isMe),
    totalValue: t.strengthTotal,
    medianAge: t.valueWeightedCoreAge,
  }));

  const leagueMedians = {
    value: median(snapshots.map((s) => s.totalValue)),
    age: median(snapshots.map((s) => s.medianAge)),
  };

  const enriched = snapshots.map((s) => ({ ...s, phase: classifyPhase(s, leagueMedians) }));

  enriched.sort((a, b) => {
    if (a.phase.order !== b.phase.order) return a.phase.order - b.phase.order;
    return (b.totalValue ?? -Infinity) - (a.totalValue ?? -Infinity);
  });

  const winners = enriched.filter((t) => t.phase.key === "win_now" || t.phase.key === "contender");
  const rebuilders = enriched.filter((t) => t.phase.key === "rebuild");
  const partnerships = [];
  for (const w of winners) {
    for (const r of rebuilders) {
      // An unmeasured value OR age must not silently become a real
      // number in a complementarity SCORE that ranks recommendations —
      // that is exactly the missing-is-never-zero violation the retired
      // formula's own `|| 0` fallbacks used to commit. Skip the pairing
      // rather than fabricate a gap.
      if (w.totalValue == null || r.totalValue == null) continue;
      if (w.medianAge == null || r.medianAge == null) continue;
      // Score by complementarity: bigger value gap x bigger age gap =
      // better fit. Unchanged rule from the retired formula — only the
      // two inputs it reads are now canonical.
      const valueGap = w.totalValue - r.totalValue;
      const ageGap = r.medianAge - w.medianAge;
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
