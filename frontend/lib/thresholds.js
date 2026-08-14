// ── Shared thresholds ────────────────────────────────────────────────────────
// MIRROR OF config/thresholds.json — that file is the source of truth.
//
// This used to sync to the backend via a hand-written comment listing the
// Python constant names and their values.  A comment cannot fail a build, so
// whenever it disagreed with the code it was the comment people believed —
// and #725 measured the cost of exactly that: two of the constants it listed
// described a rule the backend had retired.
// It has been replaced by the mechanism that works elsewhere in this repo
// (see tests/api/test_source_registry_parity.py): a JSON source, a Python
// loader that CANNOT drift because it reads the JSON at import, and a parity
// test that fails when this mirror stops matching.
//
// One backend constant still has no mirror here and should not gain one
// without a reader: _SUSPICIOUS_DISAGREEMENT_THRESHOLD (150).
//
// To change a threshold: edit config/thresholds.json — including its
// `derivedFrom`, which is where the reason lives — then update the matching
// line here.  Adding a constant here that the JSON does not declare fails
// tests/api/test_threshold_parity.py by design.
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
// UNIT: a RELATIVE gap in blended-value space.  0.25 means one side prices the
// player 25% above the other.  These are not ranks and not points on the
// 0-9999 scale.  The backend publishes it as `marketGapValueRatio`; the old
// `marketGapMagnitude` is stamped None on every row precisely so a consumer
// still reading it fails visibly instead of gating on a stale unit.

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

/**
 * Minimum relative gap for a row to appear in the /edge premium panels.
 *
 * Those panels used to gate and sort on `sourceRankSpread` — how much the
 * SOURCES disagree with each other — while displaying the market gap's sign
 * (audit S-3).  Two different quantities: a clean, large gap on a player every
 * source agrees about was excluded outright, while a negligible gap on a
 * player they were arguing over sorted first.
 *
 * 0.15 is p70 of |marketGapValueRatio| across the 414 two-sided rows on the
 * 2026-08-05 board (0.1565), giving 127 candidates before the top-250 filter
 * — the same order as the 148 the spread gate passed, so this re-aims the
 * panel rather than silently emptying or flooding it.
 *
 * Deliberately NOT a separate constant for the trade page: `getPlayerEdge`
 * reuses MARKET_GAP_MIN_VALUE_RATIO, because if the board will not label a
 * gap, a trade surface must not signal on it.  Four thresholds gated this one
 * concept before; there are now two.
 */
export const PREMIUM_SUMMARY_VALUE_RATIO = 0.15;

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

// ── ROS context tags (B9b) ───────────────────────────────────────────────────
// These replaced absolute gates on `rosValue`, a 0-100 STRENGTH INDEX that the
// old constants treated as if it were a percentile. Measured 2026-08-14 over
// 1,031 players and corroborated across all 893 historical aggregates back to
// 2026-04-28: the index's median is 9.15 and its 99th percentile is 59.41, so
// `rosValue >= 80` ("elite") selected 2 players and `>= 60` ("strong") selected
// 9 — while the complement of "strong" labelled 99.13% of the pool
// "Injury/bye cover". A percentile states the intended population directly and
// cannot drift when the index's distribution moves.
//
// `rosPercentile` is stamped by the backend over the WHOLE pool. Do not
// recompute it here: /api/ros/player-values truncates to `limit` (500), so a
// standing computed from the response is a standing within the top half.
export const ROS_ELITE_PERCENTILE = 95;
export const ROS_STRONG_PERCENTILE = 75;
export const ROS_DEPTH_BAND_LOW_PERCENTILE = 40;

// Percentile POINTS, not a percentile: the gap between a player's ROS standing
// and their dynasty standing. W29-F005 — the predicate was
// `dynastyValue < rosValue * 0.7`, comparing a 0-9999 board value against the
// 0-100 index, so it could not fire for any of the 1,093 rows and never had.
export const ROS_SELLER_PERCENTILE_GAP = 25;
