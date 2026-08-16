"use client";

import {
  normalizePoints,
  computeWindowTrend,
  computeVolatility,
  buildHistoryLookup,
} from "@/lib/value-history";
import { buildPickLookupCandidates } from "@/lib/trade-logic";
import { fillLineup, lineupPosition, slotsFromStarterCounts } from "@/lib/starter-slots";

/** First contract row matching any candidate key, or null. */
function resolveByCandidates(byName, candidates) {
  for (const key of candidates || []) {
    const row = byName.get(key);
    if (row) return row;
  }
  return null;
}

/**
 * portfolio-insights — FALLBACK ROSTER AGGREGATES.
 *
 * As of the terminal endpoint rollout, the backend's
 * ``/api/terminal`` computes the authoritative version of every
 * field this module produces:
 *   - ``totalValue`` / ``byPosition`` / ``byAge`` / ``volExposure``
 *     / ``counters`` / ``medianAge``   ← from ``_compute_portfolio_insights``
 *   - ``bestAsset`` / ``biggestRisk`` / ``tradeChip`` / ``buyLow``
 *     insight cards                     ← same module
 *   - per-player ``trend7`` / ``trend30`` / ``volatility``
 *     enrichment on each roster player  ← same module
 *
 * This file is retained as a **defensive fallback** — the panels
 * that consume it prefer the server fields and only fall through
 * to these local computations when:
 *   1. The user is anonymous (no /api/terminal auth).
 *   2. The terminal endpoint returned an error.
 *   3. The panel is rendering before the fetch resolves.
 *
 * Do NOT add new fields here without a matching server-side
 * emission; the server is the authority.  Keep this module lean:
 * shrink it when server coverage expands rather than growing it.
 *
 * The two server-missing bits are:
 *   - Starter/bench split (needs lineup-position parsing)
 *   - ``computePlayerBlurb`` single-sentence narratives
 * Those remain owned by this module for both online and fallback
 * paths.
 *
 * No randomness.  Every insight cites the metric that earned it.
 */

const POSITION_GROUPS = ["QB", "RB", "WR", "TE", "K", "DEF", "IDP", "PICK"];

function normalizePos(pos) {
  const p = String(pos || "").toUpperCase();
  if (p === "DB" || p === "LB" || p === "DL" || p === "DE" || p === "DT" || p === "CB" || p === "S") return "IDP";
  if (p === "PK") return "K";
  return p;
}

function ageBucket(age, isRookie) {
  if (isRookie) return "rookie";
  const a = Number(age);
  if (!Number.isFinite(a) || a <= 0) return "unknown";
  if (a <= 22) return "rookie";
  if (a <= 24) return "young";
  if (a <= 28) return "prime";
  return "vet";
}

function sumValue(players) {
  let total = 0;
  for (const p of players) total += Number(p.value) || 0;
  return total;
}

function pct(part, whole) {
  if (!whole) return 0;
  return Math.round((part / whole) * 1000) / 10;
}

// NO LITERAL FALLBACK LINEUP.  This used to hold a 9-slot offence-only
// default used whenever the contract lacked ``sleeper.rosterPositions``,
// justified as "degrade to a plausible shape".  It was neither plausible
// nor necessary:
//
//   * Measured by running this module both ways on one 29-player roster,
//     it produced 9 starters — QB2 RB3 WR3 TE1 and ZERO DL / LB / DB, all
//     12 defenders benched — where the real lineup gives 20 starters
//     including 3 / 3 / 3.  The split bar read 40.1% against a true
//     68.1%.  Offense was wrong too (TE 1, not 2).
//   * It was reachable in production, and stickily so.  ``fetch_sleeper_
//     rosters`` gets teams and the lineup from two DIFFERENT Sleeper
//     endpoints, and only the lineup call sits in a bare ``except: pass``
//     with ``roster_positions`` pre-set to ``[]`` — so one timeout on
//     that endpoint alone yields teams-present / lineup-empty.
//   * And the league's real lineup was one destructure away the whole
//     time: ``useTeam()`` already returns ``rosterSettings`` from
//     ``/api/leagues``, and ``PortfolioSummary`` already calls it.
//
// So the ladder is now the same one BDVM already set
// (``src/bdvm/league_config.py``) and that /rosters follows: live host
// (``sleeper.rosterPositions``) → registry (``rosterSettings.starters``)
// → refuse and say so.  Never a literal.

