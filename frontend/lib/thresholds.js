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

/**
 * Minimum ordinal-rank difference between the retail market and the expert
 * consensus before ANY surface puts a directional verb on a row.
 *
 * ONE constant because it is ONE quantity. `marketEdge` / `marketAction`
 * (display-helpers.js) compute |consensusMean − retailMean| from the
 * per-source ranks; the backend stamps the same number as
 * `marketGapMagnitude`, which `getPlayerEdge` (trade-logic.js) reads —
 * Brock Bowers: 5 either way. Until 2026-08-05 those two files applied 10
 * and a private `MIN_EDGE_RANK_GAP = 3` to it with no shared import, so 83
 * of 1,072 rows — Brock Bowers (#2), Bijan Robinson (#3), Drake Maye (#5),
 * Jahmyr Gibbs (#6), Trey McBride (#8), Lamar Jackson (#11) — rendered
 * HOLD in the /rankings Edge column and a full "Sell High" card in the
 * popup opened from that very row (W12-F001).
 *
 * The HIGHER floor won the merge: a mean-of-means over source ranks
 * flickers by several ranks between scrapes, so a verb resting on a
 * sub-10-rank gap is noise on either surface — and this cluster's rule is
 * to abstain on thin evidence rather than to widen who gets a verb.
 */
export const MARKET_GAP_MIN_DIFF = 10;

/**
 * Minimum number of NON-RETAIL sources that must have ranked a player
 * before the retail-vs-consensus gap may be called a consensus and carry a
 * directional verb.
 *
 * Two, because one source is not a consensus — it is a disagreement
 * between two numbers wearing the word. On the 2026-08-04 contract, 34 of
 * the 281 rows that cleared MARKET_GAP_MIN_DIFF had exactly ONE non-retail
 * source on the far side, and the UI framed that as "retail versus expert
 * consensus" (W12-F007). The count comes from the backend
 * (``marketGapConsensusSources``, stamped where the two sides are formed),
 * so both emitters gate on the same number.
 *
 * NOT gated on ``confidenceBucket``, and that is deliberate. Confidence is
 * source-rank AGREEMENT; the gap is source DISAGREEMENT — the same
 * dispersion, read twice. Measured on that contract, rows carrying a verb
 * had a median gap of 24.4 ranks at "low" confidence against 5.2 at
 * "high", so suppressing low-confidence verbs would delete the strongest
 * signals and keep the weakest, which inverts the feature rather than
 * gating it. Evidence sufficiency here means "how many independent voices",
 * not "how much did they agree".
 */
export const MIN_CONSENSUS_SOURCES_FOR_VERB = 2;

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
