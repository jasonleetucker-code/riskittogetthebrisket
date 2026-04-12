// ── Display helpers ──────────────────────────────────────────────────────────
// Shared presentational logic for badge CSS classes and label formatting.
// Used by rankings, edge, and finder pages.  Pure functions, no React.
//
// Tests: frontend/__tests__/display-helpers.test.js
// ─────────────────────────────────────────────────────────────────────────────

import { MARKET_GAP_MIN_DIFF } from "./thresholds.js";

/**
 * Return the CSS class for a position badge based on asset class.
 */
export function posBadgeClass(row) {
  if (row?.assetClass === "offense") return "badge badge-cyan";
  if (row?.assetClass === "idp") return "badge badge-amber";
  return "badge";
}

/**
 * Return the CSS class for a confidence badge.
 */
export function confBadgeClass(bucket) {
  if (bucket === "high") return "badge badge-green";
  if (bucket === "medium") return "badge badge-amber";
  return "badge badge-red";
}

/**
 * Return a short human label for a confidence bucket.
 */
export function confBadgeLabel(bucket) {
  if (bucket === "high") return "High";
  if (bucket === "medium") return "Med";
  return "Low";
}

// ── Eligibility filters ─────────────────────────────────────────────────────

/**
 * Returns true if a row is eligible for the ranked board.
 * Used by Rankings (which shows all eligible including unranked) and
 * by Edge/Finder (which further require r.rank to be set).
 */
export function isEligibleForBoard(row) {
  return !!row?.pos && row.pos !== "?" && row.pos !== "PICK";
}

/**
 * Returns true if a row is eligible for Edge/Finder analysis surfaces.
 * Requires a rank in addition to board eligibility.
 */
export function isEligibleForAnalysis(row) {
  return isEligibleForBoard(row) && !!row.rank;
}

/**
 * Return a short market-gap label string, or null if insignificant.
 *
 * "Market gap" is KTC (the retail offense market) vs the mean rank of
 * every other registered ranking source (the expert consensus — IDPTC,
 * DLF, etc.).  A KTC premium means the offense market values the
 * player more than the consensus does; a consensus premium is the
 * opposite.
 */
export function marketGapLabel(row) {
  if (!row?.sourceRanks) return null;
  const ktcRank = row.sourceRanks.ktc;
  if (!ktcRank) return null;

  const otherRanks = Object.entries(row.sourceRanks)
    .filter(([key, rank]) => key !== "ktc" && rank != null)
    .map(([, rank]) => Number(rank))
    .filter((n) => Number.isFinite(n));
  if (otherRanks.length === 0) return null;

  const consensusRank = otherRanks.reduce((s, v) => s + v, 0) / otherRanks.length;
  const diff = Math.round(Math.abs(consensusRank - ktcRank));
  if (diff < MARKET_GAP_MIN_DIFF) return null;
  const higher = ktcRank < consensusRank ? "KTC" : "Consensus";
  return `${higher} +${diff}`;
}