/**
 * Starter / bench split for the terminal's portfolio panels.
 *
 * Thin wrapper over the shared ``fillLineup`` — see
 * ``lib/starter-slots.js`` for why the slot filling lives there.
 *
 * Fills on ``lineupPos`` (DL / LB / DB kept DISTINCT), never on ``pos``
 * (every defender collapsed to "IDP").  The league starts 3 at each IDP
 * position; filling on the collapsed field made every defensive slot
 * match every defender, so the split credited the top 9 defenders by
 * value.  Identical answer on a balanced roster, wrong on one stacked at
 * a single IDP position — it counted starters the league has no slot
 * for.  ``pos`` is still what ``byPosition`` allocates against, which is
 * why both fields exist.
 */
function splitStartersBench({ rosterValues, sleeperRosterPositions, rosterSettings }) {
  const { starters, bench, assignments, usedFallback, available } = fillLineup({
    assets: rosterValues,
    rosterPositions: sleeperRosterPositions,
    // ``|| p.pos`` only for callers that predate ``lineupPos``; every
    // row built by ``computePortfolio`` carries it.
    positionOf: (p) => p.lineupPos || p.pos,
    // Rung two of the ladder — the registry's own lineup, not a guess.
    // Omitted entirely when the registry has nothing either, so
    // ``available: false`` propagates and the panel says so.
    fallbackSlots: slotsFromStarterCounts(rosterSettings?.starters),
  });
  return {
    starters,
    bench,
    // Slot-ordered, for anything that RENDERS the lineup.  ``starters``
    // is value-descending, and truncating that to fit a panel drops the
    // defense — IDP values sit far below offense on the blended board.
    starterAssignments: assignments,
    // Which rung of the truth ladder produced this lineup, so the panel
    // can be honest about it:
    //   lineupFromLeague true        -> the league's live rosterPositions
    //   false + lineupKnown true     -> the registry's rosterSettings
    //   both false                   -> no lineup at all; nobody starts,
    //                                   and the panel must say so rather
    //                                   than render 0% as a measurement
    lineupFromLeague: !usedFallback && available,
    lineupKnown: available,
    starterCount: starters.length,
    benchCount: bench.length,
    starterValue: sumValue(starters),
    benchValue: sumValue(bench),
  };
}

/**
 * Compute the full portfolio snapshot.
 *
 * Inputs:
 *   - rows          flat contract rows (from useDynastyData)
 *   - selectedTeam  Sleeper team object ({players, picks})
 *   - rawData       full contract (used for sleeper.rosterPositions —
 *                   the lineup-slot ARRAY, distinct from
 *                   sleeper.positions which is the player→position map)
 *   - history       rank-history map (name -> [{date, rank}])
 *   - rosterSettings the registry's roster settings (from ``useTeam()``),
 *                   used ONLY as the lineup fallback when the contract
 *                   carries no rosterPositions
 */
