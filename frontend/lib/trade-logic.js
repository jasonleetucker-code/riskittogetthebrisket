/**
 * Trade calculator logic — the authoritative implementation for Next.js.
 * Covers: value modes, power-weighted totals, edge detection,
 * pick valuation, verdict calculation, persistence.
 *
 * No React dependencies — pure functions + constants.
 */

// Explicit .js extension: Next's webpack resolves extensionless
// relative imports, but vitest's node environment does not — the
// missing extension silently broke the entire trade-logic test suite
// (including the KTC-VA parity pins) until the 2026-07-25 audit (F-4).
import { effectiveAuctionPower } from "./auction-power.js";
import { MARKET_GAP_MIN_VALUE_RATIO } from "./thresholds.js";

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

// ── Value Adjustment: ONE owner, and it is ktcAdjustPackage ─────────────
//
// RETIRED 2026-08-18: the V2 scarcity constants (VA_SCARCITY_SLOPE,
// VA_SCARCITY_INTERCEPT, VA_SCARCITY_CAP, VA_PER_EXTRA_BOOST,
// VA_EFFECTIVE_CAP, VA_POSITION_DECAY), the V12 regression fit
// (`ktcRawAdjustment`, `ktcSolveForAddedValue`, `KTC_V_OVERALL_MAX`) and
// the V13 suppression rules (`_vaFromSortedSides`,
// V13_SUPPRESS_RAW_DIFF, V13_SUPPRESS_SAME_SIDE_RAW_DIFF).
//
// They were superseded on 2026-04-26 by the direct port of KTC's own
// algorithm below (`ktcProcessV` / `ktcReverseAdjust` /
// `ktcAdjustPackage`), and at that point every entry point was rewired.
// What was left behind was a complete second VA implementation —
// `_vaFromSortedSides` had **no caller anywhere in the app and no
// test**, and the V2 constants were imported by exactly one test file
// which never read them.
//
// Deleted rather than deprecated.  A whole second VA sitting exported
// beside the live one is what lets a future caller wire it in without
// anyone deciding to, and this repo has already paid for that once
// (W29-F001: a second canonical board on every row that three engines
// picked up).  The deprecation note that used to sit here promised
// removal after 2026-Q3; the reason to remove it is that it is dead,
// not that a date passed.
//
// `TRADE_ALPHA` above is NOT part of this and is still live — it grades
// past trades on /trades, where a consolidation premium cannot be
// attributed after the fact.

// ── Pick Year Discount: backend-owned ───────────────────────────────────
// The future-year pick discount is applied ONCE, in the backend
// canonical pipeline (src/api/data_contract.py::_pick_year_discount_for,
// keyed off the self-rolling current_rookie_draft_year()), and is
// already baked into every pick's ``rankDerivedValue``.  The frontend
// must NOT re-discount: a second client-side multiply was a double
// discount (backend 0.82 × old client 0.85, with divergent constants
// and a hard-coded, non-self-rolling year).  Removed — the backend is
// the single source of truth, same as TEP (see ``effectiveValue``).
// The resolved year is serialized as ``contract.currentDraftYear`` for
// display only.

/**
 * Get the effective value for a row.
 *
 * NEITHER the TE premium NOR the future-year pick discount is applied
 * here — both are baked into the backend ``rankDerivedValue`` (TEP via
 * the rankings override pipeline; the pick-year discount via
 * ``src/api/data_contract.py::_pick_year_discount_for`` off the
 * self-rolling ``current_rookie_draft_year()``).  ``row.values``
 * already carries those.  Re-applying either on render would
 * double-count — the backend is the single source of truth.  Do NOT
 * reintroduce a client-side multiply here.
 *
 * @param {object} row - Player row
 * @param {string} valueMode - Value mode key
 * @param {object} [_settings] - Accepted for call-site compatibility; unused.
 * @returns {number}
 */
export function effectiveValue(row, valueMode, _settings) {
  // Per-player trade override: the user's typed number is used verbatim.
  if (row.customValue != null && row.customValue > 0) return row.customValue;
  return Number(row.values?.[valueMode] || 0);
}

/** Simple linear total (sum of values). */
export function sideTotal(side, valueMode, settings = null) {
  return side.reduce((sum, r) => sum + effectiveValue(r, valueMode, settings), 0);
}

/**
 * Resolve the value to *display* for a player row.
 *
 * Use this anywhere a row's "Our Value" number is shown (picker cells,
 * sort comparators, headers).  Don't use ``effectiveValue`` directly for
 * display — that one is trade math, and it answers a different question.
 *
 * **Returns `null` when the board declined to price the row**, which is
 * not the same statement as zero and must not render as one.  282 of
 * 1,094 rows on the live board carry `rankDerivedValue: null`; a `0`
 * there reads as "we priced this asset and it is worth nothing", and it
 * sorts alongside genuinely worthless assets. `formatBoardValue` is the
 * companion that turns the null into an em dash.
 *
 * This used to return `0`, which was correct for the arithmetic it was
 * originally written beside and wrong the moment it reached a label.
 */
export function displayValue(row, _settings = null) {
  if (!row) return null;
  const fromValues = Number(row.values?.full);
  if (Number.isFinite(fromValues) && fromValues > 0) return fromValues;
  const fromRdv = Number(row.rankDerivedValue);
  return Number.isFinite(fromRdv) && fromRdv > 0 ? fromRdv : null;
}

/**
 * A board value as text, with the unpriced case spelled out.
 *
 * One formatter so "not priced" cannot render as "0" on one surface and
 * "—" on another.
 */
export function formatBoardValue(row, settings = null) {
  const value = displayValue(row, settings);
  return value == null ? "—" : Math.round(value).toLocaleString();
}

