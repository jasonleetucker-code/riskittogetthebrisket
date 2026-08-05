/**
 * team-phase — THE team-direction classifier for the frontend.
 *
 * ONE DEFINITION, AND WHAT IT REPLACED
 * ------------------------------------
 * Four independent team-direction classifiers shipped at once, three of
 * them reachable by a user, none referencing the others (audit
 * W20-F006 / W30-F016). On the same 12 live rosters they agreed on 3.
 * Brent was simultaneously "Contender", "#1 Contender",
 * "championship_contender" and "Seller".
 *
 *   1. this module's old 2×2 median split (top-25 value × median age →
 *      Win-now / Contender / Mixed / Rebuild), rendered on /phases
 *   2. `league-analysis.js::scoreTeamTiers` — `starters*0.7 +
 *      depth*0.2 − picks*0.1` cut into forced thirds, rendered on
 *      /rosters
 *   3. `src/roster_intel/window.py` — five affinity-weighted states
 *      over (competitiveness, trajectory), served by /api/gameplan
 *   4. `src/ros/direction.py` — seven buyer/seller labels off simulated
 *      playoff + championship odds, rendered on /league?tab=rosTradeDeadline
 *
 * (3) is nominated. It is the only one with a measured axis pair, the
 * only one that reports a DISTRIBUTION rather than picking a side of a
 * threshold, and the only one already under test. (1) and (2) are gone:
 * this file is a faithful port of window.py — identical state names,
 * anchors, axis weights, temperature and age bounds, pinned by
 * `frontend/__tests__/team-phase.test.js` against the same fixtures as
 * `tests/roster_intel/test_window.py`. (4) answers a different question
 * from a different input family (simulated odds, not roster shape) and
 * stays, but it now says which engine produced its number.
 *
 * Do not add a fifth. If a surface needs a direction label it imports
 * `classifyLeagueDirections` from here.
 *
 * WHY THE OLD MODEL HAD TO GO, CONCRETELY
 * ---------------------------------------
 * - `Rebuild` required `medianAge < leagueMedian(medianAge)` STRICTLY.
 *   Team medians over the top 25 land on integers; on the live snapshot
 *   the league median was 26.0 with six teams at exactly 26.0, all
 *   forced to the "older" side. Rebuild count: 0 of 12, so /phases'
 *   headline trade-partner feature rendered nothing (W20-F008).
 * - Both axes were median splits, so they were scale-blind above the
 *   median (×10 on one roster's value changed no label anywhere) and
 *   NON-LOCAL (halving Collin's value relabelled Ed, who did not trade)
 *   — W20-F009. The median moves when any team moves; an anchored
 *   softmax over percentile axes still moves, but continuously and
 *   without a cliff at the median.
 * - The sample was the top 25 BY VALUE, which systematically excludes
 *   the young cheap prospects a rebuild is made of. Trajectory is now
 *   measured over lineup ENTRANTS, weighted by value — window.py's
 *   rule, and for its reasons: a bench dart throw's age says nothing
 *   about a window, and an unweighted mean lets six rookies hide one
 *   33-year-old anchor.
 *
 * THE TWO AXES
 * ------------
 * - `competitiveness` (0-1): league percentile of the team's optimal
 *   STARTING-LINEUP value, solved by `starter-slots.js::fillLineup` —
 *   the tree's one answer to "who starts". This mirrors window.py's
 *   `lineupScoreRank` source exactly. The contract carries no playoff
 *   simulation on this path, so the odds-based source window.py
 *   prefers is unavailable here and every row is stamped
 *   `competitivenessSource` so the two are never confused.
 * - `trajectory` (0-1, 1 = young): value-weighted mean age of lineup
 *   entrants mapped onto [22, 32].
 *
 * Absence is never a number. No lineup slots → the source falls back to
 * total roster value and says so; no ages → trajectory is neutral and
 * `trajectorySample` is 0. Neither is silently dressed as a
 * measurement.
 *
 * No I/O — pure functions from the live contract.
 */

import { buildRowLookup, posGroup, PLAYER_GROUPS } from "@/lib/league-analysis";
import { parsePickToken, resolvePickRow } from "@/lib/trade-logic";
import { fillLineup } from "@/lib/starter-slots";

/** The five states, contend → rebuild. Mirrors `window.COMPETITIVE_STATES`. */
export const COMPETITIVE_STATES = Object.freeze([
  "championship_contender",
  "playoff_contender",
  "retool",
  "productive_struggle",
  "rebuild",
]);