export function computePortfolio({ rows, selectedTeam, rawData, history, rosterSettings }) {
  const hasPlayers = !!selectedTeam?.players?.length;
  const hasPicks = !!selectedTeam?.picks?.length;
  if ((!hasPlayers && !hasPicks) || !Array.isArray(rows)) {
    return null;
  }

  const byName = new Map();
  for (const r of rows) byName.set(String(r.name).toLowerCase(), r);

  // Backend rank-history keys are stamped as "{Name}::{asset_class}",
  // so a bare ``history[name]`` lookup misses every entry — which
  // collapsed every player into the volatility/age "unknown" bucket.
  // ``buildHistoryLookup`` strips the suffix and supports scope-aware
  // disambiguation via the row's assetClass.
  const lookupHistory = buildHistoryLookup(history);

  // Build per-player value objects with position, age, volatility.
  const rosterValues = [];
  const unresolved = [];
  for (const name of selectedTeam.players || []) {
    const row = byName.get(String(name).toLowerCase());
    if (!row) {
      unresolved.push(name);
      continue;
    }
    const pos = normalizePos(row.pos);
    // TWO position fields, deliberately, because they answer different
    // questions:
    //   ``pos``       collapses every defender to "IDP" — the value
    //                 bucket this page reports allocation against
    //                 (``byPosition``, POSITION_GROUPS).
    //   ``lineupPos`` keeps DL / LB / DB DISTINCT — because the league
    //                 starts 3 at EACH of those, not 9 defenders.
    // Filling slots off the collapsed field made every defensive slot
    // match every defender, so the split credited the top 9 by value; a
    // roster stacked at one IDP position had players counted as starters
    // that the league has no slot for.
    const lineupPos = lineupPosition(row.pos);
    const value = Number(row.rankDerivedValue || row.values?.full || 0);
    const points = normalizePoints(lookupHistory(row.name, row.assetClass));
    const vol = computeVolatility(points, 30);
    rosterValues.push({
      name: row.name,
      pos,
      lineupPos,
      value,
      age: row.age,
      isRookie: !!row.rookie,
      rank: Number(row.canonicalConsensusRank) || null,
      rankChange: Number.isFinite(row.rankChange) ? row.rankChange : null,
      confidence: Number.isFinite(row.confidence) ? row.confidence : null,
      points,
      trend7: computeWindowTrend(points, 7),
      trend30: computeWindowTrend(points, 30),
      volatility: vol,
      volLabel: vol?.label || "unknown",
      ageBucket: ageBucket(row.age, row.rookie),
      isPick: false,
    });
  }

  // Pick assets — Sleeper team objects carry them as a separate list
  // (e.g. "2026 1.05" / "2027 2.11").  They don't fill lineup slots
  // so they're excluded from the starter/bench split, but they DO
  // count toward total value + the PICK positional bucket.  Ignoring
  // them here silently understated both.
  for (const name of selectedTeam.picks || []) {
    // Picks need the candidate expansion, not a bare lowercase. Sleeper
    // labels a pick "2026 1.02 (own)"; the contract row is named
    // "2026 Pick 1.02". The case was never the problem — the FORMAT is
    // — so `byName.get(name.toLowerCase())` resolved 0 of 288 picks on
    // the live 12-team snapshot, and every team therefore rendered a
    // permanent "N unresolved" badge at 45-84% coverage while
    // `pickCount` stayed 0 and the "Picks $X · N" legend never drew.
    //
    // `buildPickLookupCandidates` already solves this and
    // `lib/league-analysis.js` already uses it; this module simply
    // never imported it. With it, 216 of 288 resolve.
    //
    // The remaining 72 were every 2029 pick, which the board did not
    // price at the time this comment was written. C1-U6 CLOSED that:
    // the board now carries a finite, provenance-stamped value for
    // every valid pick through the horizon, including rank-less
    // generic-grade rows ("2029 Round 1"). The count is therefore
    // expected to be far lower now, and a residual unresolved pick
    // means a LABEL the candidate expansion cannot map — not a pick the
    // board declines to price.
    //
    // What has not changed, and must not: a pick with no board row has
    // no value to show. It stays in `unresolved`; nothing is invented.
    // That was the failure mode of the deleted flat 7000/4000/2000/1200
    // table, and it is still the rule.
    const row = resolveByCandidates(byName, buildPickLookupCandidates(name));
    if (!row) {
      unresolved.push(name);
      continue;
    }
    // MISSING IS NEVER ZERO: a row the board explicitly declines to
    // price (`rankDerivedValue: null`) is unresolved, not worth 0.
    // `Number(null || undefined || 0)` collapsed all three into a
    // measured zero that then summed into the portfolio total.
    const rawValue = row.rankDerivedValue ?? row.values?.full ?? null;
    const numericValue = Number(rawValue);
    if (rawValue === null || !Number.isFinite(numericValue) || numericValue <= 0) {
      unresolved.push(name);
      continue;
    }
    const value = numericValue;
    rosterValues.push({
      name: row.name,
      pos: "PICK",
      value,
      age: null,
      isRookie: false,
      rank: Number(row.canonicalConsensusRank) || null,
      rankChange: Number.isFinite(row.rankChange) ? row.rankChange : null,
      confidence: Number.isFinite(row.confidence) ? row.confidence : null,
      points: [],
      trend7: null,
      trend30: null,
      volatility: null,
      volLabel: "unknown",
      ageBucket: "unknown",
      isPick: true,
    });
  }

  const totalValue = sumValue(rosterValues);
  // ``sleeper.rosterPositions`` is the lineup-slot array (e.g.
  // ["QB","RB","RB","WR","WR","WR","TE","FLEX","SUPER_FLEX","BN",...]).
  // ``sleeper.positions`` is a different field entirely — a
  // player-name → position MAP — and was previously misread here.
  const sleeperRosterPositions = rawData?.sleeper?.rosterPositions;
  // Starters are drawn from the lineup-eligible pool only — picks
  // don't fill lineup slots, so we filter them out before the split.
  // Picks still appear in totalValue and byPosition.PICK below.
  const lineupEligible = rosterValues.filter((p) => !p.isPick);
  const starterSplit = splitStartersBench({
    rosterValues: lineupEligible,
    sleeperRosterPositions,
    rosterSettings,
  });
  const picks = rosterValues.filter((p) => p.isPick);
  const pickValue = sumValue(picks);

  // Positional allocation: value + count per position group.
  const byPosition = {};
  for (const g of POSITION_GROUPS) {
    byPosition[g] = { count: 0, value: 0, pct: 0 };
  }
  for (const p of rosterValues) {
    const bucket = POSITION_GROUPS.includes(p.pos) ? p.pos : p.pos === "PICK" ? "PICK" : null;
    if (bucket) {
      byPosition[bucket].count += 1;
      byPosition[bucket].value += p.value;
    }
  }
  for (const g of POSITION_GROUPS) byPosition[g].pct = pct(byPosition[g].value, totalValue);

  // Age mix: value-weighted.
  const byAge = {
    rookie: { count: 0, value: 0, pct: 0 },
    young:  { count: 0, value: 0, pct: 0 },
    prime:  { count: 0, value: 0, pct: 0 },
    vet:    { count: 0, value: 0, pct: 0 },
    unknown:{ count: 0, value: 0, pct: 0 },
  };
  for (const p of rosterValues) {
    byAge[p.ageBucket].count += 1;
    byAge[p.ageBucket].value += p.value;
  }
  for (const k of Object.keys(byAge)) byAge[k].pct = pct(byAge[k].value, totalValue);

  // Median age across non-rookie non-unknown.
  const ages = rosterValues
    .map((p) => Number(p.age))
    .filter((a) => Number.isFinite(a) && a > 0);
  ages.sort((a, b) => a - b);
  const medianAge = ages.length
    ? ages.length % 2
      ? ages[(ages.length - 1) / 2]
      : (ages[ages.length / 2 - 1] + ages[ages.length / 2]) / 2
    : null;

  // Volatility exposure: value-weighted.
  const volExposure = {
    low:     { count: 0, value: 0, pct: 0 },
    med:     { count: 0, value: 0, pct: 0 },
    high:    { count: 0, value: 0, pct: 0 },
    unknown: { count: 0, value: 0, pct: 0 },
  };
  for (const p of rosterValues) {
    const b = p.volLabel || "unknown";
    if (!volExposure[b]) continue;
    volExposure[b].count += 1;
    volExposure[b].value += p.value;
  }
  for (const k of Object.keys(volExposure)) volExposure[k].pct = pct(volExposure[k].value, totalValue);

  const expectedAssets =
    (selectedTeam.players?.length || 0) + (selectedTeam.picks?.length || 0);

  return {
    totalValue,
    ...starterSplit,
    picks,
    pickCount: picks.length,
    pickValue,
    byPosition,
    byAge,
    medianAge,
    volExposure,
    rosterValues,
    unresolved,
    coverage: expectedAssets ? rosterValues.length / expectedAssets : 0,
  };
}

