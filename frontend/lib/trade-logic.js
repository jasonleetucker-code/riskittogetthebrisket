/**
 * Trade calculator logic — the authoritative implementation for Next.js.
 * Covers: value modes, power-weighted totals, edge detection,
 * pick valuation, verdict calculation, persistence.
 *
 * No React dependencies — pure functions + constants.
 */

// ── Value Modes ──────────────────────────────────────────────────────────
export const VALUE_MODES = [
  { key: "full", label: "Our Value" },
  { key: "raw", label: "Raw" },
];

// ── Persistence Keys ─────────────────────────────────────────────────────
export const STORAGE_KEY = "next_trade_workspace_v1";
export const RECENT_KEY = "next_trade_recent_assets_v1";
export const SETTINGS_KEY = "next_settings_v2";

// ── Verdict Thresholds (1–9999 scale) ────────────────────────────────────
const VERDICT_NEAR_EVEN = 350;
const VERDICT_LEAN = 900;
const VERDICT_STRONG_LEAN = 1800;

// ── Legacy Power-Weighted Alpha (trade history only) ─────────────────────
// The Trade Calculator no longer uses this; it has moved to the KTC-style
// Value Adjustment model below.  `TRADE_ALPHA` is kept as a retrospective
// grading exponent for past trades on the `/trades` history page, where a
// consolidation premium can't be attributed after the fact.
export const TRADE_ALPHA = 1.65;

// ── KTC-Style Value Adjustment (V12 — KTC's actual published formula) ───
//
// V12 is the EXACT algorithm KTC uses, reverse-engineered from KTC's
// client-side JavaScript and corroborated by KTC's own Reddit
// explanation.  It supersedes the previous hand-tuned V2 formula.
//
// Per-player raw adjustment:
//
//   raw(p, t, v) = p · (0.1
//                       + 0.04 · (p / v)^8
//                       + 0.11 · (p / t)^1.3
//                       + 0.22 · (p / (v + 2000))^1.28)
//
// where:
//   p = this player's KTC value
//   t = max KTC value among players IN the trade
//   v = max KTC value overall (~9999, e.g. Josh Allen)
//
// Algorithm to compute the displayed Value Adjustment:
//   1. Compute raw(p, t, v) for every player on each side.
//   2. Sum raw per side.  Side with bigger raw_sum has the bigger studs.
//   3. Compute raw_diff = bigger_raw - smaller_raw.
//   4. Solve for player value X such that raw(X, t, v) ≈ raw_diff
//      (the smaller-raw side needs a virtual player worth X to even).
//   5. Displayed VA = (smaller_raw_side_total + X) - bigger_raw_side_total,
//      applied to the side with the bigger raw_sum.
//
// Special cases:
//   - 1v1 trades → VA = 0 (KTC empirically suppresses VA for these,
//     even when the formula would produce one).
//   - Equal raw_sum → VA = 0.
//   - Cases where small (DataPoint convention) doesn't have the
//     bigger raw → VA on small = 0; the trade favors large.
//
// Calibration on 100 fresh KTC captures (2026-04-25, 15 topologies):
//
//   V2 prod (replaced):  rms = 69.6%   mean = 58.4%   max = 112%
//   V12 KTC actual:      rms = 39.3%   mean = 24.7%   max = 100%
//
// V12 cuts RMS by 44% and mean error by 58% on current KTC behavior.
// The script ``scripts/calibrate_va_formula.py`` runs the comparison
// against the captured fixture in ``scripts/ktc_va_observations.json``.
//
// V12 is closed-form — no parameters to tune.  The constants 0.1 /
// 0.04 / 0.11 / 0.22 and exponents 8 / 1.3 / 1.28 are KTC's own.

// Max KTC value overall — Josh Allen sits here.  Effectively constant
// across the lifetime of any deployed build; refresh if the top
// player's value drifts more than ±5%.
export const KTC_V_OVERALL_MAX = 9999;

// Backward-compat exports — kept so any test file or downstream
// consumer that imports these by name still resolves.  The values are
// unused at runtime now that V12 replaces V2.  Will be removed once
// the 2026-Q3 deprecation window passes.
export const VA_SCARCITY_SLOPE = 3.75;
export const VA_SCARCITY_INTERCEPT = 0.45;
export const VA_SCARCITY_CAP = 0.55;
export const VA_PER_EXTRA_BOOST = 1.4;
export const VA_EFFECTIVE_CAP = 1.0;
export const VA_POSITION_DECAY = 0.35;

/**
 * KTC's per-player raw adjustment, the inner term of V12.
 *
 * Pure function — same inputs always produce the same output, no
 * hidden state.  ``Math.pow`` handles the fractional exponents fine
 * for the value ranges we deal with (0–9999).
 *
 * @param {number} p - this player's KTC value
 * @param {number} t - max KTC value among players in the trade
 * @param {number} [v=KTC_V_OVERALL_MAX] - max KTC value overall
 * @returns {number} the player's raw adjustment contribution
 */
export function ktcRawAdjustment(p, t, v = KTC_V_OVERALL_MAX) {
  if (!(p > 0)) return 0;
  const pv = v > 0 ? p / v : 0;
  const ptRatio = t > 0 ? p / t : 0;
  const pv2k = p / (v + 2000);
  return p * (
    0.1
    + 0.04 * Math.pow(pv, 8)
    + 0.11 * Math.pow(ptRatio, 1.3)
    + 0.22 * Math.pow(pv2k, 1.28)
  );
}

/**
 * Find player value X such that ``ktcRawAdjustment(X, t, v) ≈ target``.
 *
 * Binary search.  ``ktcRawAdjustment`` is monotonically increasing in
 * p when t and v are fixed (every term inside the parens is
 * non-decreasing in p, and p multiplies the whole thing), so
 * bisection converges fast.  60 iterations bring the bracket
 * width to ~10⁻¹⁸ — way past floating-point precision.
 *
 * @param {number} target - target raw adjustment value
 * @param {number} t - max KTC value in the trade (drives the formula)
 * @param {number} [v=KTC_V_OVERALL_MAX]
 * @returns {number} player value X
 */
