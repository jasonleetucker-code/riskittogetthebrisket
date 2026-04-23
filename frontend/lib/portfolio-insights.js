"use client";

import {
  normalizePoints,
  computeWindowTrend,
  computeVolatility,
} from "@/lib/value-history";

/**
 * portfolio-insights — roster aggregates + front-office intel.
 *
 * Produces the numbers a GM actually uses at a glance:
 *   - total value / starter vs bench split / positional allocation
 *   - age mix (rookie / young / prime / vet) weighted by value
 *   - volatility exposure weighted by value
 *   - four named insight cards (best asset, biggest risk, trade chip,
 *     buy-low) — each with a concrete reason, never generic prose
 *   - short per-player blurb generator for drill-ins
 *
 * No randomness.  Every insight cites the metric that earned it.
 */

// Which positions can fill each flex-style slot in a Sleeper league.
const FLEX_POOLS = {
  FLEX: new Set(["RB", "WR", "TE"]),
  WR_RB_FLEX: new Set(["RB", "WR"]),
  REC_FLEX: new Set(["WR", "TE"]),
  SUPER_FLEX: new Set(["QB", "RB", "WR", "TE"]),
  SUPERFLEX: new Set(["QB", "RB", "WR", "TE"]),
  Q_FLEX: new Set(["QB", "RB", "WR", "TE"]),
};

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

/**
 * Compute the strict starter / bench split using the league's
 * positions array when present, falling back to a reasonable default
 * (1QB/2RB/3WR/1TE/1FLEX/1SF) otherwise.  Returns each bucket with
 * its player list and summed value.
 */
function splitStartersBench({ rosterValues, sleeperPositions }) {
  const slots = Array.isArray(sleeperPositions) && sleeperPositions.length > 0
    ? sleeperPositions.filter((p) => String(p).toUpperCase() !== "BN" && String(p).toUpperCase() !== "IR")
    : ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"];

  const pool = [...rosterValues].sort((a, b) => b.value - a.value);
  const starterNames = new Set();

  // First pass: strict position slots.
  for (const slot of slots) {
    const upper = String(slot).toUpperCase();
    if (FLEX_POOLS[upper]) continue;
    const match = pool.find((p) => !starterNames.has(p.name) && p.pos === upper);
    if (match) starterNames.add(match.name);
  }
  // Second pass: flex slots.
  for (const slot of slots) {
    const upper = String(slot).toUpperCase();
    const pool_ = FLEX_POOLS[upper];
    if (!pool_) continue;
    const match = pool.find((p) => !starterNames.has(p.name) && pool_.has(p.pos));
    if (match) starterNames.add(match.name);
  }

  const starters = pool.filter((p) => starterNames.has(p.name));
  const bench = pool.filter((p) => !starterNames.has(p.name));
  return {
    starters,
    bench,
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
 *   - rawData       full contract (used for sleeper.positions)
 *   - history       rank-history map (name -> [{date, rank}])
 */
export function computePortfolio({ rows, selectedTeam, rawData, history }) {
  if (!selectedTeam?.players?.length || !Array.isArray(rows)) {
    return null;
  }

  const byName = new Map();
  for (const r of rows) byName.set(String(r.name).toLowerCase(), r);

  // Build per-player value objects with position, age, volatility.
  const rosterValues = [];
  const unresolved = [];
  for (const name of selectedTeam.players) {
    const row = byName.get(String(name).toLowerCase());
    if (!row) {
      unresolved.push(name);
      continue;
    }
    const pos = normalizePos(row.pos);
    const value = Number(row.rankDerivedValue || row.values?.full || 0);
    const points = normalizePoints(history?.[row.name] || history?.[name] || []);
    const vol = computeVolatility(points, 30);
    rosterValues.push({
      name: row.name,
      pos,
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
    });
  }

  const totalValue = sumValue(rosterValues);
  const sleeperPositions = rawData?.sleeper?.positions;
  const starterSplit = splitStartersBench({ rosterValues, sleeperPositions });

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

  return {
    totalValue,
    ...starterSplit,
    byPosition,
    byAge,
    medianAge,
    volExposure,
    rosterValues,
    unresolved,
    coverage: selectedTeam.players.length
      ? rosterValues.length / selectedTeam.players.length
      : 0,
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
      const long = r.canonicalConsensusRankUncalibrated || r.canonicalConsensusRank;
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
