// ── Shared thresholds ────────────────────────────────────────────────────────
// Single source of truth for numeric thresholds used across Rankings, Edge,
// and Finder surfaces.  Backend-authoritative thresholds (confidence spread
// cutoffs, disagreement threshold) mirror values in src/api/data_contract.py.
//
// When changing a threshold here, check whether the backend equivalent needs
// to match:
//   Python: _CONFIDENCE_SPREAD_HIGH (30), _CONFIDENCE_SPREAD_MEDIUM (80)
//   Python: _SUSPICIOUS_DISAGREEMENT_THRESHOLD (150)
//
// Tests: frontend/__tests__/thresholds.test.js
// ─────────────────────────────────────────────────────────────────────────────

// ── Confidence spread cutoffs ───────────────────────────────────────────────
// These mirror the backend confidence bucket thresholds exactly.
// High:   2+ sources AND spread <= CONFIDENCE_SPREAD_HIGH
// Medium: 2+ sources AND spread <= CONFIDENCE_SPREAD_MEDIUM
// Low:    single source OR spread > CONFIDENCE_SPREAD_MEDIUM

/** Max source-rank spread for "high" confidence bucket. */
export const CONFIDENCE_SPREAD_HIGH = 30;

/** Max source-rank spread for "medium" confidence bucket. */
export const CONFIDENCE_SPREAD_MEDIUM = 80;

// ── Market premium / disagreement thresholds ────────────────────────────────

/** Minimum spread for a row to qualify as a "market premium" (action label). */
export const MARKET_PREMIUM_SPREAD = 30;

/** Minimum spread for a row to appear in premium summary lists (edge rail). */
export const PREMIUM_SUMMARY_SPREAD = 20;

/** Minimum spread for "disagreements" lens on Rankings page. */
export const LENS_DISAGREEMENT_SPREAD = 40;

/** Minimum spread for "inefficiencies" lens (top-ranked players with spread). */
export const LENS_INEFFICIENCY_SPREAD = 30;

/** Maximum rank for "inefficiencies" lens eligibility. */
export const LENS_INEFFICIENCY_RANK = 200;

// ── Market gap ──────────────────────────────────────────────────────────────

/** Minimum rank difference for a market gap label to display. */
export const MARKET_GAP_MIN_DIFF = 10;

// ── Rank cutoffs ────────────────────────────────────────────────────────────

/** Maximum rank for flagged/single-source sections on Edge page. */
export const EDGE_CAUTION_RANK_LIMIT = 300;

/**
 * Maximum rank (by consensus OR retail/KTC) for players to appear in
 * the Edge page's Retail Premium / Consensus Premium sections.  Deep-
 * bench players can have huge source disagreements without any real
 * trade relevance, so we pin both premium sections to players inside
 * the top 200 of either scale.  A player qualifies when EITHER their
 * consensus rank is <= 200 OR their per-source KTC rank is <= 200.
 */
export const EDGE_PREMIUM_RANK_LIMIT = 200;

// ── Display limits ──────────────────────────────────────────────────────────
// These are page-level UX choices, not data thresholds.

/** Default number of rows shown on Rankings page before "show more". */
export const RANKINGS_DEFAULT_ROW_LIMIT = 200;

/** Maximum rows per workflow on Finder page. */
export const FINDER_ROW_LIMIT = 100;

/** Default items per Edge page section. */
export const EDGE_SECTION_LIMIT = 15;

/** Items per premium section on Edge page. */
export const EDGE_PREMIUM_LIMIT = 10;

// NOTE: The overall rank cap lives exclusively on the backend
// (src/api/data_contract.py defines the cap constant).  The
// frontend trusts the backend's cap and never imports or
// re-declares it — this keeps a single source of truth and prevents
// a parallel ranking engine from sneaking back in.