export function ktcSolveForAddedValue(target, t, v = KTC_V_OVERALL_MAX) {
  if (!(target > 0)) return 0;
  let lo = 0;
  let hi = Math.max(t || 0, KTC_V_OVERALL_MAX);
  if (ktcRawAdjustment(hi, t, v) < target) return hi;
  for (let i = 0; i < 60; i++) {
    const mid = (lo + hi) / 2;
    if (ktcRawAdjustment(mid, t, v) < target) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
}

// ── Pick Year Discount ──────────────────────────────────────────────────
// Future-year picks are worth less than current-year picks.
// Matches static: year+1 → 0.85, year+2 → 0.72, year+3+ → 0.60
const PICK_YEAR_DISCOUNTS = [1.0, 0.85, 0.72, 0.60];

/**
 * Pick year discount multiplier.
 * @param {string} pickName - Pick name (e.g. "2027 Early 1st")
 * @param {number} currentYear - Current draft year from settings
 * @returns {number} Multiplier (1.0 for current year, <1 for future)
 */
export function pickYearDiscount(pickName, currentYear) {
  const m = String(pickName || "").match(/^(20\d{2})/);
  if (!m) return 1.0;
  const pickYear = parseInt(m[1], 10);
  const delta = Math.max(0, pickYear - currentYear);
  return PICK_YEAR_DISCOUNTS[Math.min(delta, PICK_YEAR_DISCOUNTS.length - 1)];
}

/**
 * Get the effective value for a row, adjusted by pick year discount.
 *
 * NOTE: TE premium is NOT applied here.  ``settings.tepMultiplier``
 * is threaded through the backend rankings override pipeline (see
 * ``frontend/lib/dynasty-data.js::fetchDynastyData`` and
 * ``src/api/data_contract.py::_compute_unified_rankings``), which
 * bakes the boost into every TE row's ``rankDerivedValue`` stamp
 * before the contract reaches the trade calculator.  Multiplying
 * again on render would double-boost every TE whenever the TEP
 * slider is > 1.0, and would completely miss the TEP-native source
 * carve-out (dynastyNerdsSfTep).  The backend is now the single
 * source of truth for TEP — do NOT reintroduce the multiplication
 * here.
 *
 * @param {object} row - Player row
 * @param {string} valueMode - Value mode key
 * @param {object} [settings] - User settings (from useSettings)
 * @returns {number}
 */
export function effectiveValue(row, valueMode, settings) {
  const raw = Number(row.values?.[valueMode] || 0);
  if (!settings || raw <= 0) return raw;
  const pos = row.pos || "WR";
  let val = raw;

  // Pick year discount for future picks
  if (pos === "PICK" && settings.pickCurrentYear) {
    val *= pickYearDiscount(row.name, settings.pickCurrentYear);
  }

  return val;
}

/** Simple linear total (sum of values). */
export function sideTotal(side, valueMode, settings = null) {
  return side.reduce((sum, r) => sum + effectiveValue(r, valueMode, settings), 0);
}

/** Descending-sorted effective values for a side. */
function sortedSideValues(side, valueMode, settings) {
  return side
    .map((r) => Math.max(0, effectiveValue(r, valueMode, settings)))
    .sort((a, b) => b - a);
}

/**
 * Core V2 VA formula on pre-sorted value arrays.
 *
 * ``small`` and ``large`` must be sorted descending.  ``small`` is the
 * side receiving the VA; ``large`` is the side with more pieces.
 * Returns the scalar VA (always ≥ 0).  Caller is responsible for
 * clamping when small.length ≥ large.length — this function assumes
 * ``large`` is strictly longer than ``small``.
 *
 * Factored out so both the 2-side ``computeValueAdjustment`` path and
 * the N-side ``computeMultiSideAdjustments`` path share exactly the
 * same math — no divergence between how a 2-team trade is graded vs
 * how the same shape is graded inside a 3-team trade.
 */
// V13 suppression thresholds — calibrated 2026-04 against 39 captured
// borderline KTC trades (raw gaps 0-2500 across 9 topologies).
//
// Grid-searched on the full 139-trade fixture
// (scripts/ktc_va_observations.json):
//
//                                RMS   on-orig-100   on-39-BORD
//   V12 (no suppression)        91%      39%          160%
//   V13 (these thresholds)      41%      42%           41%
//
// The 3pt regression on the original 100 captures is the cost of
// catching the 11 false-fire cases on the borderline set + the
// user-reported "fair trade" where V12 over-predicted +1028.
const V13_SUPPRESS_RAW_DIFF = 100;
const V13_SUPPRESS_SAME_SIDE_RAW_DIFF = 400;

function _vaFromSortedSides(small, large) {
  if (small.length === 0 || small[0] <= 0) return 0;
  if (large.length === 0) return 0;

  // V12 + V13: KTC's published formula plus empirical suppression rules.
  //
  // KTC observation 1: 1v1 trades never display a VA, even when the
  // formula would produce one.  KTC's UI gates the row off.
  if (small.length === 1 && large.length === 1) return 0;

  const all = small.concat(large);
  const t = Math.max(...all);
  const v = KTC_V_OVERALL_MAX;

  let rawSmall = 0;
  for (const x of small) rawSmall += ktcRawAdjustment(x, t, v);
  let rawLarge = 0;
  for (const x of large) rawLarge += ktcRawAdjustment(x, t, v);

  // KTC convention: VA displayed on the bigger raw_sum side.  Our
  // caller convention is that ``small`` is the recipient — so we only
  // return a non-zero VA when small actually has the bigger raw_sum.
  const rawDiff = rawSmall - rawLarge;
  if (rawDiff <= 0) return 0;

  // V13 suppression rule 1 — "trade is too close to fire".  When
  // raw_diff is small in absolute terms, KTC's UI shows "Fair Trade"
  // and suppresses the VA row.  Threshold tuned from 4 captured cases
  // where V12 over-predicted by 200-1100 but KTC reported 0.
  if (rawDiff < V13_SUPPRESS_RAW_DIFF) return 0;

  // V13 suppression rule 2 — KTC article hint: "The value adjustment
  // isn't necessarily applied to the side with the best player; it
  // tends to be applied to the side with less junk."  When the
  // single best AND single worst piece in the trade are on the same
  // side AND the raw gap is moderate, KTC tends to suppress.  This
  // is the rule that caught the user-reported "fair trade" where
  // Justin Jefferson (best) and Germie Bernard (worst) were both on
  // the same side and KTC showed VA=0 despite V12 computing 1028.
  const allMin = Math.min(...all);
  const bestInSmall = small.includes(t);
  const worstInSmall = small.includes(allMin);
  if (
    bestInSmall === worstInSmall &&
    rawDiff < V13_SUPPRESS_SAME_SIDE_RAW_DIFF
  ) {
    return 0;
  }

  const sumSmall = small.reduce((s, x) => s + x, 0);
  const sumLarge = large.reduce((s, x) => s + x, 0);

  // Solve for the virtual player value that closes the raw gap on the
  // large side, then displayed VA = (large_total + virtual) -
  // small_total — which is the "show this much extra to make the
  // sides equal" quantity KTC's UI displays.
  const virtual = ktcSolveForAddedValue(rawDiff, t, v);
  const va = (sumLarge + virtual) - sumSmall;
  return Math.max(0, va);
}

/**
 * Compute the KTC-style Value Adjustment between two sides.
 *
 * Uses V12 — KTC's actual published formula.  The side with the
 * bigger raw_adjustment_sum receives the displayed VA bonus.  KTC's
 * algorithm is symmetric: equal-count trades (e.g. 2v2 stud-vs-pile)
 * fire VA when one side has bigger studs, and unequal-count trades
 * (the canonical 1v2/1v3) fire VA on the consolidator side.  The
 * one empirical exception is 1v1 trades, where KTC suppresses VA.
 *
 * Returns { adjustment, recipientIdx } where:
 *   - adjustment: ≥ 0 bonus to apply to the receiving side's total
 *   - recipientIdx: 0 for sideA, 1 for sideB, or null when neither
 *     side merits the boost (raw sums equal, or 1v1, or empty input)
 *
 * @param {object[]} sideA
 * @param {object[]} sideB
 * @param {string} valueMode
 * @param {object} [settings]
 */
export function computeValueAdjustment(sideA, sideB, valueMode, settings = null) {
  const aValues = sortedSideValues(sideA, valueMode, settings);
  const bValues = sortedSideValues(sideB, valueMode, settings);

  if (aValues.length === 0 || bValues.length === 0) {
    return { adjustment: 0, recipientIdx: null };
  }
  // KTC empirical: 1v1 trades never display a VA.
  if (aValues.length === 1 && bValues.length === 1) {
    return { adjustment: 0, recipientIdx: null };
  }

  // Compute raw sums to determine which side gets the VA.  Whichever
  // side has the bigger raw_sum is the recipient (KTC convention).
  const all = aValues.concat(bValues);
  if (all.length === 0 || all[0] <= 0) {
    return { adjustment: 0, recipientIdx: null };
  }
  const t = Math.max(...all);
  const v = KTC_V_OVERALL_MAX;
  const rawA = aValues.reduce((s, x) => s + ktcRawAdjustment(x, t, v), 0);
  const rawB = bValues.reduce((s, x) => s + ktcRawAdjustment(x, t, v), 0);

  if (Math.abs(rawA - rawB) < 1e-9) {
    return { adjustment: 0, recipientIdx: null };
  }
  const recipientIdx = rawA > rawB ? 0 : 1;
  const small = recipientIdx === 0 ? aValues : bValues;
  const large = recipientIdx === 0 ? bValues : aValues;
  const adjustment = _vaFromSortedSides(small, large);
  return { adjustment, recipientIdx };
}

/**
 * Compute per-side Value Adjustments for a multi-team trade (N ≥ 2).
 *
 * Each side's VA is computed as if that side is the "small" side in a
 * 2-side trade, and the merged opposition is the flattened union of
 * every OTHER side's received assets.  This generalization reduces to
 * the 2-side ``computeValueAdjustment`` behavior when N = 2, and lets
 * every side that consolidated relative to what they gave up earn an
 * independent premium in 3+-team deals.
 *
 * Returns an array of numeric adjustments — one per side, in the same
 * order as the input.  A side's adjustment is ≥ 0; sides without a
 * piece-count advantage over the rest of the trade receive 0.
 *
 * Caveat: the V2 coefficients were calibrated against 2-side KTC
 * observations.  Multi-side output is a structural extension of that
 * calibration, NOT a separately fit formula.  If KTC's real multi-team
 * VA diverges from this, we'll know when we have multi-team KTC data.
 *
 * @param {object[][]} sides  — array of asset arrays, one per side
 * @param {string} valueMode
 * @param {object} [settings]
 * @returns {number[]}
 */
export function computeMultiSideAdjustments(sides, valueMode, settings = null) {
  if (!Array.isArray(sides) || sides.length < 2) {
    return (sides || []).map(() => 0);
  }
  const allValues = sides.map((side) =>
    sortedSideValues(side, valueMode, settings),
  );
  return allValues.map((small, i) => {
    const large = [];
    for (let j = 0; j < allValues.length; j++) {
      if (j !== i) large.push(...allValues[j]);
    }
    large.sort((a, b) => b - a);
    return _vaFromSortedSides(small, large);
  });
}

/**
 * Per-source VA helper: computes Value Adjustment given raw numeric
 * value arrays (one per side) rather than player rows.
 *
 * Use this for the per-source trade breakdown, where each source
 * provides its own per-player values and the blended ``effectiveValue``
 * path doesn't apply.  Arrays may contain zeroes (players the source
 * doesn't rank); those are dropped before the VA math so a missing
 * source value doesn't erase an otherwise-present piece-count premium.
 *
 * Returns an array of adjustments matching the input order.  Exactly
 * one element is populated for a 2-side trade; for N ≥ 3 each side
 * that consolidated relative to the rest earns its own adjustment
 * (mirrors ``computeMultiSideAdjustments``).
 *
 * @param {number[][]} sidesValues  — array of raw-value arrays, one per side
 * @returns {number[]}
 */
export function valueAdjustmentFromSideArrays(sidesValues) {
  if (!Array.isArray(sidesValues) || sidesValues.length < 2) {
    return (sidesValues || []).map(() => 0);
  }
  const sorted = sidesValues.map((raw) =>
    (Array.isArray(raw) ? raw : [])
      .map((v) => Number(v) || 0)
      .filter((v) => v > 0)
      .sort((a, b) => b - a),
  );
  return sorted.map((small, i) => {
    const large = [];
    for (let j = 0; j < sorted.length; j++) {
      if (j !== i) large.push(...sorted[j]);
    }
    large.sort((a, b) => b - a);
    return _vaFromSortedSides(small, large);
  });
}

/**
 * Adjusted per-side totals for 2-team trade display.
 * Each entry is { raw, adjustment, adjusted } where `adjusted = raw + adjustment`
 * and only the recipient side has a non-zero adjustment.
 */
export function adjustedSideTotals(sideA, sideB, valueMode, settings = null) {
  const rawA = sideTotal(sideA, valueMode, settings);
  const rawB = sideTotal(sideB, valueMode, settings);
  const { adjustment, recipientIdx } = computeValueAdjustment(sideA, sideB, valueMode, settings);
  const adjA = recipientIdx === 0 ? adjustment : 0;
  const adjB = recipientIdx === 1 ? adjustment : 0;
  return [
    { raw: rawA, adjustment: adjA, adjusted: rawA + adjA },
    { raw: rawB, adjustment: adjB, adjusted: rawB + adjB },
  ];
}

/**
 * Adjusted per-side totals for N-team trade display (N ≥ 2).
 *
 * Each entry is { raw, adjustment, adjusted }.  For N = 2 this matches
 * ``adjustedSideTotals`` exactly.  For N ≥ 3 each side can earn its
 * own consolidation premium — see ``computeMultiSideAdjustments``.
 *
 * @param {object[][]} sides  — array of asset arrays
 * @param {string} valueMode
 * @param {object} [settings]
 */
export function multiAdjustedSideTotals(sides, valueMode, settings = null) {
  const adjustments = computeMultiSideAdjustments(sides, valueMode, settings);
  return sides.map((side, i) => {
    const raw = sideTotal(side, valueMode, settings);
    const adjustment = adjustments[i] || 0;
    return { raw, adjustment, adjusted: raw + adjustment };
  });
}

/** Gap = Side A adjusted total − Side B adjusted total (KTC-style). */
export function tradeGapAdjusted(sideA, sideB, valueMode, settings = null) {
  const totals = adjustedSideTotals(sideA, sideB, valueMode, settings);
  return totals[0].adjusted - totals[1].adjusted;
}

// ── Verdict ──────────────────────────────────────────────────────────────
export function verdictFromGap(gap) {
  const abs = Math.abs(gap);
  if (abs < VERDICT_NEAR_EVEN) return "Near even";
  if (abs < VERDICT_LEAN) return "Lean";
  if (abs < VERDICT_STRONG_LEAN) return "Strong lean";
  return "Major gap";
}

export function colorFromGap(gap) {
  if (Math.abs(gap) < VERDICT_NEAR_EVEN) return "";
  return gap > 0 ? "green" : "red";
}

/**
 * Verdict bar position (0 = Side B wins, 50 = even, 100 = Side A wins).
 * Clamped so the marker never fully touches either edge.
 */
export function verdictBarPosition(gap, maxGap = 4000) {
  const clamped = Math.max(-maxGap, Math.min(maxGap, gap));
  return 50 + (clamped / maxGap) * 50;
}

// ── Edge Detection ───────────────────────────────────────────────────────
//
// We trust the backend's rank-based ``marketGapDirection`` +
// ``marketGapMagnitude`` (see ``_compute_market_gap`` in
// ``src/api/data_contract.py``) as the source of truth:
//
//   * ``retail_premium``     — retail (KTC) mean rank is LOWER (better)
//                              than the expert consensus → market
//                              OVERVALUES the player vs consensus →
//                              ``SELL HIGH`` to a retail-anchored
//                              trade partner.
//   * ``consensus_premium``  — consensus mean rank is LOWER (better)
//                              than retail → market UNDERVALUES the
//                              player → ``BUY LOW`` from a retail-
//                              anchored partner.
//
// Why rank not value:
//   The Hill curve is flat at the top and steep in the middle.  Three
//   ranks of disagreement at #8 vs #11 reads as ~18% value gap; three
//   ranks at #80 reads as ~4%.  A rank-based signal is stable across
//   the board and matches the trade intuition ("who's ranked higher
//   by whom").  The prior value-based implementation over-fired at
//   elite QB/RB tiers and under-fired in the mid-rounds.
//
//   The prior implementation also had the sign backwards — ``ourValue
//   > KTC`` was labelled SELL, but a blend higher than retail means
//   the MARKET is cheap, which is BUY.  See PR for the walkthrough.
//
// Magnitude threshold (in ranks):
//   3 ranks is the floor.  Below that we treat it as noise — the mean-
//   of-means comparison can flicker by a rank from scrape to scrape.
//   Anything 3+ is a real, actionable disagreement.
const MIN_EDGE_RANK_GAP = 3;

/**
 * Compute the retail-vs-consensus edge signal for a player row.
 *
 * Reads the backend-stamped ``marketGapDirection`` /
 * ``marketGapMagnitude`` directly — no client-side recompute from
 * per-source values.
 *
 * @param {object} row - Player row with marketGapDirection + marketGapMagnitude
 * @returns {{ signal: 'BUY'|'SELL'|null, edgePct: number, rankGap: number, sources: string[] }}
 */
export function getPlayerEdge(row) {
  if (!row) return { signal: null, edgePct: 0, rankGap: 0, sources: [] };

  const direction = String(row.marketGapDirection || "none");
  const magnitude = Number(row.marketGapMagnitude);
  // ``marketGapMagnitude`` is the absolute rank gap between retail
  // mean and consensus mean — float because both sides are mean-of-N.
  if (!Number.isFinite(magnitude) || magnitude < MIN_EDGE_RANK_GAP) {
    return { signal: null, edgePct: 0, rankGap: 0, sources: ["ktc"] };
  }
  if (direction !== "retail_premium" && direction !== "consensus_premium") {
    return { signal: null, edgePct: 0, rankGap: 0, sources: ["ktc"] };
  }

  // Translate the rank gap into a rough value-% for display continuity
  // with the old UI.  We compare the row's live value against its KTC
  // canonical-site value when available, else derive from the rank
  // gap.  The SIGNAL itself is rank-driven — this % is purely a
  // human-readable "how different is the price".
  let edgePct = 0;
  const ourValue = Number(row?.values?.full);
  const ktcValue = Number(row?.canonicalSites?.ktc);
  if (Number.isFinite(ourValue) && ourValue > 0 && Number.isFinite(ktcValue) && ktcValue > 0) {
    edgePct = Math.round(Math.abs(((ourValue - ktcValue) / ktcValue) * 100));
  } else {
    // Fallback: magnitude-in-ranks is the best we have.  Render as
    // "3-rank gap" style.  The popup handles the suffix via the
    // ``rankGap`` field.
    edgePct = Math.round(magnitude);
  }

  return {
    // consensus_premium → BUY LOW (market undervalues the player)
    // retail_premium    → SELL HIGH (market overvalues the player)
    signal: direction === "consensus_premium" ? "BUY" : "SELL",
    edgePct,
    rankGap: Math.round(magnitude),
    sources: ["ktc"],
  };
}

// ── Pick Token Parsing ───────────────────────────────────────────────────
const ROUND_LABELS = { "1": "1st", "2": "2nd", "3": "3rd", "4": "4th", "5": "5th", "6": "6th" };

/**
 * Parse a pick token string into structured parts.
 * Handles: "2026 1.06", "2026 early 1st", "2026 1st", "2026 mid 2nd"
 * @returns {{ year: string, round: string, tier: string|null, slot: number|null }}
 */
export function parsePickToken(token) {
  const s = String(token || "").trim();

  // "2026 1.06" format
  const slotMatch = s.match(/^(\d{4})\s+(\d)\.(\d{2})/);
  if (slotMatch) {
    const round = ROUND_LABELS[slotMatch[2]] || `${slotMatch[2]}th`;
    const slot = parseInt(slotMatch[3], 10);
    const tier = slot <= 4 ? "early" : slot <= 8 ? "mid" : "late";
    return { year: slotMatch[1], round, tier, slot };
  }

  // "2026 early 1st" or "2026 1st" format
  const labelMatch = s.match(/^(\d{4})\s+(early|mid|late)?\s*(1st|2nd|3rd|4th|5th|6th)/i);
  if (labelMatch) {
    return { year: labelMatch[1], round: labelMatch[3].toLowerCase(), tier: (labelMatch[2] || "").toLowerCase() || null, slot: null };
  }

  return null;
}

/**
 * Normalize a pick token to canonical lookup label.
 * "2026 1.06" → "2026 Mid 1st", "2026 early 2nd" → "2026 Early 2nd"
 */
export function normalizePickLabel(token) {
  const parsed = parsePickToken(token);
  if (!parsed) return token;
  const tier = parsed.tier ? parsed.tier.charAt(0).toUpperCase() + parsed.tier.slice(1) : "Mid";
  return `${parsed.year} ${tier} ${parsed.round}`;
}

// Tier-centre slot used to translate tier labels to slot-specific rows.
// Matches backend _suppress_generic_pick_tiers_when_slots_exist() in
// src/api/data_contract.py: Early=2, Mid=6, Late=10.
const TIER_CENTRE_SLOT = { early: 2, mid: 6, late: 10 };

// Round numeric digit ("1") for the round label ("1st").  Kept here so
// both slot-based and tier-based candidates can be generated without
// re-deriving the mapping at every call site.  Mirrors the backend
// draft_rounds range in Dynasty Scraper.py (1..6).
const ROUND_NUM = { "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6 };

/**
 * Given a raw pick label from any source (Sleeper roster, Sleeper trade
 * history, rankings row), return a de-duplicated, lowercased list of
 * candidate canonical row names to probe against `rowLookup`.
 *
 * Sleeper labels arrive as "2026 1.04 (from Team X)" or "2027 Mid 1st
 * (own)" — the rankings pipeline stores the same asset as
 * "2026 Pick 1.04" or "2027 Mid 1st".  Without candidate expansion the
 * slot-based Sleeper label misses the rankings row and the pick is
 * valued at 0 in trade history + roster breakdown (while the rankings
 * page shows the correct value).
 *
 * Returns lowercased strings so callers can match rowLookup (which
 * uses `r.name.toLowerCase()` as the key).
 */
export function buildPickLookupCandidates(rawLabel) {
  if (!rawLabel) return [];
  const raw = String(rawLabel).trim();
  const candidates = [];
  const push = (v) => {
    if (!v) return;
    const key = String(v).trim().toLowerCase();
    if (key && !candidates.includes(key)) candidates.push(key);
  };

  // 1) Raw label exactly as provided.
  push(raw);

  // 2) Strip trailing "(...)" annotation like "(from Team X)" or "(own)".
  const stripped = raw.replace(/\s*\([^)]*\)\s*$/, "").trim();
  if (stripped && stripped !== raw) push(stripped);

  // 3) Parse into {year, round, tier, slot} and enumerate every
  //    canonical form the rankings pipeline might have used.
  const parsed = parsePickToken(stripped || raw);
  if (parsed) {
    const { year, round, tier, slot } = parsed;
    const roundDigit = ROUND_NUM[round];

    if (slot && roundDigit) {
      // "2026 Pick 1.04" (rankings canonical, slot-specific)
      push(`${year} Pick ${roundDigit}.${String(slot).padStart(2, "0")}`);
      // "2026 1.04" (already pushed as stripped, but guaranteed here)
      push(`${year} ${roundDigit}.${String(slot).padStart(2, "0")}`);
    }

    if (tier) {
      const cap = tier.charAt(0).toUpperCase() + tier.slice(1);
      // "2027 Early 1st" (tier canonical — used for future years)
      push(`${year} ${cap} ${round}`);
      // If we only know the tier, generate the tier-centre slot form
      // so years that DO have slot-specific rows still resolve.
      if (roundDigit) {
        const centreSlot = TIER_CENTRE_SLOT[tier] || 6;
        push(`${year} Pick ${roundDigit}.${String(centreSlot).padStart(2, "0")}`);
        push(`${year} ${roundDigit}.${String(centreSlot).padStart(2, "0")}`);
      }
    }

    // 4) If we have a slot but no tier — derive the tier from the slot
    //    (early 1-4, mid 5-8, late 9-12) and push tier-based candidates.
    if (slot && !tier && roundDigit) {
      const derivedTier = slot <= 4 ? "Early" : slot <= 8 ? "Mid" : "Late";
      push(`${year} ${derivedTier} ${round}`);
    }
  }

  return candidates;
}

/**
 * True if a row is a suppressed generic-tier pick — one that the backend
 * kept on the legacy board for name-search purposes but cleared of
 * ranking fields because a slot-specific sibling exists (e.g. "2026 Mid
 * 1st" when "2026 Pick 1.06" is the authoritative row).  These rows
 * can still carry stale values from the legacy pipeline, so callers
 * must treat them as non-authoritative and consult `pickAliases` or
 * slot-specific candidates instead.
 */
function isSuppressedGenericPickRow(row) {
  if (!row) return false;
  return Boolean(row.pickGenericSuppressed || row.raw?.pickGenericSuppressed);
}

/**
 * Resolve a pick label (raw or annotated) to a row using rowLookup and
 * optional backend-authored pickAliases map.  Returns null if no
 * candidate resolves.  Callers should NOT fall back to an untyped 0 —
 * a null return means the pick genuinely has no known value.
 *
 * Resolution order is deliberate:
 *   1. `pickAliases` lookup against the **input** label (raw or stripped
 *      of its "(from X)" / "(own)" annotation).  The alias table only
 *      contains entries for generic tier labels whose slot-specific
 *      siblings exist on the board (e.g. "2026 Mid 1st" →
 *      "2026 Pick 1.06").  Applying aliases to the input — not to the
 *      synthesized derived candidates — prevents a slot input like
 *      "2026 1.04" from being rewritten to the tier-centre slot via
 *      its derived "2026 Early 1st" candidate.
 *   2. Direct `rowLookup` walk over candidate names, skipping any
 *      suppressed generic-tier row so the fallback chain continues to a
 *      valid slot-specific sibling.  This keeps the resolver robust
 *      even when `pickAliases` is missing (stale data, older contract).
 *
 * @param {string} rawLabel - raw pick label (any source)
 * @param {Map<string, object>} rowLookup - lowercased name → row
 * @param {object} [pickAliases] - optional backend alias map
 *   ({ "2026 Mid 1st": "2026 Pick 1.06", ... })
 */
export function resolvePickRow(rawLabel, rowLookup, pickAliases) {
  if (!rawLabel || !rowLookup) return null;

  const raw = String(rawLabel).trim();
  const stripped = raw.replace(/\s*\([^)]*\)\s*$/, "").trim();

  // 1) Backend alias map — only applied to the input label (raw or
  //    stripped), never to synthesized derived candidates.  This is
  //    the critical distinction: the alias table redirects generic
  //    tier labels to slot-specific canonical rows, so applying it to
  //    derived tier candidates (e.g. the "2026 Early 1st" that
  //    buildPickLookupCandidates synthesizes for a "2026 1.04" input)
  //    would systematically misroute slot picks to the tier-centre
  //    slot.  Only trust the alias map for labels the caller actually
  //    provided.
  if (pickAliases && typeof pickAliases === "object") {
    const inputForms = new Set();
    inputForms.add(raw.toLowerCase());
    if (stripped) inputForms.add(stripped.toLowerCase());
    for (const [k, v] of Object.entries(pickAliases)) {
      if (typeof k !== "string" || typeof v !== "string") continue;
      if (!inputForms.has(k.toLowerCase())) continue;
      const row = rowLookup.get(v.toLowerCase());
      if (row && !isSuppressedGenericPickRow(row)) return row;
      // Alias target matched but row is absent or suppressed — fall
      // through to direct lookup; don't keep iterating the alias map.
      break;
    }
  }

  // 2) Direct candidate lookup.  Skip suppressed generic-tier rows so a
  //    later candidate (typically the slot-specific "Pick N.NN" form)
  //    gets a chance to resolve even without a pickAliases map.
  const candidates = buildPickLookupCandidates(raw);
  for (const key of candidates) {
    const row = rowLookup.get(key);
    if (!row) continue;
    if (isSuppressedGenericPickRow(row)) continue;
    return row;
  }

  return null;
}