/**
 * The assets on a side the board declined to price.
 *
 * ``effectiveValue`` deliberately keeps returning 0 for these: inside
 * ``sideTotal`` that is a legitimate arithmetic neutral, and dropping
 * the row instead would silently shrink the piece count that Value
 * Adjustment is computed from.
 *
 * What is NOT legitimate is publishing the resulting gap and verdict
 * without saying which pieces contributed nothing because nobody priced
 * them. That is what this is for — the caller reports incompleteness
 * rather than the arithmetic hiding it.
 */
export function unpricedAssetsOnSide(side) {
  return (side || []).filter(
    (row) => row?.customValue == null && isUnpricedBoardRow(row),
  );
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
// ── KTC NATIVE ALGORITHM (ported from keeptradecut.com site.min.js) ────
//
// As of 2026-04-26 the V12/V13 regression-fit approximation below is
// superseded by a direct port of KTC's actual VA algorithm.  V13 had
// 41% RMS error against the captured fixture; the port reproduces
// keeptradecut.com's display value bit-for-bit.
//
// Source: keeptradecut.com/js/site.min.js, functions ``processV``,
// ``reverseAdjust``, ``adjustPackage``.  Constants ``MAXPLAYERVAL``
// (10000) and ``tcFilters.variance`` (5%) lifted from the same file.
//
// The port preserves variable names from KTC's source where it
// improves traceability against the original; comments mark the
// mapping from KTC's identifiers to readable names.

// KTC's MAXPLAYERVAL — board-wide ceiling used as the asymptotic
// reference in reverseAdjust's "all-equal" fallback branch.
const KTC_MAX_PLAYER_VAL = 10000;

// KTC's t = playersArray[0].value + 80 — top-of-board reference, used
// as the denominator in the (e/t)^1.3 term of processV.  We can't
// observe the live top value at compute time without bundling KTC's
// player payload, but it's stable around ~9961+80=10041 across the
// lifetime of any deployed build.  Sensitivity is low — the term is
// dampened by 0.05 multiplier and 1.3 exponent — so a static constant
// produces VAs within ~1% of using the live top value.
const KTC_T_REFERENCE = 10041;

// KTC's tcFilters.variance — the 5% equality threshold used by
// checkEquality() to gate "trade is fair on totals AND raw_adj"
// branches.  KTC's UI exposes this slider but defaults it to 5; we
// match the default.
const KTC_VARIANCE_PCT = 5;

/**
 * KTC's per-player raw adjustment, ported verbatim from
 * site.min.js::processV.  Replaces the V12 ``ktcRawAdjustment``.
 *
 * @param {number} value     — this player's KTC value
 * @param {number} maxInTrade — max value among players in THIS trade
 * @param {number} t          — top-of-board reference (KTC_T_REFERENCE)
 * @param {number} nerfIndex  — -1 to disable nerf, else 0,1,2,...
 *                              (each successive small piece on the same
 *                              side gets progressively discounted)
 */
export function ktcProcessV(value, maxInTrade, t, nerfIndex) {
  if (!(value > 0) || !(maxInTrade > 0) || !(t > 0)) return 0;
  let s = (
    0.05 * Math.pow(value / t, 1.3) +
    0.05 * Math.pow(value / (1.05 * maxInTrade), 6) +
    0.1
  ) * value;
  if (nerfIndex > 0) s *= Math.max(0.6, 1 - 0.15 * nerfIndex);
  if (s < 0) s /= 4;
  return s;
}

/**
 * KTC's reverseAdjust, ported verbatim from site.min.js.  Iteratively
 * solves for the player value V such that
 * ``ktcProcessV(V, maxInTrade, t, nerfCount) ≈ rawDiff``.
 *
 * Two-phase iterative search (not bisection): an outer 10-step coarse
 * pass with step-size 0.75x current error, then if convergence isn't
 * within 5% an inner 10-step refinement with step 0.25x.  Mirrors
 * KTC's implementation exactly so our virtual-player value matches
 * theirs to ±1.
 */
export function ktcReverseAdjust(rawDiff, maxInTrade, t, nerfCount) {
  if (!(rawDiff > 0) || !(maxInTrade > 0)) return 0;
  const seed = ktcProcessV(maxInTrade, maxInTrade, t, -1);
  let n = maxInTrade;
  if (seed < rawDiff) {
    n = Math.max((rawDiff / seed) * maxInTrade * 0.8, maxInTrade);
  }
  let l = n / 2;
  let d = 1;
  let u = 0;
  let bestErr = 1;
  let bestL = -1;
  while (d > 0.025 && u <= 10) {
    const i = ktcProcessV(l, n, t, nerfCount);
    d = Math.min(1, Math.abs(i - rawDiff) / rawDiff);
    if (d > 0.025) {
      const o = l;
      const p = d * l * 0.75;
      l += i <= rawDiff ? p : -p;
      if (d < bestErr) {
        bestErr = d;
        bestL = o;
        if (bestL > maxInTrade) n = bestL;
      }
    } else if (d < bestErr) {
      bestErr = d;
      bestL = l;
      if (bestL > maxInTrade) n = bestL;
    }
    if (u === 10 && d > 0.05) {
      let f = 0;
      l = Math.max(1, bestL);
      while (d > 0.025 && f <= 10) {
        const i2 = ktcProcessV(l, n, t, nerfCount);
        d = Math.min(1, Math.abs(i2 - rawDiff) / rawDiff);
        if (d > 0.025) {
          const o = l;
          const p = d * l * 0.25;
          l += i2 <= rawDiff ? p : -p;
          if (d < bestErr) {
            bestErr = d;
            bestL = o;
            if (bestL > maxInTrade) n = bestL;
          }
        } else if (d < bestErr) {
          bestErr = d;
          bestL = l;
          if (bestL > maxInTrade) n = bestL;
        }
        f++;
      }
      l = bestL;
    }
    u++;
  }
  return Math.round(l);
}

/**
 * KTC's checkEquality — returns true iff |a-b|/(a+b)*100 ≤ variancePct.
 * Used by adjustPackage to decide whether the trade is "fair" on
 * total values and on raw_adj sums.
 */
function ktcCheckEquality(a, b, variancePct) {
  const sum = Math.max(0, a) + Math.max(0, b);
  if (sum <= 0) return true;
  const pct = Math.min(100, (Math.abs(a - b) / sum) * 100);
  return parseFloat(Math.round(10 * pct) / 10) <= variancePct;
}

/**
 * Build per-piece adjustment list with KTC's progressive-nerf rule:
 * pieces below 0.5 × maxInTrade are flagged "small"; the FIRST small
 * piece is unnerfed (nerfIndex=0 → multiplier 1.0), subsequent ones
 * get nerfIndex 1,2,3,... (multiplier 0.85, 0.70, 0.60-floor).
 */
function _ktcBuildSideAdj(values, maxInTrade, t) {
  const half = 0.5 * maxInTrade;
  let nerfIndex = -1;
  let rawAdjSum = 0;
  const items = [];
  for (const v of values) {
    let nerfed = false;
    if (v < half) {
      nerfIndex++;
      nerfed = true;
    }
    const adj = ktcProcessV(v, maxInTrade, t, nerfIndex);
    rawAdjSum += adj;
    items.push({ value: v, adj, nerfed, nerfIndex });
  }
  items.sort((x, y) => y.adj - x.adj);
  return { items, rawAdjSum };
}

/**
 * KTC's adjustPackage, ported from site.min.js.  Takes two arrays of
 * raw KTC values (no row objects) and returns:
 *   { value: int, side: 0|1|2, displayed: bool }
 * where side is 1 if team1 receives the VA, 2 if team2 receives it,
 * and 0 when KTC would suppress the VA badge entirely.
 *
 * The port preserves KTC's branch structure exactly — every named
 * intermediate (e, a, h, y, v, k, b, T, P, w, V, M, R, A, S) maps
 * one-to-one to a variable in KTC's site.min.js.  See inline comments
 * for what each one represents.
 */
export function ktcAdjustPackage(team1Vals, team2Vals, opts = {}) {
  const variance = opts.variancePct ?? KTC_VARIANCE_PCT;
  const t = opts.t ?? KTC_T_REFERENCE;

  const tOne = [...team1Vals]
    .map((v) => Number(v) || 0)
    .filter((v) => v > 0)
    .sort((a, b) => b - a);
  const tTwo = [...team2Vals]
    .map((v) => Number(v) || 0)
    .filter((v) => v > 0)
    .sort((a, b) => b - a);
  if (tOne.length === 0 || tTwo.length === 0) {
    return { value: 0, side: 0, displayed: false };
  }

  const team1Total = tOne.reduce((q, v) => q + v, 0);
  const team2Total = tTwo.reduce((q, v) => q + v, 0);
  const r = Math.max(tOne[0], tTwo[0]);          // KTC's `r`
  const o = ktcProcessV(0.5 * r, r, t, -1);       // KTC's `o` — half-max raw_adj reference
  const { items: s, rawAdjSum: e } = _ktcBuildSideAdj(tOne, r, t);
  const { items: n, rawAdjSum: a } = _ktcBuildSideAdj(tTwo, r, t);
  const h = e / team1Total;                       // KTC's `h` — side1 intensity
  const y = a / team2Total;                       // KTC's `y` — side2 intensity
  const v = Math.floor(Math.abs(e - a));          // KTC's `v` — raw_adj diff
  const k = ktcCheckEquality(team1Total, team2Total, variance);
  const b = ktcCheckEquality(e, a, variance);

  // Compute T (extra nerf count for reverseAdjust).  KTC iterates the
  // larger-rawAdj side's items and records nerfIndex+1 of the FIRST
  // item whose adj falls below v (the raw_adj diff).  The original
  // source has dead-code in the loop body; we drop it.
  let T = 0;
  if (v < o) {
    const items = e > a ? n : s;
    for (const it of items) {
      if (it.adj < v) {
        T = it.nerfIndex + 1;
        break;
      }
    }
  }

  let side = 0;
  let value = 0;
  let w = true;

  if (k && b) {
    // BRANCH 1: both totals AND raw_adjs are within variance — small VA on the bigger raw_adj side
    if (e > a) {
      side = 1;
      const S = ktcReverseAdjust(v, r, t, T);
      const A = team2Total + S - team1Total;
      if (A > 0) value = A;
      else { w = false; side = 2; value = -A; }
    } else if (a > e) {
      side = 2;
      const S = ktcReverseAdjust(v, r, t, T);
      const A = team1Total + S - team2Total;
      if (A > 0) value = A;
      else { w = false; side = 1; value = -A; }
    }
  } else if (h > y) {
    // BRANCH 2: side1 has higher raw_adj intensity
    side = 1;
    if (e > a) {
      const S = ktcReverseAdjust(v, r, t, T);
      const A = team2Total + S - team1Total;
      if (A > 0) value = A;
      else { w = false; side = 2; value = Math.abs(A); }
    } else {
      // h > y but e <= a — "intensity flip" special branch
      let V = -1;
      if (team1Total < team2Total) V = 1;
      else if (team2Total < team1Total) V = 2;
      const M = ktcReverseAdjust(Math.abs(e - a), Math.max(...tOne, ...tTwo), 10099, T);
      if (M > 0 && V > 0) {
        side = V;
        if (V === 2) {
          const R = M - (team1Total - team2Total);
          if (R > 0) value = R;
          else { w = false; value = R; }
        } else {
          // V === 1
          const R = M - (team2Total - team1Total);
          if (R > 0) {
            if (R > KTC_MAX_PLAYER_VAL) { w = false; value = 0; side = 1; }
            else { side = 2; value = R; }
          } else { w = true; value = -R; }
        }
      } else {
        w = false;
      }
    }
  } else {
    // BRANCH 3: side2 has higher raw_adj intensity (mirror of branch 2)
    side = 2;
    if (a > e) {
      const S = ktcReverseAdjust(v, r, t, T);
      const A = team1Total + S - team2Total;
      if (A > 0) value = A;
      else { w = false; side = 1; value = Math.abs(A); }
    } else {
      let V = -1;
      if (team1Total < team2Total) V = 1;
      else if (team2Total < team1Total) V = 2;
      const M = ktcReverseAdjust(Math.abs(e - a), Math.max(...tOne, ...tTwo), 10099, T);
      if (M > 0 && V > 0) {
        side = V;
        if (V === 1) {
          const R = M - (team2Total - team1Total);
          if (R > 0) value = R;
          else { w = false; value = R; }
        } else {
          // V === 2
          const R = M - (team1Total - team2Total);
          if (R > 0) {
            if (R > KTC_MAX_PLAYER_VAL) { w = false; value = 0; side = 1; }
            else { side = 1; value = R; }
          } else { w = true; value = -R; }
        }
      } else {
        w = false;
      }
    }
  }

  // KTC's display gates:
  //   1. Sign / fairness gate: only show when value passed sign-checks
  //      (w === true) AND the VA is at least 3.3% of combined trade
  //      volume.  Sub-3.3% VAs are KTC's "Fair Trade" zone.
  //   2. 1v1 gate: KTC's evaluateTrade() suppresses displayAdjustment()
  //      when both sides have exactly 1 piece, regardless of what
  //      adjustPackage computed.  Reproduce here so 1v1 always returns
  //      displayed=false even if the math fired a non-zero value.
  let displayed = false;
  if (value !== 0) {
    if (w) displayed = true;
    if (Math.abs(value / (team1Total + team2Total)) < 0.033) displayed = false;
  }
  if (tOne.length === 1 && tTwo.length === 1) displayed = false;
  if (!displayed) return { value: 0, side: 0, displayed: false };
  return { value: Math.round(value), side, displayed: true };
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
  // Direct port path: ktcAdjustPackage returns side ∈ {0, 1, 2}
  // matching KTC's team1/team2 convention.  Map to our 0-indexed
  // recipientIdx.
  const result = ktcAdjustPackage(aValues, bValues);
  if (!result.displayed || result.value <= 0 || result.side === 0) {
    return { adjustment: 0, recipientIdx: null };
  }
  return {
    adjustment: result.value,
    recipientIdx: result.side === 1 ? 0 : 1,
  };
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
  // For each side, fold the rest into one synthetic opposing side and
  // ask ktcAdjustPackage if THIS side is the recipient.  This is the
  // direct N-side generalization of the 2-side ktcAdjustPackage call,
  // matching the prior _vaFromSortedSides semantic of "what does this
  // side receive given the rest as opposition".
  return allValues.map((thisSide, i) => {
    if (thisSide.length === 0) return 0;
    const others = [];
    for (let j = 0; j < allValues.length; j++) {
      if (j !== i) others.push(...allValues[j]);
    }
    if (others.length === 0) return 0;
    const result = ktcAdjustPackage(thisSide, others);
    if (!result.displayed || result.value <= 0) return 0;
    // side === 1 means team1 (i.e. thisSide) gets the VA
    return result.side === 1 ? result.value : 0;
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
  // 2-side fast path: direct ktcAdjustPackage call.  N-side path folds
  // every other side into the opposing array, mirroring
  // computeMultiSideAdjustments.
  if (sorted.length === 2) {
    const result = ktcAdjustPackage(sorted[0], sorted[1]);
    if (!result.displayed || result.value <= 0) return [0, 0];
    return result.side === 1 ? [result.value, 0] : [0, result.value];
  }
  return sorted.map((thisSide, i) => {
    if (thisSide.length === 0) return 0;
    const others = [];
    for (let j = 0; j < sorted.length; j++) {
      if (j !== i) others.push(...sorted[j]);
    }
    if (others.length === 0) return 0;
    const result = ktcAdjustPackage(thisSide, others);
    if (!result.displayed || result.value <= 0) return 0;
    return result.side === 1 ? result.value : 0;
  });
}

// ── Draft-capital stack effect ───────────────────────────────────────────
//
// A pick's worth depends on the receiving team's existing draft
// capital.  Given the routing (which pick auction-$ moves between which
// teams), recompute the league's zero-sum effective auction power
// before/after the trade; each team's CHANGE in premium-over-raw is the
// stack effect of this trade for that team.  It's returned in
// board-value units (converted via the trade's own pick board-$ ratio)
// so it folds straight into the fairness gap, and surfaced explicitly
// (never a silent verdict shift).
//
// stackContext = {
//   sideTeams:   string[]            // side idx → league team (null = unset)
//   leagueStacks:{ [team]: number }  // auction $ for every league team
//   moves:       [{ from, to, dollars, board }]  // from/to are side idx
// }
// Returns number[] (board-unit stack adjustment per side); zeros when
// the context is absent/insufficient.
export function computeStackAdjustments(numSides, stackContext) {
  const zeros = Array(numSides).fill(0);
  if (!stackContext) return zeros;
  const { sideTeams, leagueStacks, moves } = stackContext;
  if (!Array.isArray(sideTeams) || !leagueStacks || !Array.isArray(moves)) {
    return zeros;
  }
  if (moves.length === 0) return zeros;

  const post = { ...leagueStacks };
  let sumBoard = 0;
  let sumDollars = 0;
  for (const mv of moves) {
    const fromT = sideTeams[mv.from];
    const toT = sideTeams[mv.to];
    const d = Number(mv.dollars) || 0;
    if (fromT == null || toT == null) return zeros; // gate not satisfied
    if (!(fromT in post)) post[fromT] = 0;
    if (!(toT in post)) post[toT] = 0;
    post[fromT] -= d;
    post[toT] += d;
    sumBoard += Number(mv.board) || 0;
    sumDollars += d;
  }
  if (sumDollars <= 0) return zeros;
  const k = sumBoard / sumDollars; // $ → board-value units

  const before = effectiveAuctionPower(leagueStacks);
  const after = effectiveAuctionPower(post);
  return sideTeams.map((team) => {
    if (team == null || !(team in leagueStacks)) return 0;
    const premiumBefore = (before[team] || 0) - (leagueStacks[team] || 0);
    const premiumAfter = (after[team] || 0) - (post[team] || 0);
    return (premiumAfter - premiumBefore) * k;
  });
}

/**
 * Adjusted per-side totals for 2-team trade display.
 * Each entry is { raw, adjustment, adjusted, stackAdjustment } where
 * `adjusted = raw + adjustment + stackAdjustment`.  The KTC value
 * adjustment only credits the recipient side; the draft-capital stack
 * effect (optional `stackContext`) can credit/debit either side.
 */
export function adjustedSideTotals(
  sideA,
  sideB,
  valueMode,
  settings = null,
  stackContext = null,
) {
  const rawA = sideTotal(sideA, valueMode, settings);
  const rawB = sideTotal(sideB, valueMode, settings);
  const { adjustment, recipientIdx } = computeValueAdjustment(sideA, sideB, valueMode, settings);
  const adjA = recipientIdx === 0 ? adjustment : 0;
  const adjB = recipientIdx === 1 ? adjustment : 0;
  const [stackA, stackB] = computeStackAdjustments(2, stackContext);
  // stackX = the premium team X GAINS from the picks it RECEIVES in
  // this trade (positive = its stack improved).  A side that benefits
  // from what it's receiving effectively gives up LESS, so the premium
  // is SUBTRACTED from that side's giving total — never added to the
  // side that happened to hold the pick.
  return [
    { raw: rawA, adjustment: adjA, stackAdjustment: stackA, adjusted: rawA + adjA - stackA },
    { raw: rawB, adjustment: adjB, stackAdjustment: stackB, adjusted: rawB + adjB - stackB },
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
export function multiAdjustedSideTotals(
  sides,
  valueMode,
  settings = null,
  stackContext = null,
) {
  const adjustments = computeMultiSideAdjustments(sides, valueMode, settings);
  const stack = computeStackAdjustments(sides.length, stackContext);
  return sides.map((side, i) => {
    const raw = sideTotal(side, valueMode, settings);
    const adjustment = adjustments[i] || 0;
    const stackAdjustment = stack[i] || 0;
    return {
      raw,
      adjustment,
      stackAdjustment,
      // Premium a side gains from what it receives reduces what it
      // effectively gives up (see adjustedSideTotals).
      adjusted: raw + adjustment - stackAdjustment,
    };
  });
}

/** Gap = Side A adjusted total − Side B adjusted total (KTC-style). */
export function tradeGapAdjusted(
  sideA,
  sideB,
  valueMode,
  settings = null,
  stackContext = null,
) {
  const totals = adjustedSideTotals(sideA, sideB, valueMode, settings, stackContext);
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
// LIVE REGRESSION FIX. #740 moved the market gap into value space and did
// the careful thing on the way: it published the new number as
// ``marketGapValueRatio`` and stamped ``marketGapMagnitude = None`` on every
// row, so that a consumer still reading the old field would fail visibly
// rather than gate on a retired unit.
//
// This function was that consumer, and it failed silently anyway:
// ``Number(null)`` is 0, 0 is finite, and ``0 < 3`` — so the guard below
// returned early for EVERY player and the trade page's BUY/SELL edge went
// dead across the board. Its tests stayed green because they feed
// rank-space fixtures (2, 5, 6) against a rank-space threshold (3); nothing
// exercised it against a real contract row.
//
// Reads the live field now, gated on the shared ratio threshold rather than
// a local literal — if the board will not label a gap, a trade surface must
// not signal on it.

/**
 * Compute the retail-vs-consensus edge signal for a player row.
 *
 * Reads the backend-stamped ``marketGapDirection`` /
 * ``marketGapMagnitude`` directly — no client-side recompute from
 * per-source values.
 *
 * @param {object} row - Player row with marketGapDirection + marketGapMagnitude
 * @returns {{ signal: 'BUY'|'SELL'|null, edgePct: number, valueGapPct: number, sources: string[] }}
 */
export function getPlayerEdge(row) {
  if (!row) return { signal: null, edgePct: 0, valueGapPct: 0, sources: [] };

  const direction = String(row.marketGapDirection || "none");
  // ``marketGapValueRatio`` is a RELATIVE gap in blended-value space:
  // 0.25 means one side prices the player 25% above the other.
  const magnitude = Number(row.marketGapValueRatio);
  if (!Number.isFinite(magnitude) || magnitude < MARKET_GAP_MIN_VALUE_RATIO) {
    return { signal: null, edgePct: 0, valueGapPct: 0, sources: ["ktc"] };
  }
  if (direction !== "retail_premium" && direction !== "consensus_premium") {
    return { signal: null, edgePct: 0, valueGapPct: 0, sources: ["ktc"] };
  }

  // Translate the rank gap into a rough value-% for display continuity
  // with the old UI.  We compare the row's live value against its KTC
  // canonical-site value when available, else derive from the rank
  // gap.  The SIGNAL itself is rank-driven — this % is purely a
  // human-readable "how different is the price".
  //
  // Read KTC's TE++ raw scrape (``rawSourceValues.ktcSfTep``) so the
  // gap matches what the user sees on keeptradecut.com.  Falls back
  // to ``canonicalSites.ktcSfTep`` (post PR #406 this equals the raw
  // scrape verbatim — KTC is exempt from the blend-time TE
  // multiplier) if the rawSourceValues stamp is missing, then to the
  // legacy ``canonicalSites.ktc`` board for pre-#393 fixtures.
  let edgePct = 0;
  const ourValue = Number(row?.values?.full);
  const ktcValue =
    Number(row?.rawSourceValues?.ktcSfTep) ||
    Number(row?.canonicalSites?.ktcSfTep) ||
    Number(row?.canonicalSites?.ktc);
  if (Number.isFinite(ourValue) && ourValue > 0 && Number.isFinite(ktcValue) && ktcValue > 0) {
    edgePct = Math.round(Math.abs(((ourValue - ktcValue) / ktcValue) * 100));
  } else {
    // Fallback: the market gap is the best we have.  This used to render
    // an ordinal rank difference into a field named ``edgePct``, which was
    // not a percentage of anything — "a 3-rank gap" and "3%" are unrelated
    // quantities and the UI printed the second while meaning the first.
    // In value space the conversion is real: the ratio IS a relative
    // difference, so x100 is an honest percentage.
    edgePct = Math.round(magnitude * 100);
  }

  return {
    // consensus_premium → BUY LOW (market undervalues the player)
    // retail_premium    → SELL HIGH (market overvalues the player)
    signal: direction === "consensus_premium" ? "BUY" : "SELL",
    edgePct,
    // Renamed from ``rankGap``: it is no longer a count of ranks.
    // Math.round() on a 0-1 ratio collapsed every gap to 0.
    valueGapPct: Math.round(magnitude * 100),
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

    // 5) Year + round only ("2026 1st", "2027 2nd") — Sleeper's
    //    /traded_picks endpoint emits these labels for every owned pick
    //    because slots aren't tracked there.  Without a slot or tier
    //    the rankings row never matches, so default to the tier-centre
    //    "Mid" slot used elsewhere in the pipeline (matches the trade
    //    history valuation convention in _format_trade_pick_label).
    if (!slot && !tier && roundDigit) {
      push(`${year} Mid ${round}`);
      push(`${year} Pick ${roundDigit}.06`);
      push(`${year} ${roundDigit}.06`);
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
export function isSuppressedGenericPickRow(row) {
  if (!row) return false;
  return Boolean(row.pickGenericSuppressed || row.raw?.pickGenericSuppressed);
}

/**
 * True if a board row can be offered as a trade asset.
 *
 * The only rows excluded are the suppressed generic-tier pick aliases
 * above: they are DUPLICATES of a row already on the board (the
 * slot-specific sibling `pickAliases` redirects them to), and the
 * backend cleared their value, so offering one adds a second copy of
 * the same asset priced at nothing.
 *
 * `/trade` used to express this as a hardcoded `/^2026\b/` regex at
 * four call sites, which is a different rule wearing the same clothes.
 * It removed the 72 SLOT rows the current-year board is actually priced
 * on: typing "2026" or "2026 Pick 1.0" into the only search box on the
 * page returned zero results, while "2027 Mid 1st" returned a row, so
 * the omission read as the app not having the asset rather than as a
 * filter. It would also have excluded the wrong year from 2027 onward.
 * Audit finding W08-F004.
 *
 * Unpriced rows are deliberately NOT excluded here — the board declines
 * to price 260 of 1,072 rows and hiding them would be a bigger lie than
 * showing them. They are labelled instead, at the chip.
 */
export function isTradeableBoardRow(row) {
  if (!row) return false;
  return !(row.assetClass === "pick" && isSuppressedGenericPickRow(row));
}

/**
 * True if the board declined to price this row.
 *
 * 260 of 1,072 materialised rows carry `rankDerivedValue: null` -> a
 * `values.full` of 0, including every 2027/2028 5th and 6th (48 of the
 * league's 216 roster picks). Added to a trade they render as an
 * ordinary chip contributing 0 to the side total, the gap, the verdict
 * and the CSV export — indistinguishable from an asset that is priced
 * and merely cheap. Audit finding W08-F006.
 */
export function isUnpricedBoardRow(row) {
  if (!row) return false;
  if (row.rankDerivedValue != null) return false;
  return !Number(row.values?.full);
}

/**
 * Board rows matching a search query, excluding anything already in the
 * trade. Sorted by blended source rank so the most relevant dynasty
 * assets come first — the KTC trade-calculator UX.
 *
 * Extracted from `/trade`'s `searchAssets` so the asset-eligibility
 * rule is one testable function rather than an inline predicate
 * repeated beside three other copies of itself.
 */
export function searchTradeAssets(rows, query, excludedNames, limit = 5) {
  const q = String(query || "")
    .trim()
    .toLowerCase();
  if (!q) return [];
  const excluded =
    excludedNames instanceof Set ? excludedNames : new Set(excludedNames || []);
  const list = (rows || []).filter(
    (r) =>
      r &&
      !excluded.has(r.name) &&
      isTradeableBoardRow(r) &&
      String(r.name).toLowerCase().includes(q),
  );
  list.sort(
    (a, b) =>
      (a.blendedSourceRank ?? Infinity) - (b.blendedSourceRank ?? Infinity),
  );
  return list.slice(0, limit);
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
 * Find add-ons that actually close the gap the user is being shown.
 *
 * ──────────────────────────────────────────────────────────────────────
 * Why this simulates instead of matching a value (defect #800)
 * ──────────────────────────────────────────────────────────────────────
 * The gap on screen is the ADJUSTED gap — ``raw + Value Adjustment −
 * stack``, from ``adjustedSideTotals`` / ``tradeImbalance``.  This
 * function used to be handed that number and then rank candidates by
 * ``Math.abs(candidate.rawValue − |gap|)``: a RAW player value matched
 * against an ADJUSTED target.
 *
 * That arithmetic is only valid if adding a piece worth ``V`` moves the
 * adjusted gap by ``V``, and it does not.  VA is a function of BOTH
 * sides' complete value arrays, so adding a piece re-runs
 * ``ktcAdjustPackage`` from scratch — the piece count changes, the
 * progressive-nerf ladder shifts, the recipient side can flip, and the
 * 1-v-1 / 3.3% display gates snap on or off.
 *
 * Measured over 4,000 seeded two-side trades in which a near-even
 * landing WAS reachable from the candidate pool, the value-matching
 * rule missed it **43.2%** of the time, and in **701** of those cases it
 * handed the lead to the other side.  Mean residual gap 1,007 against an
 * achievable 50.
 *
 * So the signature takes the TRADE, not a pre-computed number: a caller
 * cannot hand this function a gap from one representation and a pool
 * priced in another.  Every candidate is scored by rebuilding the trade
 * with that candidate on the sweetening side and re-measuring through
 * ``tradeImbalance`` — the same path the meter renders.
 *
 * @param {object[]} sides       — side objects (``{ assets, destinations }``)
 * @param {number} behindIdx     — index of the side that must sweeten
 * @param {object[]} rosterRows  — candidate rows to choose from
 * @param {string} valueMode
 * @param {object}  [opts]
 * @param {object}  [opts.settings]
 * @param {object}  [opts.stackContext]
 * @param {number}  [opts.maxResults=5]
 * @param {number}  [opts.toSideIdx] — destination for the added asset in
 *        N >= 3 trades; defaults to the side netting the least.
 * @returns {{name: string, pos: string, value: number, gapBefore: number|null,
 *            gapAfter: number|null, imbalanceBefore: number,
 *            imbalanceAfter: number}[]}
 *        Sorted best-first.  Empty when the trade is already near even or
 *        nothing in the pool improves it.
 */
export function findBalancers(sides, behindIdx, rosterRows, valueMode, opts = {}) {
  const { settings = null, stackContext = null, maxResults = 5 } = opts;
  if (!Array.isArray(sides) || sides.length < 2) return [];
  if (!Number.isInteger(behindIdx) || behindIdx < 0 || behindIdx >= sides.length) {
    return [];
  }

  const before = tradeImbalance(sides, valueMode, settings, stackContext);
  if (before.imbalance < VERDICT_NEAR_EVEN) return [];

  // In an N >= 3 trade an added asset needs somewhere to go.  Default to
  // the side currently netting the least — the team this side is
  // shorting — rather than the circular default, which would route the
  // sweetener to whoever happens to sit next in the list.
  let toSideIdx = opts.toSideIdx;
  if (!Number.isInteger(toSideIdx) || toSideIdx === behindIdx) {
    toSideIdx = before.nets.indexOf(Math.min(...before.nets));
    if (toSideIdx === behindIdx) {
      toSideIdx = behindIdx === 0 ? 1 : 0;
    }
  }

  const withCandidate = (row) => {
    const next = sides.map((side, i) => {
      if (i !== behindIdx) return side;
      const assets = [...(Array.isArray(side?.assets) ? side.assets : []), row];
      if (sides.length === 2) return { ...side, assets };
      return {
        ...side,
        assets,
        destinations: { ...(side?.destinations || {}), [row.name]: toSideIdx },
      };
    });
    return tradeImbalance(next, valueMode, settings, stackContext);
  };

  const scored = [];
  for (const row of rosterRows || []) {
    // Unpriced rows cannot be shown to close anything, so they are
    // SKIPPED rather than coerced to zero.  A zero-value candidate would
    // let "we do not know what this is worth" render as "this changes
    // nothing" — MISSING IS NEVER ZERO.
    const value = Number(row?.values?.[valueMode]);
    if (!Number.isFinite(value) || value <= 0) continue;
    const after = withCandidate(row);
    if (!(after.imbalance < before.imbalance)) continue;
    scored.push({
      name: row.name,
      pos: row.pos,
      value,
      gapBefore: before.gap,
      gapAfter: after.gap,
      imbalanceBefore: before.imbalance,
      imbalanceAfter: after.imbalance,
    });
  }

  scored.sort((a, b) => a.imbalanceAfter - b.imbalanceAfter || a.name.localeCompare(b.name));
  return scored.slice(0, maxResults);
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
export function computeSideFlows(
  sides,
  valueMode,
  settings = null,
  stackContext = null,
) {
  const n = Array.isArray(sides) ? sides.length : 0;
  const result = [];
  for (let i = 0; i < n; i++) result.push({ given: 0, received: 0, net: 0, adjustment: 0 });
  if (n < 2) return result;

  const sideAssets = sides.map((side) =>
    Array.isArray(side?.assets) ? side.assets : [],
  );
  // Value Adjustment is a property of the PACKAGE, so it has to travel
  // with the assets when they are routed.  Each side's premium is
  // spread proportionally across the assets it sends, which makes
  // ``given_i = raw_i + adjustment_i`` by construction and lets the
  // premium land on whichever side actually receives those pieces.
  const adjustments = computeMultiSideAdjustments(sideAssets, valueMode, settings);

  for (let i = 0; i < n; i++) {
    const assets = sideAssets[i];
    const destinations = sides[i]?.destinations || {};
    let rawTotal = 0;
    for (const asset of assets) {
      rawTotal += Math.max(0, effectiveValue(asset, valueMode, settings));
    }
    const rawAdjustment = Number(adjustments[i]);
    // A non-finite premium means the VA could not be computed for this
    // side, which is "no premium to attribute", not "a premium of zero
    // that we measured".  Both land on 0 here because the arithmetic
    // neutral is the same, but the distinction is why this is written
    // out rather than coerced with ``|| 0``.
    const adjustment = Number.isFinite(rawAdjustment) && rawAdjustment > 0 ? rawAdjustment : 0;
    // A side whose pieces are all unpriced has nothing to scale, so the
    // premium is dropped rather than divided by zero.  The assets are
    // still counted; they just carry no premium nobody can attribute.
    const scale = rawTotal > 0 ? (rawTotal + adjustment) / rawTotal : 1;
    result[i].adjustment = rawTotal > 0 ? adjustment : 0;

    for (const asset of assets) {
      const value = Math.max(0, effectiveValue(asset, valueMode, settings)) * scale;
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
  // Fold the draft-capital stack premium into net so the multi-team
  // verdict bar (which renders from net, not adjusted totals) reflects
  // the same stack-aware result as the 2-team path.  A team's premium
  // from the picks it receives is extra value it nets.
  const stack = computeStackAdjustments(n, stackContext);
  for (let i = 0; i < n; i++) {
    result[i].net = result[i].received - result[i].given + (stack[i] || 0);
  }
  return result;
}

/**
 * The single imbalance number for a trade of ANY side count.
 *
 * ONE REPRESENTATION, EVERY N.  Before 2026-08-18 the 2-team meter read
 * VA-adjusted side totals while the 3+-team meter read a raw net flow
 * with no Value Adjustment in it at all, so the same trade shape graded
 * differently at 2 teams and at 3.  ``computeSideFlows`` is now
 * VA-inclusive and this is the one place the imbalance is defined.
 *
 * Returns ``{ imbalance, nets, gap }``:
 *   - ``nets``  — per-side net flow (received − given + stack)
 *   - ``gap``   — the signed 2-team gap (side A minus side B), or
 *                 ``null`` for N >= 3 where "which side is ahead" is not
 *                 a single signed number
 *   - ``imbalance`` — magnitude, comparable across N: ``|gap|`` for
 *                 N = 2, ``max(net) - min(net)`` for N >= 3.
 *
 * KNOWN, PRE-EXISTING, OUT OF SCOPE: the draft-capital stack term is
 * accounted differently by the two paths — ``adjustedSideTotals``
 * debits BOTH sides' stack into the gap while a net flow credits only
 * the side's own.  That difference predates this function, is zero for
 * every trade with no pick routing, and belongs to whoever revisits the
 * stack model.  With no ``stackContext`` the N = 2 identity
 * ``nets[1] === tradeGapAdjusted(A, B)`` holds exactly, and a test pins it.
 */
export function tradeImbalance(
  sides,
  valueMode,
  settings = null,
  stackContext = null,
) {
  const n = Array.isArray(sides) ? sides.length : 0;
  if (n < 2) return { imbalance: 0, nets: [], gap: null };
  const nets = computeSideFlows(sides, valueMode, settings, stackContext).map(
    (f) => f.net,
  );
  if (n === 2) {
    const gap = tradeGapAdjusted(
      Array.isArray(sides[0]?.assets) ? sides[0].assets : [],
      Array.isArray(sides[1]?.assets) ? sides[1].assets : [],
      valueMode,
      settings,
      stackContext,
    );
    return { imbalance: Math.abs(gap), nets, gap };
  }
  return {
    imbalance: Math.max(...nets) - Math.min(...nets),
    nets,
    gap: null,
  };
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

export function tradeWorkspaceToJSON(sides, valueMode, activeSide) {
  return JSON.stringify(serializeWorkspaceMulti(sides, valueMode, activeSide), null, 2);
}

// `valueBasis` is the human-readable board these values came from
// ("Market consensus" / "League-adjusted ..."), from
// `valuationBasisLabel`. It rides as a COLUMN rather than a preamble
// because an exported trade outlives the app: a market valuation and a
// league-adjusted one answer different questions about the same trade,
// and once the rows are in a spreadsheet nothing else distinguishes
// them. A header line would be lost the first time someone sorts or
// pastes a subset.
//
// Defaulted rather than required so an existing caller cannot silently
// break — but the default says "unspecified", never "Market", because
// guessing the basis is the exact error this column exists to prevent.
export function tradeWorkspaceToCSV(sides, valueMode = "full", valueBasis = "") {
  const esc = (v) => {
    const s = v == null ? "" : String(v);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const pickVal = (r) => {
    const vals = (r && r.values) || {};
    const v = valueMode === "raw" ? (vals.raw ?? vals.full) : (vals.full ?? vals.raw);
    return v == null ? "" : Math.round(Number(v));
  };
  const basis = valueBasis || "unspecified";
  const lines = ["Side,Asset,Position,Team,Value,Value Basis"];
  for (const s of sides || []) {
    for (const r of s.assets || []) {
      lines.push(
        [s.label, r.name, r.pos || "", r.team || "", pickVal(r), basis].map(esc).join(","),
      );
    }
  }
  return lines.join("\n") + "\n";
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
