// ── Shared thresholds ────────────────────────────────────────────────────────
// Single source of truth for numeric thresholds used across Rankings, Edge,
// and Finder surfaces.  Backend-authoritative thresholds (confidence spread
// cutoffs, disagreement threshold) mirror values in src/api/data_contract.py.
//
// When changing a threshold here, check whether the backend equivalent needs
// to match:
//   Python: _SUSPICIOUS_DISAGREEMENT_THRESHOLD (150)
//
// Tests: frontend/__tests__/thresholds.test.js
// ─────────────────────────────────────────────────────────────────────────────

// ── Confidence spread cutoffs — REMOVED 2026-08-05 ──────────────────────────
// `CONFIDENCE_SPREAD_HIGH` (30) and `CONFIDENCE_SPREAD_MEDIUM` (80) used to
// live here, described as mirroring "the backend confidence bucket thresholds
// exactly".  They did not.  `_confidence_bucket` in data_contract.py decides
// off the PERCENTILE spread on the normal `_compute_unified_rankings` path and
// only falls back to the absolute ordinal for callers that have nothing else —
// the percentile signal exists precisely so an IDP player ranked by 4 sources
// is judged on the same agreement scale as an offense player ranked by 14.
//
// Their one live consumer re-applied the ordinal rule ON TOP of the backend's
// own verdict.  Measured on the pinned 2026-07-30 contract, that suppressed
// "Consensus asset" on 54 of the 111 rows the backend calls high-confidence,
// multi-source and undisputed.
//
// Deleted rather than relabelled: a mirrored constant of a retired rule, with
// no remaining reader, is the exact shape that produced this bug.  The board's
// answer is `row.confidenceBucket`, stamped by the backend.
// See frontend/__tests__/consensus-label-reads-backend-bucket.test.js.

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
// RETIRED: MARKET_GAP_MIN_DIFF (was 10 ordinal ranks).  The market gap is
// no longer measured in rank space at all, so a rank threshold has nothing
// to gate.  Removed rather than left at its old value, where it would read
// as a live knob nobody is turning.

// Minimum RELATIVE gap, in blended-value space, for a market-gap label to
// fire.  Replaces MARKET_GAP_MIN_DIFF for that purpose.
//
// The gap used to be a difference of raw ordinal RANKS averaged across
// sources drawn from pools of very unequal depth (ktcSfTep 473 rows,
// idpTradeCalc 901, dlfSf 278).  Differencing ordinals across those pools
// measures pool depth and format basis, not opinion — measured on the
// 2026-08-05 board the median signed gap was TE +40.7 ranks while QB was
// -18.3, RB -9.3 and WR -6.0, i.e. every position negative and TE alone
// hugely positive.  That is not 15 independent boards agreeing about
// tight ends; it is a basis offset.
//
// In value space the same medians are QB +0.008, TE +0.084, WR +0.110,
// RB +0.112 — TE sits between the others instead of outside them.
//
// A relative gate, not an absolute one: 300 points of a 0-9999 scale is
// noise at the top of the board and a whole tier at rank 400.
//
// 0.05 is CALIBRATED, not chosen: on the live board it labels 68.8% of
// two-sided rows non-HOLD, against 69.2% under the old rank gate.  The
// point is to re-aim the signal, not to quietly silence it.
export const MARKET_GAP_MIN_VALUE_RATIO = 0.05;

// ── Rank cutoffs ────────────────────────────────────────────────────────────

/** Maximum rank for flagged/single-source sections on Edge page. */
export const EDGE_CAUTION_RANK_LIMIT = 300;

/**
 * Maximum OUR-consensus rank for players to appear in the Edge
 * page's Sell Signals / Buy Signals sections AND the rankings
 * page's Edge Summary rail.  Deep-bench players can have huge
 * source disagreements without any real trade relevance — so we
 * pin both surfaces to players inside the top 250 of the blended
 * board.
 *
 * Bumped 150 → 250 (2026-04-29) to surface mid-board WR / RB
 * disagreements that were previously filtered out (Elijah Moore /
 * Jahan Dotson / Ja'Lynn Polk class).  Previously qualified on
 * ``consensus <= 200 OR ktc <= 200``; the KTC-only path pulled in
 * low-rated players KTC happened to price highly (Mac Jones,
 * Jacoby Brissett, etc.) which defeated the "only trade-relevant"
 * intent.  Now single-filtered on consensus rank: if the blended
 * board doesn't think the player is top-250, no signal.
 */
export const EDGE_PREMIUM_RANK_LIMIT = 250;

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