// ── Trade Side Helpers ───────────────────────────────────────────────────
export function addAssetToSide(side, row) {
  if (!row) return side;
  if (side.some((r) => r.name === row.name)) return side;
  return [...side, row];
}

export function removeAssetFromSide(side, name) {
  return side.filter((r) => r.name !== name);
}

export function isAssetInTrade(sideA, sideB, name) {
  return sideA.some((r) => r.name === name) || sideB.some((r) => r.name === name);
}

// ── Balancing Suggestions ────────────────────────────────────────────────
/**
 * Find players from a roster that could balance a trade gap.
 * @param {number} gap - Current trade gap (positive = Side A ahead)
 * @param {object[]} rosterRows - Available rows from the behind team's roster
 * @param {string} valueMode - Current value mode
 * @param {number} maxResults - Max suggestions to return
 * @returns {object[]} Sorted array of { name, pos, value } that best fill the gap
 */
export function findBalancers(gap, rosterRows, valueMode, maxResults = 5) {
  const target = Math.abs(gap);
  if (target < VERDICT_NEAR_EVEN) return [];

  return rosterRows
    .map((r) => ({ name: r.name, pos: r.pos, value: Number(r.values?.[valueMode] || 0) }))
    .filter((r) => r.value > 0 && r.value <= target * 1.3)
    .sort((a, b) => Math.abs(a.value - target) - Math.abs(b.value - target))
    .slice(0, maxResults);
}

