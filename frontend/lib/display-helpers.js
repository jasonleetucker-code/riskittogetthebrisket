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
 *
 * Picks get a distinct green badge so users can spot draft picks inline
 * alongside offense (cyan) and IDP (amber) rows on the rankings board
 * and in the trade calculator picker.
 */
export function posBadgeClass(row) {
  if (row?.assetClass === "offense") return "badge badge-cyan";
  if (row?.assetClass === "idp") return "badge badge-amber";
  if (row?.assetClass === "pick") return "badge badge-green";
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
 * Used by Rankings (which shows all eligible including unranked).
 *
 * Draft picks (pos "PICK") are included: KTC and IDPTradeCalc both
 * price picks on the same 0-9999 scale as players, so they get full
 * unified ranks from the backend and render alongside players on the
 * rankings board and in the trade calculator.
 */
export function isEligibleForBoard(row) {
  return !!row?.pos && row.pos !== "?";
}

/**
 * Returns true if a row is eligible for Edge/Finder analysis surfaces.
 * Requires a rank in addition to board eligibility.  Excludes picks:
 * the finder workflows (buy-low, sell-high, inefficiencies) are
 * player-discovery surfaces; draft picks are surfaced on the rankings
 * board and trade calculator, not the finder.
 */
export function isEligibleForAnalysis(row) {
  return isEligibleForBoard(row) && row.pos !== "PICK" && !!row.rank;
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
/**
 * Compute the structured market-edge descriptor for a row.
 *
 * Returns an object so callers can show explicit wording instead of the
 * legacy ambiguous dash.  The returned shape is always:
 *
 *   { label: string, css: string, title: string, kind: string }
 *
 * `kind` identifies the exact logic branch so UI code can render
 * different styles without re-implementing the branching:
 *   - "retail_higher"   retail prices player above consensus by >= threshold
 *   - "consensus_higher" consensus prices player above retail by >= threshold
 *   - "aligned"          both sides agree within threshold
 *   - "retail_only"      only retail sources ranked this player
 *   - "consensus_only"   only expert/consensus sources ranked this player
 *   - "unranked"         no per-source ranks available at all
 *
 * The legacy `marketGapLabel` behavior (returning a raw string or null)
 * is preserved in `marketGapLabelLegacy` for back-compat with tests.
 */
export function marketEdge(row) {
  const retailLabel = getRetailLabel();
  // Prefer ``effectiveSourceRanks`` (post-Hampel filter on the
  // backend) when present so retail-vs-consensus edge labels stay in
  // lockstep with backend marketGapDirection / confidence /
  // anomalyFlags.  Fall back to ``sourceRanks`` for legacy payloads.
  const ranks =
    row?.effectiveSourceRanks && Object.keys(row.effectiveSourceRanks).length > 0
      ? row.effectiveSourceRanks
      : row?.sourceRanks;
  if (!ranks || Object.keys(ranks).length === 0) {
    return {
      label: "unranked",
      css: "edge-none",
      kind: "unranked",
      title: "This player has no per-source ranks available.",
    };
  }
  const retailKeys = new Set(getRetailSourceKeys());

  const retailRanks = Object.entries(ranks)
    .filter(([key, rank]) => retailKeys.has(key) && rank != null)
    .map(([, rank]) => Number(rank))
    .filter((n) => Number.isFinite(n));

  const consensusRanks = Object.entries(ranks)
    .filter(([key, rank]) => !retailKeys.has(key) && rank != null)
    .map(([, rank]) => Number(rank))
    .filter((n) => Number.isFinite(n));

  if (retailRanks.length === 0 && consensusRanks.length > 0) {
    return {
      label: "expert only",
      css: "edge-none",
      kind: "consensus_only",
      title: `No ${retailLabel} rank for this player — only expert/consensus sources contributed.`,
    };
  }
  if (consensusRanks.length === 0 && retailRanks.length > 0) {
    return {
      label: `${retailLabel} only`,
      css: "edge-none",
      kind: "retail_only",
      title: `No expert/consensus rank for this player — only ${retailLabel} contributed.`,
    };
  }
  if (retailRanks.length === 0 && consensusRanks.length === 0) {
    return {
      label: "unranked",
      css: "edge-none",
      kind: "unranked",
      title: "This player has no per-source ranks available.",
    };
  }

  const retailMean = retailRanks.reduce((s, v) => s + v, 0) / retailRanks.length;
  const consensusMean =
    consensusRanks.reduce((s, v) => s + v, 0) / consensusRanks.length;
  const diff = Math.round(Math.abs(consensusMean - retailMean));

  if (diff < MARKET_GAP_MIN_DIFF) {
    return {
      label: "aligned",
      css: "edge-aligned",
      kind: "aligned",
      title: `${retailLabel} and expert consensus agree within ${MARKET_GAP_MIN_DIFF} ranks (actual difference: ${diff}).`,
    };
  }
  if (retailMean < consensusMean) {
    return {
      label: `${retailLabel} higher by ${diff}`,
      css: "edge-retail",
      kind: "retail_higher",
      title: `${retailLabel} ranks this player ~${diff} ordinal ranks above expert consensus.`,
    };
  }
  return {
    label: `Experts higher by ${diff}`,
    css: "edge-consensus",
    kind: "consensus_higher",
    title: `Expert consensus ranks this player ~${diff} ordinal ranks above ${retailLabel}.`,
  };
}

/**
 * Legacy string-only market gap label.  Retained for tests and any
 * consumer that still expects the old `"KTC +N"` / `"Consensus +N"` /
 * `null` contract.  New code should prefer `marketEdge()` which
 * returns an explicit structured object.
 */
export function marketGapLabel(row) {
  // Mirror ``marketEdge``: prefer the post-Hampel ``effectiveSourceRanks``
  // when stamped, fall back to ``sourceRanks`` for legacy payloads.
  const ranks =
    row?.effectiveSourceRanks && Object.keys(row.effectiveSourceRanks).length > 0
      ? row.effectiveSourceRanks
      : row?.sourceRanks;
  if (!ranks) return null;
  const retailKeys = new Set(getRetailSourceKeys());

  const retailRanks = Object.entries(ranks)
    .filter(([key, rank]) => retailKeys.has(key) && rank != null)
    .map(([, rank]) => Number(rank))
    .filter((n) => Number.isFinite(n));
  if (retailRanks.length === 0) return null;

  const consensusRanks = Object.entries(ranks)
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