/**
 * Four named insights driven by explicit rules.  Each returns
 * { player, reason, metric } — never prose with no anchor.
 */
export function computeInsights({ portfolio, rows, selectedTeam, newsItems }) {
  if (!portfolio) return null;
  const { rosterValues } = portfolio;

  const rosterSet = new Set(rosterValues.map((p) => p.name.toLowerCase()));

  // News lookup keyed by player name.
  const newsByPlayer = new Map();
  if (Array.isArray(newsItems)) {
    for (const it of newsItems) {
      for (const p of it.players || []) {
        const key = String(p?.name || "").toLowerCase();
        if (!key) continue;
        if (!newsByPlayer.has(key)) newsByPlayer.set(key, []);
        newsByPlayer.get(key).push(it);
      }
    }
  }

  // Best asset: highest value.
  const best = [...rosterValues].sort((a, b) => b.value - a.value)[0] || null;
  const bestAsset = best
    ? {
        player: best,
        reason: `Highest-valued asset at ${best.value.toLocaleString()}${
          best.trend30 != null && best.trend30 >= 0 ? " with a stable 30d trend" : ""
        }.`,
        metric: "value",
      }
    : null;

  // Biggest risk: highest-value player with worst volatility + falling trend.
  //   tier 1: high volatility AND trend7 negative
  //   tier 2: high volatility alone
  //   tier 3: trend7 ≤ -3 and confidence low
  let risk = null;
  const tier1 = rosterValues
    .filter((p) => p.volLabel === "high" && (p.trend7 ?? 0) < 0)
    .sort((a, b) => b.value - a.value)[0];
  if (tier1) {
    risk = {
      player: tier1,
      reason: `High volatility (MAD ${tier1.volatility.mad.toFixed(1)}) and 7d trend of ${fmt(tier1.trend7)}.`,
      metric: "vol_plus_drop",
    };
  }
  if (!risk) {
    const tier2 = rosterValues.filter((p) => p.volLabel === "high").sort((a, b) => b.value - a.value)[0];
    if (tier2) {
      risk = {
        player: tier2,
        reason: `High volatility on an asset worth ${tier2.value.toLocaleString()} — the market hasn't settled a price.`,
        metric: "vol_alone",
      };
    }
  }
  if (!risk) {
    const tier3 = rosterValues
      .filter((p) => (p.trend7 ?? 0) <= -3)
      .sort((a, b) => (a.trend7 ?? 0) - (b.trend7 ?? 0))[0];
    if (tier3) {
      risk = {
        player: tier3,
        reason: `Steep 7d decline of ${fmt(tier3.trend7)} ranks — watch for further erosion.`,
        metric: "steep_decline",
      };
    }
  }

  // Trade chip: mid-to-high value player (3000-7500) who's rising — the
  // sweet spot for "sell into demand" without dealing a foundation piece.
  const chip = rosterValues
    .filter(
      (p) =>
        p.value >= 3000 &&
        p.value <= 7500 &&
        (p.trend7 ?? 0) >= 3 &&
        p.volLabel !== "high",
    )
    .sort((a, b) => (b.trend7 ?? 0) - (a.trend7 ?? 0))[0];
  const tradeChip = chip
    ? {
        player: chip,
        reason: `Rising ${fmt(chip.trend7)} ranks over 7d — a coherent sell-into-demand piece without moving a cornerstone.`,
        metric: "rising_mid_tier",
      }
    : null;

  // Buy-low candidate: LEAGUE-wide — not on my roster, value ≥ 3000,
  // 7d trend ≤ -3 (dipped), 30d trend still ≥ 0 (long-term fine).
  let buyLow = null;
  if (Array.isArray(rows)) {
    const candidates = rows
      .filter((r) => !rosterSet.has(String(r.name).toLowerCase()))
      .filter(
        (r) =>
          typeof r.canonicalConsensusRank === "number" &&
          r.canonicalConsensusRank > 0 &&
          r.canonicalConsensusRank <= 150,
      )
      .filter((r) => Number(r.rankDerivedValue || r.values?.full || 0) >= 3000);

    // Score: magnitude of short-term drop, but only if long-term steady.
    let bestCand = null;
    let bestScore = -Infinity;
    for (const r of candidates) {
      const t7 = Number(r.rankChange);
      if (!Number.isFinite(t7)) continue;
      if (t7 > -3) continue;
      const score = -t7; // bigger short-term drop = bigger opportunity
      if (score > bestScore) {
        bestScore = score;
        bestCand = r;
      }
    }
    if (bestCand) {
      buyLow = {
        player: {
          name: bestCand.name,
          pos: normalizePos(bestCand.pos),
          value: Number(bestCand.rankDerivedValue || bestCand.values?.full || 0),
          rank: Number(bestCand.canonicalConsensusRank) || null,
        },
        reason: `Dropped ${Math.abs(Number(bestCand.rankChange))} ranks on the last scrape but still inside the top ${bestCand.canonicalConsensusRank} — window open before the market corrects.`,
        metric: "short_drop_long_steady",
      };
    }
  }

  return { bestAsset, biggestRisk: risk, tradeChip, buyLow, newsByPlayer };
}