// ── Multi-Team Verdict Helpers ───────────────────────────────────────────

/** Side labels: A through E */
export const SIDE_LABELS = ["A", "B", "C", "D", "E"];
export const MAX_SIDES = 5;
export const MIN_SIDES = 2;

/**
 * Create a fresh empty side.
 *
 * ``destinations`` is a name → destination-side-index map that only
 * applies in 3+-team trades.  In a 2-team trade every asset implicitly
 * goes to the other side, so the map is ignored.  In N ≥ 3 trades the
 * user picks explicitly which side each asset is going to; ``addToSide``
 * seeds a default via ``defaultDestination`` and ``computeSideFlows``
 * uses the map to compute per-side given/received/net.
 *
 * @param {number} index - 0-based index
 * @returns {{ id: number, label: string, assets: [], destinations: {} }}
 */
export function createSide(index) {
  return {
    id: index,
    label: SIDE_LABELS[index] || String.fromCharCode(65 + index),
    assets: [],
    destinations: {},
  };
}

/**
 * Default destination for an asset on a side in a multi-team trade.
 * Picks the next side (circular), which matches "A gives to B, B gives
 * to C, C gives to A" as the first-guess flow.
 */
export function defaultDestination(sideIdx, sideCount) {
  if (sideCount < 2) return 0;
  if (sideIdx < 0 || sideIdx >= sideCount) return 0;
  return (sideIdx + 1) % sideCount;
}

