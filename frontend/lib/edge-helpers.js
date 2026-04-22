// ── Edge helpers ─────────────────────────────────────────────────────────────
// Shared logic for actionable lenses, edge summaries, and per-row action labels.
// Pure functions — no React dependencies, fully testable.
// Designed for reuse by /rankings, /edge, and /finder pages.
//
// All signals are derived from existing trust + source fields on the row object:
//   sourceRankSpread, confidenceBucket, isSingleSource, hasSourceDisagreement,
//   anomalyFlags, sourceRanks, marketGapDirection, quarantined, rank, sourceCount
//
// Nothing is predicted or editorialized.  Every label traces to a measurable
// property of the source data.
//
// Tests: frontend/__tests__/edge-helpers.test.js
// ─────────────────────────────────────────────────────────────────────────────

import {
  MARKET_PREMIUM_SPREAD,
  CONFIDENCE_SPREAD_HIGH,
  CONFIDENCE_SPREAD_MEDIUM,
  PREMIUM_SUMMARY_SPREAD,
  LENS_DISAGREEMENT_SPREAD,
  LENS_INEFFICIENCY_SPREAD,
  LENS_INEFFICIENCY_RANK,
  EDGE_CAUTION_RANK_LIMIT,
  EDGE_PREMIUM_RANK_LIMIT,
} from "./thresholds.js";
import { isEligibleForAnalysis } from "./display-helpers.js";
import { getRetailLabel } from "./dynasty-data.js";

/**
 * True when a row is "top-ranked" for the Edge page Premium sections
 * (Sell / Buy Signals).  Qualifies strictly by OUR consensus rank —
 * inside the top ``EDGE_PREMIUM_RANK_LIMIT`` (150 today) on the
 * blended board.
 *
 * Previously qualified on ``consensus OR ktc`` rank, which pulled in
 * players KTC priced high but our blend ranked deep (Mac Jones,
 * Jacoby Brissett, etc.).  That defeated the "only trade-relevant"
 * intent — if OUR board doesn't think a player is top-150, a market
 * gap on them isn't actionable.
 */
export function isTopRankedForEdgePremium(row) {
  if (!row) return false;
  const consensusRank = Number(row.rank);
  if (
    Number.isFinite(consensusRank) &&
    consensusRank >= 1 &&
    consensusRank <= EDGE_PREMIUM_RANK_LIMIT
  ) {
    return true;
  }
  return false;
}

// ── Action-frame labels ──────────────────────────────────────────────────────
// Each row gets at most one primary action label + optional caution labels.
// Rules are evaluated top-to-bottom; first match wins for primary.
// Caution labels can stack.

/**
 * Compute the primary action-frame label for a row.
 * Returns { label, css, title } or null.
 *
 * Priority:
 *   1. Market premium (source gap >= 30 ranks in a meaningful direction)
 *   2. Consensus asset (multi-source, high confidence, spread <= 30)
 *   3. null (no primary label — row is ordinary)
 */
export function actionLabel(row) {
  if (!row || row.quarantined) return null;

  // NOTE: The former "Market premium: X" action label was removed.
  // The Market/Edge column already renders this same information as
  // "KTC higher by N" / "Experts higher by N".  Duplicating it here
  // made every premium row carry two near-identical labels.
  //
  // The Signal column is now strictly: consensus asset (positive
  // informational) + any number of caution labels.  If you want the
  // retail-vs-expert gap, look at the Edge column.

  // Consensus asset: tight multi-source agreement.
  // Requires BOTH the ordinal-spread check AND the absence of the
  // percentile-spread disagreement flag, so we never render
  // "Consensus asset" and "Caution: wide disagreement" together.
  const spread = row.sourceRankSpread;
  if (
    row.confidenceBucket === "high" &&
    (row.sourceCount || 0) >= 2 &&
    (spread == null || spread <= CONFIDENCE_SPREAD_HIGH) &&
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

/**
 * Compute caution labels for a row.  Can return 0-N labels.
 * Each is { label, css, title }.
 */
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
    labels.push({
      label: "Caution: wide disagreement",
      css: "caution-disagree",
      title: `Sources disagree by more than ${CONFIDENCE_SPREAD_MEDIUM} rank positions`,
    });
  }
  return labels;
}

// ── Board lenses ─────────────────────────────────────────────────────────────
// Each lens is a { key, label, description, filter, sort } descriptor.
// filter(row) → boolean, sort(a,b) → number.
// The rankings page applies these to produce different board views.

/**
 * Lens definitions.  Each lens filters and sorts the ranked player list
 * to surface a specific type of signal.
 *
 * "consensus" is the default lens — shows all rows sorted by rank.
 */
