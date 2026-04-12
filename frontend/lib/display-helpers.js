// ── Display helpers ──────────────────────────────────────────────────────────
// Shared presentational logic for badge CSS classes and label formatting.
// Used by rankings, edge, and finder pages.  Pure functions, no React.
//
// Tests: frontend/__tests__/display-helpers.test.js
// ─────────────────────────────────────────────────────────────────────────────

import { MARKET_GAP_MIN_DIFF } from "./thresholds.js";
import { getRetailSourceKeys, getRetailLabel } from "./dynasty-data.js";

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
 * "Market gap" frames the retail market (sources flagged `isRetail` in
 * the registry — today just KTC) against every other registered
 * source (the expert consensus — IDPTC, DLF, etc.).  Both sides are
 * averaged and the label shows the side that ranks the player higher
 * and by how many ordinal ranks.  A "KTC +N" label means retail values
 * the player more than the consensus does; a "Consensus +N" label is
 * the reverse.
 *
 * The retail side label is resolved dynamically from the registry via
 * `getRetailLabel()`, so adding a second retail source flips the label
 * to the generic "Retail" with no code edits here.
 */
export function marketGapLabel(row) {
  if (!row?.sourceRanks) return null;
  const retailKeys = new Set(getRetailSourceKeys());

  const retailRanks = Object.entries(row.sourceRanks)
    .filter(([key, rank]) => retailKeys.has(key) && rank != null)
    .map(([, rank]) => Number(rank))
    .filter((n) => Number.isFinite(n));
  if (retailRanks.length === 0) return null;

  const consensusRanks = Object.entries(row.sourceRanks)
    .filter(([key, rank]) => !retailKeys.has(key) && rank != null)
    .map(([, rank]) => Number(rank))
    .filter((n) => Number.isFinite(n));
  if (consensusRanks.length === 0) return null;

  const retailMean = retailRanks.reduce((s, v) => s + v, 0) / retailRanks.length;
  const consensusMean =
    consensusRanks.reduce((s, v) => s + v, 0) / consensusRanks.length;
  const diff = Math.round(Math.abs(consensusMean - retailMean));
  if (diff < MARKET_GAP_MIN_DIFF) return null;
  const higher = retailMean < consensusMean ? getRetailLabel() : "Consensus";
  return `${higher} +${diff}`;
}
