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
 */
export function marketGapLabel(row) {
  if (!row?.sourceRanks) return null;
  const ktcRank = row.sourceRanks.ktc;
  const idpRank = row.sourceRanks.idpTradeCalc;
  if (ktcRank && idpRank) {
    const diff = Math.abs(ktcRank - idpRank);
    if (diff < MARKET_GAP_MIN_DIFF) return null;
    const higher = ktcRank < idpRank ? "KTC" : "IDPTC";
    return `${higher} +${diff}`;
  }
  return null;
}