/**
 * Display metadata. `order` is the contend→rebuild axis; see
 * `window.ORDERING_CAVEAT` — the ends are solid, the retool /
 * productive_struggle pair is a soft ordering because they are
 * different strategies at similar competitiveness.
 */
export const PHASES = Object.freeze({
  CHAMPIONSHIP_CONTENDER: {
    key: "championship_contender",
    label: "Championship contender",
    tone: "up",
    order: 0,
  },
  PLAYOFF_CONTENDER: {
    key: "playoff_contender",
    label: "Playoff contender",
    tone: "up",
    order: 1,
  },
  RETOOL: { key: "retool", label: "Retool", tone: "warn", order: 2 },
  PRODUCTIVE_STRUGGLE: {
    key: "productive_struggle",
    label: "Productive struggle",
    tone: "warn",
    order: 3,
  },
  REBUILD: { key: "rebuild", label: "Rebuild", tone: "down", order: 4 },
});

const PHASE_BY_KEY = Object.freeze(
  Object.fromEntries(Object.values(PHASES).map((p) => [p.key, p])),
);

export const ORDERING_CAVEAT =
  "States are ordered contend→rebuild, but the axis conflates current " +
  "competitiveness with directional intent. 'Retool' vs 'Productive " +
  "struggle' are different strategies at similar competitiveness, not " +
  "adjacent competitiveness levels; treat that pair's ordering as soft.";

// Each state's ideal position in (competitiveness, trajectory) space.
// Verbatim from `window._STATE_ANCHORS` — changing one without the
// other splits the definition again.
export const STATE_ANCHORS = Object.freeze({
  championship_contender: [0.95, 0.45],
  playoff_contender: [0.7, 0.5],
  retool: [0.45, 0.7],
  productive_struggle: [0.25, 0.8],
  rebuild: [0.05, 0.6],
});

export const COMPETITIVENESS_WEIGHT = 2.0;
export const TRAJECTORY_WEIGHT = 1.0;
export const DEFAULT_TEMPERATURE = 0.18;
const AGE_YOUNG = 22.0;
const AGE_OLD = 32.0;

/** Below this the single label must not be presented alone. */
export const AMBIGUOUS_BELOW = 0.3;

function clamp01(x) {
  if (!Number.isFinite(x)) return 0.5;
  return Math.max(0, Math.min(1, x));
}

/**
 * Self-inclusive midrank of `value` in `population`, on 0-1.
 * The JS twin of `src/utils/percentile.py` — same formula, same
 * all-identical-population answer (0.5), same "empty is absent"
 * policy: returns `null` rather than a confident 0.
 */
export function percentileRank(value, population) {
  const pop = (population || []).filter((v) => Number.isFinite(v));
  if (!pop.length || !Number.isFinite(value)) return null;
  const below = pop.filter((v) => v < value).length;
  const equal = pop.filter((v) => v === value).length;
  return (below + 0.5 * equal) / pop.length;
}

/**
 * Value-weighted mean age of lineup entrants → 0-1 (1 = young).
 * `entrants`: `[{ age, value }]`. Returns `{ score, sample }`;
 * sample 0 ⇒ score 0.5, the honest answer when no ages were supplied.
 */
export function trajectoryScore(entrants) {
  let weightedSum = 0;
  let weight = 0;
  let n = 0;
  for (const e of entrants || []) {
    // `Number(null)` is 0 and 0 is finite — a missing age would enter
    // the mean as a newborn. Reject the absent case before coercing.
    const age = e?.age == null || e.age === "" ? NaN : Number(e.age);
    const w = Math.max(0, Number(e?.value) || 0);
    if (!Number.isFinite(age) || w <= 0) continue;
    weightedSum += age * w;
    weight += w;
    n += 1;
  }
  if (weight <= 0 || n === 0) return { score: 0.5, sample: 0 };
  const meanAge = weightedSum / weight;
  return { score: clamp01((AGE_OLD - meanAge) / (AGE_OLD - AGE_YOUNG)), sample: n };
}

/**
 * Distance-to-anchor softmax over the five states. Port of
 * `window._softmax_affinities`.
 */