/**
 * Compute, for each side, the lists of incoming / outgoing asset
 * references with their counterparty side index.  This is the
 * "who's getting what" view of a multi-team trade — the companion
 * to ``computeSideFlows`` which only returns totals.
 *
 * Returns an array of ``{ outgoing, incoming }`` per side.  Each
 * entry in ``outgoing`` is ``{ asset, toSideIdx }`` and each entry
 * in ``incoming`` is ``{ asset, fromSideIdx }``.
 *
 * In 2-team trades the mapping is implicit (every asset flows to
 * the other side).  In 3+-team trades the destinations map drives
 * routing, with the same default-destination fallback used in
 * ``computeSideFlows``.
 *
 * @param {object[]} sides
 * @returns {{outgoing: {asset: object, toSideIdx: number}[], incoming: {asset: object, fromSideIdx: number}[]}[]}
 */
export function computeSideFlowAssets(sides) {
  const n = Array.isArray(sides) ? sides.length : 0;
  const result = [];
  for (let i = 0; i < n; i++) result.push({ outgoing: [], incoming: [] });
  if (n < 2) return result;

  for (let i = 0; i < n; i++) {
    const side = sides[i];
    const assets = Array.isArray(side?.assets) ? side.assets : [];
    const destinations = side?.destinations || {};
    for (const asset of assets) {
      let dest;
      if (n === 2) {
        dest = 1 - i;
      } else {
        const raw = destinations[asset.name];
        const parsed = Number(raw);
        if (
          Number.isInteger(parsed) &&
          parsed >= 0 &&
          parsed < n &&
          parsed !== i
        ) {
          dest = parsed;
        } else {
          dest = defaultDestination(i, n);
        }
      }
      result[i].outgoing.push({ asset, toSideIdx: dest });
      result[dest].incoming.push({ asset, fromSideIdx: i });
    }
  }
  return result;
}