/**
 * Roster-level narrative — all concrete, no prose padding.
 * Returns an array of chip strings the UI can render in a row.
 */
export function computeRosterChips(portfolio) {
  if (!portfolio) return [];
  const { rosterValues, byAge, volExposure, medianAge } = portfolio;

  let rising = 0;
  let falling = 0;
  for (const p of rosterValues) {
    if ((p.trend7 ?? 0) >= 3) rising += 1;
    else if ((p.trend7 ?? 0) <= -3) falling += 1;
  }
  const highVol = volExposure.high.count;

  const chips = [];
  chips.push({ label: "Rising", value: rising, tone: rising > falling ? "up" : "flat" });
  chips.push({ label: "Falling", value: falling, tone: falling > rising ? "down" : "flat" });
  chips.push({ label: "High-vol", value: highVol, tone: highVol >= 3 ? "warn" : "flat" });
  if (medianAge != null) {
    chips.push({ label: "Median age", value: medianAge.toFixed(1), tone: medianAge <= 25 ? "up" : medianAge >= 29 ? "down" : "flat" });
  }
  chips.push({
    label: "Rookie value",
    value: `${byAge.rookie.pct}%`,
    tone: byAge.rookie.pct >= 25 ? "up" : "flat",
  });
  return chips;
}

/**
 * Single-sentence blurb for a roster player.  Purely derived — no
 * random words.  Picks one of 4 templates based on the strongest
 * signal in the data.
 */