export function stateProbabilities(
  competitiveness,
  trajectory,
  temperature = DEFAULT_TEMPERATURE,
) {
  const scores = {};
  for (const state of COMPETITIVE_STATES) {
    const [ca, ta] = STATE_ANCHORS[state];
    scores[state] =
      -(
        COMPETITIVENESS_WEIGHT * (competitiveness - ca) ** 2 +
        TRAJECTORY_WEIGHT * (trajectory - ta) ** 2
      );
  }
  const temp = Math.max(1e-6, temperature);
  const mx = Math.max(...Object.values(scores));
  const exps = {};
  let total = 0;
  for (const [k, v] of Object.entries(scores)) {
    exps[k] = Math.exp((v - mx) / temp);
    total += exps[k];
  }
  const out = {};
  for (const k of COMPETITIVE_STATES) out[k] = exps[k] / total;
  return out;
}

/**
 * Classify one roster from its two measured axes.
 * Returns `{ probabilities, mostLikely, phase, confidence, ambiguous }`.
 */
export function classifyDirection({
  competitiveness,
  trajectory,
  temperature = DEFAULT_TEMPERATURE,
}) {
  const c = clamp01(competitiveness);
  const t = clamp01(trajectory);
  const probabilities = stateProbabilities(c, t, temperature);
  let mostLikely = COMPETITIVE_STATES[0];
  for (const s of COMPETITIVE_STATES) {
    if (probabilities[s] > probabilities[mostLikely]) mostLikely = s;
  }
  const confidence = probabilities[mostLikely];
  return {
    probabilities,
    mostLikely,
    phase: PHASE_BY_KEY[mostLikely],
    confidence,
    ambiguous: confidence < AMBIGUOUS_BELOW,
  };
}

/**
 * Classify a whole league at once — competitiveness is a league
 * percentile, so a roster cannot be classified alone.
 *
 * `teams`: `[{ key, lineupValue, entrants }]` where `entrants` is
 * `[{ age, value }]` for the players who actually enter the optimal
 * lineup. Anything else on the object is passed through untouched.
 */
export function classifyLeagueDirections(teams, { temperature = DEFAULT_TEMPERATURE } = {}) {
  const list = Array.isArray(teams) ? teams : [];
  // `Number(null)` is 0, so an absent lineup value would join the
  // population as a real last-place score. Drop it instead.
  const numeric = (v) => (v == null || v === "" || !Number.isFinite(Number(v)) ? null : Number(v));
  const population = list.map((t) => numeric(t?.lineupValue)).filter((v) => v != null);
  return list.map((team) => {
    const mine = numeric(team?.lineupValue);
    const pct = mine == null ? null : percentileRank(mine, population);
    // Exactly one team, or no measurable lineup value: there is no
    // league to be ranked against, so competitiveness is unmeasured.
    // 0.5 is stamped as "unavailable", never as a measurement.
    const competitiveness = pct == null ? 0.5 : pct;
    const competitivenessSource = pct == null ? "unavailable" : team.competitivenessSource;
    const { score: trajectory, sample } = trajectoryScore(team?.entrants);
    const classified = classifyDirection({ competitiveness, trajectory, temperature });
    return {
      ...team,
      ...classified,
      competitiveness,
      competitivenessSource,
      trajectory,
      trajectorySample: sample,
    };
  });
}

// ── The /phases + /rosters entry point ───────────────────────────────

function pickValueFor(team, rowLookup, pickAliases) {
  let total = 0;
  const names = Array.isArray(team?.picks) && team.picks.length
    ? team.picks
    : (team?.players || []).filter((p) => parsePickToken(p));
  for (const name of names) {
    if (!parsePickToken(name)) continue;
    const row = resolvePickRow(name, rowLookup, pickAliases);
    total += row ? row.values?.full || 0 : 0;
  }
  return total;
}

/**
 * Direction + value split for every team in the league.
 *
 * This is the ONE call both /phases and /rosters make. It owns the
 * lineup solve (shared `fillLineup`), so there is a single answer to
 * "who starts" feeding a single answer to "which way is this team
 * going".
 *
 * Returns `{ teams, partnerships, axes }`. `teams` rows carry the
 * classifier output plus `starterValue` / `depthValue` / `pickValue` /
 * `totalValue` for display.
 */