/**
 * Compute per-side flow for a multi-team trade with explicit destinations.
 *
 * Returns an array of ``{ given, received, net }`` per side in the same
 * order as ``sides``.  ``net = received − given``, so a side with a
 * positive net is gaining value and a negative net is losing value.
 *
 * In 2-team trades (sides.length === 2), destinations are implicit:
 * every asset goes to the OTHER side, regardless of the destinations
 * map.  In 3+-team trades, each asset's destination is read from
 * ``side.destinations[assetName]`` (0-based index).  If the map is
 * missing a destination, or it points at itself / out of range, the
 * default destination (next side circular) is used so stale or
 * partially-configured state still produces sensible flows.
 *
 * @param {object[]} sides  - array of side objects
 * @param {string} valueMode
 * @param {object} [settings]
 * @returns {{given: number, received: number, net: number}[]}
 */
export function computeSideFlows(sides, valueMode, settings = null) {
  const n = Array.isArray(sides) ? sides.length : 0;
  const result = [];
  for (let i = 0; i < n; i++) result.push({ given: 0, received: 0, net: 0 });
  if (n < 2) return result;

  for (let i = 0; i < n; i++) {
    const side = sides[i];
    const assets = Array.isArray(side?.assets) ? side.assets : [];
    const destinations = side?.destinations || {};
    for (const asset of assets) {
      const value = Math.max(0, effectiveValue(asset, valueMode, settings));
      result[i].given += value;

      let dest;
      if (n === 2) {
        dest = 1 - i; // implicit: the other side
      } else {
        const raw = destinations[asset.name];
        const parsed = Number(raw);
        if (
          Number.isInteger(parsed) &&
          parsed >= 0 &&
          parsed < n &&
          parsed !== i
        ) {
          dest = parsed;
        } else {
          dest = defaultDestination(i, n);
        }
      }
      result[dest].received += value;
    }
  }
  for (let i = 0; i < n; i++) {
    result[i].net = result[i].received - result[i].given;
  }
  return result;
}

