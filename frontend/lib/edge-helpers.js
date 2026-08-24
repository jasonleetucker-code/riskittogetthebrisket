// ── Edge helpers ─────────────────────────────────────────────────────────────
// Shared pure logic for actionable rankings lenses, finder screens, and edge
// summaries. The backend remains the only ranking/value engine; this module
// only compares backend-authored row fields.

import {
  MARKET_GAP_MIN_VALUE_RATIO,
  PREMIUM_SUMMARY_VALUE_RATIO,
  LENS_DISAGREEMENT_SPREAD,
  EDGE_CAUTION_RANK_LIMIT,
  EDGE_PREMIUM_RANK_LIMIT,
} from "./thresholds.js";
import {
  formatMarketGap,
  marketGapAtLeast,
  marketGapRatioOf,
  isEligibleForAnalysis,
} from "./display-helpers.js";
import { getRetailLabel } from "./dynasty-data.js";

function finitePositive(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function firstPrice(...values) {
  for (const value of values) {
    const n = finitePositive(value);
    if (n !== null) return n;
  }
  return null;
}

/**
 * Direct public-market arbitrage against OUR canonical value.
 *
 * This intentionally does not use sourceRankSpread and does not compare retail
 * to the expert-source mean. It answers the trade question directly:
 * "What do we think this asset is worth versus the public calculator price a
 * trade partner is likely to use?"
 *
 * Public transaction market:
 *   offense / picks -> KeepTradeCut SF/TEP
 *   IDP             -> IDP Trade Calculator
 *
 * Raw vendor values are preferred when present because they match the number a
 * partner sees on the public site. canonicalSites is the safe backend-stamped
 * fallback. Missing stays missing; it is never coerced to zero.
 *
 * ratio > 0 => our canonical value is higher => BUY arbitrage
 * ratio < 0 => public market is higher       => SELL arbitrage
 */
export function publicMarketArbitrage(row) {
  if (!row || row.quarantined) return null;

  const internalValue = firstPrice(row.rankDerivedValue, row.values?.full);
  if (internalValue === null) return null;

  const raw = row.rawSourceValues || {};
  const sites = row.canonicalSites || {};
  const isIdp = row.assetClass === "idp";

  const publicValue = isIdp
    ? firstPrice(raw.idpTradeCalc, sites.idpTradeCalc)
    : firstPrice(
        raw.ktcSfTep,
        raw.ktc,
        sites.ktcSfTep,
        sites.ktc,
      );

  if (publicValue === null) return null;

  // Express hidden surplus relative to the public transaction price: if KTC is
  // 5,000 and we value the player at 6,000, the actionable edge is +20%.
  const ratio = (internalValue - publicValue) / publicValue;
  if (!Number.isFinite(ratio)) return null;

  const direction = ratio > 0 ? "buy" : ratio < 0 ? "sell" : "hold";
  const market = isIdp ? "IDPTC" : "KTC";
  const hiddenSurplus = Math.round(internalValue - publicValue);

  // Maximum public-market spend while retaining at least the same calibrated
  // meaningful-gap floor internally. Useful for "looks fair on KTC/IDPTC but
  // still wins for us" trade construction. This is descriptive only and does
  // not alter canonical valuation or trade scoring.
  const maxPublicSpendForEdge = Math.floor(
    internalValue / (1 + MARKET_GAP_MIN_VALUE_RATIO),
  );
  const winWinRoom = Math.max(0, maxPublicSpendForEdge - publicValue);

  return {
    market,
    direction,
    internalValue: Math.round(internalValue),
    publicValue: Math.round(publicValue),
    hiddenSurplus,
    ratio,
    winWinRoom: Math.round(winWinRoom),
    maxPublicSpendForEdge,
  };
}

export function isTopRankedForEdgePremium(row) {
  if (!row) return false;
  const consensusRank = Number(row.rank);
  return (
    Number.isFinite(consensusRank) &&
    consensusRank >= 1 &&
    consensusRank <= EDGE_PREMIUM_RANK_LIMIT
  );
}

export function actionLabel(row) {
  if (!row || row.quarantined) return null;
  if (
    row.confidenceBucket === "high" &&
    (row.sourceCount || 0) >= 2 &&
    !row.hasSourceDisagreement
  ) {
    return {
      label: "Consensus asset",
      css: "action-consensus",
      title: "Multiple sources agree closely on this player's value",
    };
  }
  return null;
}

export function cautionLabels(row) {
  const labels = [];
  if (!row) return labels;
  if (row.isSingleSource) {
    labels.push({
      label: "Caution: single source",
      css: "caution-single",
      title: "Only one source contributed a value — confidence is lower",
    });
  }
  if ((row.anomalyFlags || []).length > 0 && !row.quarantined) {
    labels.push({
      label: "Caution: flagged",
      css: "caution-flagged",
      title: `Data quality flags: ${(row.anomalyFlags || []).join(", ")}`,
    });
  }
  if (row.hasSourceDisagreement) {
    let effectiveCount = null;
    if (
      row.effectiveSourceRanks &&
      Object.keys(row.effectiveSourceRanks).length > 0
    ) {
      effectiveCount = Object.keys(row.effectiveSourceRanks).length;
    } else if (row.sourceRanks && Array.isArray(row.droppedSources)) {
      const dropped = new Set(row.droppedSources);
      effectiveCount = Object.keys(row.sourceRanks).filter(
        (key) => !dropped.has(key),
      ).length;
    }
    const trimNote =
      effectiveCount != null && effectiveCount >= 5
        ? " (excluding the single most extreme source on each side)"
        : "";
    labels.push({
      label: "Caution: wide disagreement",
      css: "caution-disagree",
      title: `Sources split on this player's tier more than is typical at his rank depth${trimNote}`,
    });
  }
  return labels;
}

function arbitrageMagnitude(row) {
  return Math.abs(publicMarketArbitrage(row)?.ratio ?? 0);
}

function meaningfulArbitrage(row) {
  const edge = publicMarketArbitrage(row);
  return edge !== null && Math.abs(edge.ratio) >= MARKET_GAP_MIN_VALUE_RATIO;
}

export const LENSES = [
  {
    key: "consensus",
    label: "Consensus",
    description: "Standard board — all players sorted by unified rank.",
    filter: () => true,
    sort: null,
  },
  {
    key: "disagreements",
    label: "Source Disagreements",
    description: `Players where ranking sources disagree most. Spread > ${LENS_DISAGREEMENT_SPREAD} ranks — useful research context, not the market-arbitrage signal.`,
    filter: (row) =>
      (row.sourceRankSpread ?? 0) > LENS_DISAGREEMENT_SPREAD,
    sort: (a, b) =>
      (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0),
  },
  {
    // Preserve the historical key so bookmarked ?lens=inefficiencies URLs keep
    // working, but answer the actual product question now.
    key: "inefficiencies",
    label: "Market Arbitrage",
    description:
      "Our canonical value versus the public transaction market: KTC for offense/picks, IDP Trade Calculator for IDP. Buy opportunities (we value higher) are shown first; source disagreement remains a separate lens.",
    filter: (row) =>
      (row.rank ?? Infinity) <= EDGE_PREMIUM_RANK_LIMIT &&
      meaningfulArbitrage(row),
    sort: (a, b) => {
      const aEdge = publicMarketArbitrage(a);
      const bEdge = publicMarketArbitrage(b);
      // BUY opportunities first, strongest hidden surplus first. SELL
      // opportunities follow, strongest public premium first.
      const aBucket = aEdge?.direction === "buy" ? 0 : 1;
      const bBucket = bEdge?.direction === "buy" ? 0 : 1;
      if (aBucket !== bBucket) return aBucket - bBucket;
      return arbitrageMagnitude(b) - arbitrageMagnitude(a);
    },
  },
  {
    key: "safest",
    label: "Safest",
    description:
      "High-confidence, multi-source assets with tight agreement. Lowest risk for trades — both markets agree on value.",
    filter: (row) =>
      row.confidenceBucket === "high" && (row.sourceCount ?? 0) >= 2,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
  },
  {
    key: "fragile",
    label: "Fragile",
    description:
      "Single-source, low-confidence, or flagged assets. Higher risk — value is based on thinner evidence.",
    filter: (row) =>
      row.isSingleSource ||
      row.confidenceBucket === "low" ||
      (row.anomalyFlags || []).length > 0,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
  },
];

export const SCREENS = [
  {
    key: "wr-gaps",
    label: "WR Gaps",
    description:
      "Wide receivers where ranking sources disagree most — buy-low or sell-high depending on which market you trust.",
    filter: (r) =>
      r.pos === "WR" &&
      (r.sourceRankSpread ?? 0) > 15 &&
      (r.rank ?? Infinity) <= 250 &&
      !r.quarantined,
    sort: (a, b) =>
      (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0),
  },
  {
    key: "stable-idp",
    label: "Stable IDP",
    description:
      "IDP players with high confidence and tight multi-source agreement — the safest IDP trade targets.",
    filter: (r) =>
      r.assetClass === "idp" &&
      r.confidenceBucket === "high" &&
      (r.sourceCount ?? 0) >= 2 &&
      !r.quarantined,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
  },
  {
    key: "single-risk",
    label: "1-Source Risk",
    description:
      "Players valued from only one ranking source — value could shift sharply if another source disagrees.",
    filter: (r) => r.isSingleSource && (r.rank ?? Infinity) <= 300,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
  },
  {
    key: "rookie-spread",
    label: "Rookie Spread",
    description:
      "Rookies where sources disagree — upside signal if one market sees value the other doesn't.",
    filter: (r) =>
      r.rookie &&
      (r.sourceRankSpread ?? 0) > 10 &&
      (r.rank ?? Infinity) <= 400 &&
      !r.quarantined,
    sort: (a, b) =>
      (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0),
  },
];

const ALL_VIEWS = [...LENSES, ...SCREENS];

export function isScreen(key) {
  return SCREENS.some((screen) => screen.key === key);
}

export function getLens(key) {
  return ALL_VIEWS.find((lens) => lens.key === key) || LENSES[0];
}

export function applyLens(rows, lensKey) {
  const lens = getLens(lensKey);
  const filtered = rows.filter(lens.filter);
  return lens.sort ? [...filtered].sort(lens.sort) : filtered;
}

export function topRetailPremium(rows, limit = 5) {
  return rows
    .filter(
      (r) =>
        r.marketGapDirection === "retail_premium" &&
        marketGapAtLeast(r, PREMIUM_SUMMARY_VALUE_RATIO) &&
        !r.quarantined &&
        isTopRankedForEdgePremium(r),
    )
    .sort(
      (a, b) =>
        (marketGapRatioOf(b) ?? -Infinity) -
        (marketGapRatioOf(a) ?? -Infinity),
    )
    .slice(0, limit)
    .map((r) => ({
      name: r.name,
      pos: r.pos,
      rank: r.rank,
      detail: `Sell — retail ${formatMarketGap(r)} higher`,
      row: r,
    }));
}

export function topConsensusPremium(rows, limit = 5) {
  return rows
    .filter(
      (r) =>
        r.marketGapDirection === "consensus_premium" &&
        marketGapAtLeast(r, PREMIUM_SUMMARY_VALUE_RATIO) &&
        !r.quarantined &&
        isTopRankedForEdgePremium(r),
    )
    .sort(
      (a, b) =>
        (marketGapRatioOf(b) ?? -Infinity) -
        (marketGapRatioOf(a) ?? -Infinity),
    )
    .slice(0, limit)
    .map((r) => ({
      name: r.name,
      pos: r.pos,
      rank: r.rank,
      detail: `Buy — experts ${formatMarketGap(r)} higher`,
      row: r,
    }));
}

export function topFlaggedCautions(rows, limit = 5) {
  return rows
    .filter(
      (r) =>
        (r.anomalyFlags || []).length > 0 &&
        (r.rank ?? Infinity) <= EDGE_CAUTION_RANK_LIMIT,
    )
    .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
    .slice(0, limit)
    .map((r) => ({
      name: r.name,
      pos: r.pos,
      rank: r.rank,
      detail: (r.anomalyFlags || []).slice(0, 2).join(", "),
      row: r,
    }));
}

export function topConsensusAssets(rows, limit = 5) {
  return rows
    .filter(
      (r) =>
        r.confidenceBucket === "high" &&
        (r.sourceCount ?? 0) >= 2 &&
        !r.quarantined,
    )
    .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
    .slice(0, limit)
    .map((r) => ({
      name: r.name,
      pos: r.pos,
      rank: r.rank,
      detail: `spread ${r.sourceRankSpread ?? 0}`,
      row: r,
    }));
}

export function computeEdgeSummary(rows) {
  const eligible = rows.filter(isEligibleForAnalysis);
  return {
    retailPremium: topRetailPremium(eligible),
    consensusPremium: topConsensusPremium(eligible),
    flaggedCautions: topFlaggedCautions(eligible),
    consensusAssets: topConsensusAssets(eligible),
  };
}