export function analyzeLeaguePhases(rawData, rows, options = {}) {
  const sleeperTeams = rawData?.sleeper?.teams || [];
  const rosterPositions =
    options.rosterPositions ?? rawData?.sleeper?.rosterPositions ?? null;
  const pickAliases = options.pickAliases ?? rawData?.pickAliases ?? null;
  if (!Array.isArray(sleeperTeams) || sleeperTeams.length === 0) {
    return { teams: [], partnerships: [], axes: { competitivenessSource: "unavailable" } };
  }

  const rowLookup = buildRowLookup(rows);
  const byName = new Map();
  for (const r of rows || []) {
    if (!r?.name || r.pos === "PICK" || r.pos === "K") continue;
    byName.set(String(r.name).toLowerCase(), {
      name: r.name,
      group: posGroup(r.pos),
      value: Number(r.values?.full ?? r.rankDerivedValue ?? 0) || 0,
      // Same `Number(null) === 0` trap as `trajectoryScore`: null stays
      // null so the sample count reports it as unmeasured.
      age: r.age == null || r.age === "" || !Number.isFinite(Number(r.age))
        ? null
        : Number(r.age),
    });
  }

  // No lineup slots means no lineup to solve. Say which proxy was used
  // rather than presenting roster-total order as a lineup order.
  const slotsAvailable = Array.isArray(rosterPositions) && rosterPositions.length > 0;
  const source = slotsAvailable ? "lineupScoreRank" : "rosterValueRank";

  const inputs = sleeperTeams.map((team) => {
    const lineupPool = [];
    let playerValue = 0;
    for (const pName of team?.players || []) {
      if (parsePickToken(pName)) continue;
      const pm = byName.get(String(pName || "").toLowerCase());
      if (!pm) continue;
      playerValue += pm.value;
      if (PLAYER_GROUPS.includes(pm.group)) lineupPool.push(pm);
    }
    const pickValue = pickValueFor(team, rowLookup, pickAliases);

    const { starters } = fillLineup({
      assets: lineupPool,
      rosterPositions,
      positionOf: (p) => p.group,
      valueFor: (p) => p.value,
    });
    const entrants = slotsAvailable ? starters : lineupPool;
    const starterValue = starters.reduce((s, p) => s + p.value, 0);

    return {
      key: String(team?.ownerId || team?.name || ""),
      name: team?.name || "Team",
      ownerId: String(team?.ownerId || ""),
      rosterId: String(team?.rosterId || ""),
      rosterCount: (team?.players || []).length,
      starterValue,
      depthValue: playerValue - starterValue,
      pickValue,
      totalValue: playerValue + pickValue,
      // Competitiveness ranks the STARTING lineup when the league's
      // slots are known, and the whole player pool when they are not.
      lineupValue: slotsAvailable ? starterValue : playerValue,
      competitivenessSource: source,
      entrants,
    };
  });

  const classified = classifyLeagueDirections(inputs, options).map((t) => {
    const { entrants: _drop, ...rest } = t;
    return rest;
  });

  classified.sort((a, b) => {
    if (a.phase.order !== b.phase.order) return a.phase.order - b.phase.order;
    return b.competitiveness - a.competitiveness;
  });

  // Natural trade partners: a contender buys win-now talent from a team
  // whose window is not open. Both "sell" states qualify — a
  // productive_struggle roster is young and losing, which is precisely
  // who a contender buys from.
  const BUYERS = new Set(["championship_contender", "playoff_contender"]);
  const SELLERS = new Set(["rebuild", "productive_struggle"]);
  const winners = classified.filter((t) => BUYERS.has(t.mostLikely));
  const rebuilders = classified.filter((t) => SELLERS.has(t.mostLikely));
  const partnerships = [];
  for (const w of winners) {
    for (const r of rebuilders) {
      // Complementarity: the gap on each axis. Both are 0-1, so the
      // product is comparable across leagues.
      const competitivenessGap = w.competitiveness - r.competitiveness;
      const trajectoryGap = r.trajectory - w.trajectory;
      partnerships.push({
        winnerOwnerId: w.ownerId,
        winnerName: w.name,
        rebuilderOwnerId: r.ownerId,
        rebuilderName: r.name,
        competitivenessGap,
        trajectoryGap,
        score: Math.max(0, competitivenessGap) * Math.max(0, trajectoryGap),
      });
    }
  }
  partnerships.sort((a, b) => b.score - a.score);

  return {
    teams: classified,
    partnerships: partnerships.slice(0, 6),
    axes: {
      competitivenessSource: source,
      slotsAvailable,
      temperature: options.temperature ?? DEFAULT_TEMPERATURE,
    },
  };
}