/**
 * Compute the granular trade-meter verdict label from an absolute gap.
 * More categories than verdictFromGap for the inline meter badge.
 * @param {number} absGap - Absolute point gap
 * @returns {{ label: string, level: 'fair'|'slight'|'unfair'|'lopsided' }}
 */
export function meterVerdict(absGap) {
  if (absGap < 350) return { label: "FAIR", level: "fair" };
  if (absGap < 900) return { label: "SLIGHT EDGE", level: "slight" };
  if (absGap < 1800) return { label: "UNFAIR", level: "unfair" };
  return { label: "LOPSIDED", level: "lopsided" };
}

/**
 * Percentage gap for proportional display.
 * Returns 0 when both sides are empty.
 * @param {number} valA - Side A total
 * @param {number} valB - Side B total
 * @returns {number} Integer percentage 0-100
 */
export function percentageGap(valA, valB) {
  const maxVal = Math.max(valA, valB);
  if (maxVal <= 0) return 0;
  return Math.round(Math.abs(valA - valB) / maxVal * 100);
}

/**
 * For multi-team (3+), compute each side's share percentage and
 * per-team verdict (over/under contributing).
 * @param {number[]} totals - Array of side totals
 * @returns {{ shares: number[], overall: string, perTeam: string[] }}
 */
