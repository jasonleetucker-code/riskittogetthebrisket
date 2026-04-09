// ── Display helpers ──────────────────────────────────────────────────────────
// Shared presentational logic for badge CSS classes and label formatting.
// Used by rankings, edge, and finder pages.  Pure functions, no React.
//
// Tests: frontend/__tests__/display-helpers.test.js
// ─────────────────────────────────────────────────────────────────────────────

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

/**
 * Return a short market-gap label string, or null if insignificant.
 */
export function marketGapLabel(row) {
  if (!row?.sourceRanks) return null;
  const ktcRank = row.sourceRanks.ktc;
  const idpRank = row.sourceRanks.idpTradeCalc;
  if (ktcRank && idpRank) {
    const diff = Math.abs(ktcRank - idpRank);
    if (diff < 10) return null;
    const higher = ktcRank < idpRank ? "KTC" : "IDPTC";
    return `${higher} +${diff}`;
  }
  return null;
}