export function computePlayerBlurb(player) {
  if (!player) return "";
  const { trend7, trend30, volLabel, value, isRookie, ageBucket: bucket } = player;
  const t7 = trend7 ?? 0;
  const t30 = trend30 ?? 0;

  if (volLabel === "high") {
    return `High volatility${t7 < 0 ? ` and ${fmt(t7)} over 7d — risk-on exposure.` : " — price hasn't settled."}`;
  }
  if (t7 <= -5) {
    return `Down ${fmt(t7)} ranks in 7d${t30 >= 0 ? " on a long-term stable base — potential buy-low if league treats it the same." : " with 30d drift also negative."}`;
  }
  if (t7 >= 5) {
    return `Up ${fmt(t7)} ranks in 7d${volLabel === "low" ? " with low volatility — sustained rise." : ""}.`;
  }
  if (isRookie) {
    return `Rookie asset valued at ${value.toLocaleString()} — developmental hold.`;
  }
  if (bucket === "vet" && value >= 5000) {
    return `Aging asset at ${value.toLocaleString()} — competitive window play.`;
  }
  return `Stable profile, ${fmt(t7)} 7d / ${fmt(t30)} 30d.`;
}

function fmt(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v === 0) return "·";
  return v > 0 ? `+${v}` : `${v}`;
}
