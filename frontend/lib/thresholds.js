// ── Shared thresholds ────────────────────────────────────────────────────────
// MIRROR OF config/thresholds.json — that file is the source of truth.
//
// This used to sync to the backend via a hand-written comment listing the
// Python constant names and their values.  A comment cannot fail a build, so
// whenever it disagreed with the code it was the comment people believed.
// It has been replaced by the mechanism that works elsewhere in this repo
// (see tests/api/test_source_registry_parity.py): a JSON source, a Python
// loader that CANNOT drift because it reads the JSON at import, and a parity
// test that fails when this mirror stops matching.
//
// To change a threshold: edit config/thresholds.json — including its
// `derivedFrom`, which is where the reason lives — then update the matching
// line here.  Adding a constant here that the JSON does not declare fails
// tests/api/test_threshold_parity.py by design.
// ─────────────────────────────────────────────────────────────────────────────

// ── Confidence spread cutoffs ───────────────────────────────────────────────
// High:   2+ sources AND spread <= CONFIDENCE_SPREAD_HIGH
// Medium: 2+ sources AND spread <= CONFIDENCE_SPREAD_MEDIUM
// Low:    single source OR spread > CONFIDENCE_SPREAD_MEDIUM

/** Max source-rank spread for "high" confidence bucket. */
export const CONFIDENCE_SPREAD_HIGH = 30;

/** Max source-rank spread for "medium" confidence bucket. */
export const CONFIDENCE_SPREAD_MEDIUM = 80;

// ── Source-disagreement thresholds ──────────────────────────────────────────
// These measure how much the SOURCES disagree with each other.  That is a
// different quantity from the market gap below, and conflating the two is
// audit finding S-3: the /edge premium panels used to gate and sort on
// disagreement while displaying the market gap's sign, so a clean large gap
// with tight source agreement was excluded and a tiny gap with wild
// disagreement sorted first.

/** Minimum spread for a row to qualify as a "market premium" (action label). */
export const MARKET_PREMIUM_SPREAD = 30;

/** Minimum spread for the /edge disagreements panel and the disagreement stat. */
export const PREMIUM_SUMMARY_SPREAD = 20;

/** Minimum spread for "disagreements" lens on Rankings page. */
export const LENS_DISAGREEMENT_SPREAD = 40;

/** Minimum spread for "inefficiencies" lens (top-ranked players with spread). */
export const LENS_INEFFICIENCY_SPREAD = 30;

/** Maximum rank for "inefficiencies" lens eligibility. */
export const LENS_INEFFICIENCY_RANK = 200;

// ── Market gap ──────────────────────────────────────────────────────────────
// UNIT: rank-space per-mille.  A source's rank divided by the depth of its
// own board, times 1000, with the position's median gap subtracted.  These
// are NOT ordinal ranks — the sources publish boards 278 to 900 rows deep, so
// ordinals were never comparable across them.  The backend stamps
// `marketGapUnit` on every row so a stale consumer can detect the change.

/** Minimum magnitude for a market-gap label to display at all. */
export const MARKET_GAP_MIN_MAGNITUDE = 25;

/** Minimum magnitude for an actionable buy/sell label. */
export const MARKET_PREMIUM_MAGNITUDE = 50;

/** Minimum magnitude for a row to appear in the /edge premium panels. */
export const PREMIUM_SUMMARY_MAGNITUDE = 50;

/** Minimum magnitude for the trade-page edge signal. */
export const MIN_EDGE_MAGNITUDE = 25;

/**
 * Minimum ORDINAL rank difference for the IDP market-gap label.
 *
 * Still ordinal on purpose: it gates the one surviving client-side gap
 * computation (display-helpers.js::idpMarketEdge), which exists because the
 * backend emits no market gap for IDP — the sole retail source publishes no
 * defenders.  It carries audit finding S-1 the way the offense path did
 * before C4, and is tracked as the IDP-anchor follow-up.
 */
export const MARKET_GAP_MIN_DIFF = 10;

/** Rows a position needs before its basis is trusted (backend-enforced). */
export const MARKET_GAP_MIN_POSITION_N = 8;

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
// These are page-level UX choices, not data thresholds, so they are NOT in
// config/thresholds.json and the parity test does not know about them.
// They are declared with a lowercase-free name but grouped apart on purpose;
// if one ever becomes a data threshold, move it into the JSON.

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