export const LENSES = [
  {
    key: "consensus",
    label: "Consensus",
    description: "Standard board — all players sorted by unified rank.",
    filter: () => true,
    sort: null, // use default rank sort
  },
  {
    key: "disagreements",
    label: "Disagreements",
    description: `Players where sources disagree most. Spread > ${LENS_DISAGREEMENT_SPREAD} ranks between sources — potential mispricings or data issues.`,
    filter: (row) => (row.sourceRankSpread ?? 0) > LENS_DISAGREEMENT_SPREAD,
    sort: (a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0),
  },
  {
    key: "inefficiencies",
    label: "Inefficiencies",
    description: `Ranked players (top ${LENS_INEFFICIENCY_RANK}) with high source disagreement — where one market may be wrong. These are potential trade targets.`,
    filter: (row) => (row.rank ?? Infinity) <= LENS_INEFFICIENCY_RANK && (row.sourceRankSpread ?? 0) > LENS_INEFFICIENCY_SPREAD,
    sort: (a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0),
  },
  {
    key: "safest",
    label: "Safest",
    description: "High-confidence, multi-source assets with tight agreement. Lowest risk for trades — both markets agree on value.",
    filter: (row) => row.confidenceBucket === "high" && (row.sourceCount ?? 0) >= 2,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
  },
  {
    key: "fragile",
    label: "Fragile",
    description: "Single-source, low-confidence, or flagged assets. Higher risk — value is based on thinner evidence.",
    filter: (row) =>
      row.isSingleSource ||
      row.confidenceBucket === "low" ||
      (row.anomalyFlags || []).length > 0,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
  },
];

/**
 * Look up a lens by key.
 */
export function getLens(key) {
  return LENSES.find((l) => l.key === key) || LENSES[0];
}

/**
 * Apply a lens to a list of rows.
 * Returns filtered + sorted array (does not mutate input).
 */
export function applyLens(rows, lensKey) {
  const lens = getLens(lensKey);
  const filtered = rows.filter(lens.filter);
  if (lens.sort) {
    return [...filtered].sort(lens.sort);
  }
  return filtered;
}

// ── Edge summary computation ─────────────────────────────────────────────────
// Computes compact summary lists for the Edge rail.
// Each function returns an array of { name, pos, rank, detail } objects,
// capped at `limit` entries.

/**
 * Top players where the retail market (sources flagged `isRetail` in
 * the registry — today just KTC) ranks them much higher than the
 * expert consensus (every non-retail source averaged).  These are
 * players the retail market values more than the experts do.
 *
 * Sell signals: players the retail market values much higher than the
 * expert consensus — potential sells to retail-first trade partners.
 */
export function topRetailPremium(rows, limit = 5) {
  const retailLabel = getRetailLabel();
  return rows
    .filter((r) => r.marketGapDirection === "retail_premium" && (r.sourceRankSpread ?? 0) >= PREMIUM_SUMMARY_SPREAD && !r.quarantined)
    .sort((a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0))
    .slice(0, limit)
    .map((r) => ({
      name: r.name,
      pos: r.pos,
      rank: r.rank,
      detail: `Sell +${r.sourceRankSpread} ranks`,
      row: r,
    }));
}

/**
 * Buy signals: players the expert consensus values much higher than
 * the retail market — potential buy-low targets from retail-first
 * trade partners.
 */
export function topConsensusPremium(rows, limit = 5) {
  return rows
    .filter((r) => r.marketGapDirection === "consensus_premium" && (r.sourceRankSpread ?? 0) >= PREMIUM_SUMMARY_SPREAD && !r.quarantined)
    .sort((a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0))
    .slice(0, limit)
    .map((r) => ({
      name: r.name,
      pos: r.pos,
      rank: r.rank,
      detail: `Buy +${r.sourceRankSpread} ranks`,
      row: r,
    }));
}

/**
 * Top flagged players needing caution (anomaly flags, by rank).
 */
export function topFlaggedCautions(rows, limit = 5) {
  return rows
    .filter((r) => (r.anomalyFlags || []).length > 0 && (r.rank ?? Infinity) <= EDGE_CAUTION_RANK_LIMIT)
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

/**
 * Top high-confidence consensus assets (multi-source, tight agreement, best rank).
 */
export function topConsensusAssets(rows, limit = 5) {
  return rows
    .filter((r) => r.confidenceBucket === "high" && (r.sourceCount ?? 0) >= 2 && !r.quarantined)
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

/**
 * Compute all edge summary sections at once.
 * Returns an object with arrays for each section.
 */
export function computeEdgeSummary(rows) {
  // Pre-filter to ranked non-pick players
  const eligible = rows.filter(isEligibleForAnalysis);
  return {
    retailPremium: topRetailPremium(eligible),
    consensusPremium: topConsensusPremium(eligible),
    flaggedCautions: topFlaggedCautions(eligible),
    consensusAssets: topConsensusAssets(eligible),
  };
}