export function multiTeamAnalysis(totals) {
  const grandTotal = totals.reduce((a, b) => a + b, 0);
  if (grandTotal <= 0) {
    return {
      shares: totals.map(() => 0),
      overall: "Empty",
      perTeam: totals.map(() => "No assets"),
    };
  }
  const count = totals.length;
  const equalShare = 100 / count;
  const shares = totals.map((t) => Math.round((t / grandTotal) * 100));
  const perTeam = shares.map((s, i) => {
    const diff = s - equalShare;
    if (Math.abs(diff) < 5) return "Fair share";
    if (diff > 0) return "Overpaying";
    return "Getting a deal";
  });
  const maxDiff = Math.max(...shares.map((s) => Math.abs(s - equalShare)));
  const overall = maxDiff < 10 ? "Balanced" : "Imbalanced";
  return { shares, overall, perTeam };
}

// ── Workspace Serialization ──────────────────────────────────────────────
export function serializeWorkspace(sideA, sideB, valueMode, activeSide) {
  return {
    valueMode,
    activeSide,
    sideA: sideA.map((r) => r.name),
    sideB: sideB.map((r) => r.name),
  };
}

/**
 * Serialize multi-team workspace (sides array format).
 *
 * Destinations are persisted alongside asset names so a 3+-team trade
 * reloads with the same per-asset routing the user picked.  Only entries
 * whose asset is still on the side are persisted — stale keys for
 * removed assets are dropped here rather than carried through storage.
 */
export function serializeWorkspaceMulti(sides, valueMode, activeSide) {
  return {
    version: 2,
    valueMode,
    activeSide,
    sides: sides.map((s) => {
      const assetNames = s.assets.map((r) => r.name);
      const destSource = s.destinations || {};
      const destinations = {};
      for (const name of assetNames) {
        if (Object.prototype.hasOwnProperty.call(destSource, name)) {
          destinations[name] = destSource[name];
        }
      }
      return { label: s.label, assets: assetNames, destinations };
    }),
  };
}

export function deserializeWorkspace(parsed, rowByName) {
  if (!parsed || typeof parsed !== "object") return null;
  const valueMode = VALUE_MODES.some((m) => m.key === parsed.valueMode) ? parsed.valueMode : "full";
  const activeSide = parsed.activeSide === "B" ? "B" : "A";
  const sideA = Array.isArray(parsed.sideA) ? parsed.sideA.map((n) => rowByName.get(n)).filter(Boolean) : [];
  const sideB = Array.isArray(parsed.sideB) ? parsed.sideB.map((n) => rowByName.get(n)).filter(Boolean) : [];
  return { valueMode, activeSide, sideA, sideB };
}

/**
 * Deserialize multi-team workspace, with migration from old 2-side format.
 * @param {object} parsed - Raw localStorage object
 * @param {Map} rowByName - name -> row lookup
 * @returns {{ valueMode: string, activeSide: number, sides: object[] } | null}
 */
export function deserializeWorkspaceMulti(parsed, rowByName) {
  if (!parsed || typeof parsed !== "object") return null;
  const valueMode = VALUE_MODES.some((m) => m.key === parsed.valueMode) ? parsed.valueMode : "full";

  // Version 2 (new multi-team format)
  if (parsed.version === 2 && Array.isArray(parsed.sides)) {
    const activeSide = typeof parsed.activeSide === "number" ? parsed.activeSide : 0;
    const sideCount = parsed.sides.length;
    const sides = parsed.sides.map((s, i) => {
      const assets = Array.isArray(s.assets)
        ? s.assets.map((n) => rowByName.get(n)).filter(Boolean)
        : [];
      const destSource =
        s.destinations && typeof s.destinations === "object" ? s.destinations : {};
      const destinations = {};
      for (const asset of assets) {
        const raw = destSource[asset.name];
        const parsedIdx = Number(raw);
        if (
          Number.isInteger(parsedIdx) &&
          parsedIdx >= 0 &&
          parsedIdx < sideCount &&
          parsedIdx !== i
        ) {
          destinations[asset.name] = parsedIdx;
        }
      }
      return {
        id: i,
        label: s.label || SIDE_LABELS[i] || String.fromCharCode(65 + i),
        assets,
        destinations,
      };
    });
    // Ensure at least 2 sides
    while (sides.length < MIN_SIDES) sides.push(createSide(sides.length));
    return { valueMode, activeSide: Math.min(activeSide, sides.length - 1), sides };
  }

  // Legacy format (sideA/sideB arrays) — migrate
  const activeSide = parsed.activeSide === "B" ? 1 : 0;
  const sideA = Array.isArray(parsed.sideA) ? parsed.sideA.map((n) => rowByName.get(n)).filter(Boolean) : [];
  const sideB = Array.isArray(parsed.sideB) ? parsed.sideB.map((n) => rowByName.get(n)).filter(Boolean) : [];
  return {
    valueMode,
    activeSide,
    sides: [
      { id: 0, label: "A", assets: sideA, destinations: {} },
      { id: 1, label: "B", assets: sideB, destinations: {} },
    ],
  };
}

export function addRecent(recentNames, name) {
  return [name, ...recentNames.filter((x) => x !== name)].slice(0, 20);
}

export function filterPickerRows(rows, sideA, sideB, query, filter) {
  const inTrade = new Set([...sideA, ...sideB].map((r) => r.name));
  const q = query.trim().toLowerCase();
  let list = rows.filter((r) => !inTrade.has(r.name));
  if (filter !== "all") list = list.filter((r) => r.assetClass === filter);
  if (q) list = list.filter((r) => r.name.toLowerCase().includes(q));
  return list.slice(0, 80);
}
