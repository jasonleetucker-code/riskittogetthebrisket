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
import { effectiveAuctionPowerExact } from "./auction-power.js";
import { MARKET_GAP_MIN_VALUE_RATIO } from "./thresholds.js";
import {
  classifyGap,
  fairnessBase,
  FairnessInputError,
  FAIRNESS_INPUT_ERROR_CODE,
  FAIRNESS_LABELS,
  isFiniteNumber,
  relativeGapPct,
} from "./fairness-bands.js";
import {
  canAddEntry,
  deserializeEntry,
  removeOneEntry,
  searchMatchTier,
  searchPickEntries,
  serializeEntry,
  tradeEntryKey,
} from "./trade-assets.js";

// ── Value Modes ──────────────────────────────────────────────────────────
// Trade math runs on ONE value: the canonical ``rankDerivedValue`` carried as
// ``values.full``.  The "Raw" mode is RETIRED (TC-A, UX audit P0-4): it read
// ``values.raw`` -- the legacy scraper ``rawComposite`` (0.27x-2.08x of
// canonical) -- so a display toggle rewired the meter, the tray, the
// balancers and the CSV onto a non-canonical number, while the side cards'
// "Raw" (canonical BEFORE Value Adjustment) meant something else and the War
// Room, Monte Carlo and Second Opinions stayed canonical.  "Raw" on /trade
// now means only canonical-before-VA, shown on the side cards.  A workspace
// saved with ``valueMode: "raw"`` restores as ``"full"``.
export const VALUE_MODES = [{ key: "full", label: "Our Value" }];

/** The value mode trade math uses: always canonical. */
export const TRADE_VALUE_MODE = "full";

// ── Persistence Keys ─────────────────────────────────────────────────────
export const STORAGE_KEY = "next_trade_workspace_v1";
export const RECENT_KEY = "next_trade_recent_assets_v1";
export const SETTINGS_KEY = "next_settings_v2";

// ── Verdict bands ────────────────────────────────────────────────────────
// The KTC-era absolute bands (350 / 900 / 1800) are RETIRED (TC-C, owner
// decision 3).  Every package-gap label on /trade comes from the ONE
// fairness-band owner (./fairness-bands.js, pinned to
// config/trade/fairness_bands.json): fairness_bands_v2, relative to the larger
// PACKAGE UTILITY (`packageUtilities` below, stamped as `utility` on side
// totals and side flows), with an absolute minimum.  Owner-approved prior,
// validated after launch.

// ── Legacy Power-Weighted Alpha (trade history only) ─────────────────────
// The Trade Calculator no longer uses this; it has moved to the package
// Value Adjustment model below (packageAdjustPair).  `TRADE_ALPHA` is kept
// as a retrospective grading exponent for past trades on the `/trades`
// history page, where a consolidation premium can't be attributed after
// the fact.
export const TRADE_ALPHA = 1.65;

// ── Value Adjustment: ONE owner — the packageAdjustPair dispatch ────────
//
// (ACTIVE model: geom_q078_v1 since 2026-10-17; ktcAdjustPackage is the
// retained KTC rollback model behind the same dispatch.)
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

/**
 * Identity of a trade's CONTENTS: every side's lines in order (name, owned
 * pick id, override) plus 3+-team routing.  Expensive results computed for
 * a trade (Simulate impact, Monte Carlo) are keyed to it, so a result is
 * never shown under a trade it was not computed for (TC-A / UX audit P0-2).
 */
export function tradeSignature(sides) {
  return JSON.stringify(
    (sides || []).map((s) => [
      (s?.assets || []).map((a) => [a?.name ?? "", a?.assetId ?? null, a?.customValue ?? null]),
      s?.destinations || {},
    ]),
  );
}

/**
 * The question "Simulate impact" answers: the trade's contents plus the team
 * and league it is simulated for.  The page shows a result only while this
 * still matches the trade on screen (TC-A / UX audit P0-2).
 */
export function simulationSignature(sides, teamName = "", leagueKey = "") {
  return JSON.stringify([tradeSignature(sides), teamName || "", leagueKey || ""]);
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

/**
 * Whether a trade can be evaluated at all — the gate every headline verdict
 * (meter badge, winner text, sticky tray) passes before it may speak.
 *
 *   empty       no asset on any side: "nothing to evaluate" is not an
 *               evaluation, so no band is rendered (UX audit P0-6).
 *   incomplete  some asset is unpriced by the board (and not overridden):
 *               its 0 inside the totals is an arithmetic neutral, not a
 *               value, so no verdict is computed over it (MISSING IS
 *               NEVER ZERO).  ``unpriced`` names each one by side.
 *   complete    every asset carries a value.
 *
 * Pass the OVERRIDE-APPLIED sides: a user value on an unpriced row prices it.
 */
export const TRADE_EVAL_STATE = Object.freeze({
  EMPTY: "empty",
  INCOMPLETE: "incomplete",
  COMPLETE: "complete",
});

export function tradeEvaluationState(sides) {
  const list = Array.isArray(sides) ? sides : [];
  if (!list.some((s) => (s?.assets || []).length > 0)) {
    return { state: TRADE_EVAL_STATE.EMPTY, unpriced: [] };
  }
  const unpriced = [];
  list.forEach((s, side) => {
    for (const r of unpricedAssetsOnSide(s?.assets)) {
      unpriced.push({ side, name: r?.name || r?.displayName || "An asset" });
    }
  });
  if (unpriced.length) return { state: TRADE_EVAL_STATE.INCOMPLETE, unpriced };
  return { state: TRADE_EVAL_STATE.COMPLETE, unpriced: [] };
}

/**
 * Why a board row's value is WITHHELD from a team result, or ``null``.
 *
 * Reads the pipeline's own stamps, in the engine's gate order
 * (``src/trade/trade_decision.py::asset_evidence_codes``, which gives the
 * leg ``valueState`` quarantined / stale in ``analyze_service._value_entry``):
 *
 *   ``"quarantined"``  the row-level quarantine verdict (``quarantined``)
 *   ``"stale"``        the confidence owner's freshness axis reads ``low``
 *                      (``confidenceAxes.freshness``, carried on ``raw``)
 *
 * Read, never computed: no threshold or freshness rule lives here, and an
 * absent stamp is not withheld (the engine treats it the same way).  A value
 * the user typed on the line (``customValue``) is the user's own number, not
 * the withheld board value, so it is not withheld — the same rule
 * ``unpricedAssetsOnSide`` applies to an unpriced row.
 */
export function withheldValueState(row) {
  if (!row || row.customValue != null) return null;
  if (row.quarantined === true || row.raw?.quarantined === true) return "quarantined";
  const freshness = row.confidenceAxes?.freshness ?? row.raw?.confidenceAxes?.freshness;
  if (freshness === "low") return "stale";
  return null;
}

/**
 * Per side, every WITHHELD asset in that team's part of a routed trade —
 * what it sends AND what is routed to it (``tradeRoutes``), because a team's
 * package gap reads both.  ``[{ name, state, direction: "out" | "in",
 * fromSide, toSide }]`` per side, in side order; ``[]`` for a side with none.
 *
 * The preliminary meter shows such a team as WITHHELD with the reason —
 * never its gap, never a band — and the multi-team headline as not
 * determinable (``multiTeamNetSummary``).  Pass the OVERRIDE-APPLIED sides.
 */
export function withheldAssetsBySide(sides) {
  const list = Array.isArray(sides) ? sides : [];
  const out = list.map(() => []);
  if (list.length < 2) return out;
  const routes = tradeRoutes(list);
  list.forEach((side, i) => {
    (Array.isArray(side?.assets) ? side.assets : []).forEach((asset, k) => {
      const state = withheldValueState(asset);
      if (!state) return;
      const to = routes[i]?.[k];
      const name = String(asset?.name || asset?.displayName || "An asset");
      out[i].push({ name, state, direction: "out", fromSide: i, toSide: to });
      if (Number.isInteger(to) && out[to]) {
        out[to].push({ name, state, direction: "in", fromSide: i, toSide: to });
      }
    });
  });
  return out;
}

const WITHHELD_STATE_WORDS = { quarantined: "quarantined", stale: "stale" };

/**
 * One side's withheld assets as words: "B Seven (sent, quarantined)".
 * ``null`` when there are none.
 */
export function withheldReasonText(entries) {
  const list = Array.isArray(entries) ? entries : [];
  if (!list.length) return null;
  return list
    .map(
      (e) =>
        `${e.name} (${e.direction === "in" ? "received" : "sent"}, ${
          WITHHELD_STATE_WORDS[e.state] || "withheld"
        })`,
    )
    .join(", ");
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
 * (Historical note: the V2 formula is retired; the active package model
 * is ``packageAdjustPair``, and every team of an N-team trade is read through
 * ``packageAdjustedPairTotals`` in its own perspective.)
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

// ── Package Value Adjustment model dispatch ──────────────────────────────
//
// Owner package 2026-10-17: every surface that publishes package-level trade
// equity uses the SAME named, versioned model.  This is the JS half of the
// dispatch (Python twin: src/valuation_math/package_model.py, parity pinned by
// tests/fixtures/package_model_parity_cases.json).  ACTIVE_PACKAGE_MODEL_ID is
// pinned equal to config/trade/package_model.json "active" by
// tests/valuation_math/test_package_model.py — promoting a challenger changes
// both in one PR, and only with the owner's explicit approval.
//
// * ktc_2026_04 — rollback: ktcAdjustPackage above, unchanged (its known
//   non-monotone cases are pinned as KNOWN_DEFECT in trade-logic.test.js).
// * geom_q078_v1 — owner-approved ACTIVE (2026-10-17): sorted package utility
//   U = sum q^(i-1) * v_i (q = 0.78, a PRIOR), shown as a positive-only
//   adjustment to the side that discarded less depth, so
//   adjustedA - adjustedB === U_A - U_B (up to integer rounding).

export const PACKAGE_MODEL_IDS = Object.freeze({
  KTC_2026_04: "ktc_2026_04",
  GEOM_Q078_V1: "geom_q078_v1",
});

export const PACKAGE_MODELS = Object.freeze({
  [PACKAGE_MODEL_IDS.KTC_2026_04]: Object.freeze({
    id: PACKAGE_MODEL_IDS.KTC_2026_04,
    family: "ktc",
    version: "2026-04",
    label: "KTC Value Adjustment (port of keeptradecut.com adjustPackage, April 2026)",
    classification: "FALLBACK",
  }),
  [PACKAGE_MODEL_IDS.GEOM_Q078_V1]: Object.freeze({
    id: PACKAGE_MODEL_IDS.GEOM_Q078_V1,
    family: "geom",
    version: "1",
    q: 0.78,
    label: "Geometric Value Adjustment (q = 0.78)",
    classification: "ACTIVE",
  }),
});

export const ACTIVE_PACKAGE_MODEL_ID = PACKAGE_MODEL_IDS.GEOM_Q078_V1;

export function packageModelReceipt(modelId = ACTIVE_PACKAGE_MODEL_ID) {
  const spec = PACKAGE_MODELS[modelId];
  if (!spec) throw new Error(`unknown package model ${modelId}`);
  const { id, family, version, label, classification } = spec;
  return { id, family, version, label, classification };
}

function positiveDesc(values) {
  return [...(values || [])]
    .map((v) => Number(v) || 0)
    .filter((v) => v > 0)
    .sort((a, b) => b - a);
}

/**
 * sum q^i * v_i over positive values sorted descending.
 *
 * Weights are built iteratively (w *= q) and summed left to right — never
 * `**` / Math.pow, whose results differ between V8 and CPython from i = 4 —
 * so this and src/valuation_math/package_model.py::geom_utility are the same
 * IEEE-754 operations in the same order (bit-identical; pinned by
 * tests/fixtures/package_model_float_cases.json).
 */
export function geomPackageUtility(values, q = PACKAGE_MODELS.geom_q078_v1.q) {
  let total = 0;
  let w = 1;
  for (const v of positiveDesc(values)) {
    total += v * w;
    w *= q;
  }
  return total;
}

/**
 * {value, side, displayed} for one package pairing under a model — KTC's
 * shape (side 1 = team1 receives, 2 = team2, 0 = none), so every consumer
 * keeps its contract.  modelId defaults to the ACTIVE model.
 */
export function packageAdjustPair(team1Vals, team2Vals, opts = {}) {
  const modelId = opts.modelId ?? ACTIVE_PACKAGE_MODEL_ID;
  const spec = PACKAGE_MODELS[modelId];
  if (!spec) throw new Error(`unknown package model ${modelId}`);
  const t1 = positiveDesc(team1Vals);
  const t2 = positiveDesc(team2Vals);
  if (t1.length === 0 || t2.length === 0) {
    return { value: 0, side: 0, displayed: false };
  }
  if (spec.family === "ktc") return ktcAdjustPackage(t1, t2);
  // Left-to-right addition, the same order as package_model._left_sum.
  const sum = (a) => a.reduce((acc, v) => acc + v, 0);
  const depth1 = sum(t1) - geomPackageUtility(t1, spec.q);
  const depth2 = sum(t2) - geomPackageUtility(t2, spec.q);
  // Math.round is half-up for positive numbers, matching ktc_va_core.js_round.
  const value = Math.round(Math.abs(depth1 - depth2));
  if (value <= 0) return { value: 0, side: 0, displayed: false };
  return { value, side: depth2 > depth1 ? 1 : 2, displayed: true };
}

/**
 * Each package's UTILITY under a model -- the fairness band's base
 * (fairness_bands_v2, OD-F2; Python twin:
 * src/valuation_math/fairness_bands.py::package_utilities).
 *
 * geom family: the depth-discounted utility `geomPackageUtility` of each
 * side's values.  ktc family (the rollback model) has no per-package utility,
 * so each side's ADJUSTED total stands in -- exactly the v1 basis, so a
 * package-model rollback restores v1 denominators.
 *
 * Every piece must be a finite number, else FairnessInputError (code
 * `fairness_input_not_finite`): `geomPackageUtility` prices a NaN piece as an
 * absent one, so without this check a missing value would be priced as 0
 * (MISSING IS NEVER ZERO).  Same refusal as the Python twin.
 *
 * @param {number[][]} valueArrays  one array of piece values per side
 * @param {number[]} adjustedTotals each side's adjusted total (raw + VA),
 *   read only under the ktc family
 * @param {{modelId?: string}} [opts]
 * @returns {number[]}
 */
export function packageUtilities(valueArrays, adjustedTotals, opts = {}) {
  const modelId = opts.modelId ?? ACTIVE_PACKAGE_MODEL_ID;
  const spec = PACKAGE_MODELS[modelId];
  if (!spec) throw new Error(`unknown package model ${modelId}`);
  const refuse = (what, v) => {
    throw new FairnessInputError(`${FAIRNESS_INPUT_ERROR_CODE}: ${what}=${String(v)}`);
  };
  if (!Array.isArray(valueArrays)) refuse("valueArrays", valueArrays);
  for (const values of valueArrays) {
    if (!Array.isArray(values)) refuse("side values", values);
    for (const v of values) if (!isFiniteNumber(v)) refuse("piece", v);
  }
  if (spec.family === "ktc") return valueArrays.map((_, i) => Number(adjustedTotals?.[i]));
  return valueArrays.map((values) => geomPackageUtility(values, spec.q));
}

/**
 * Compute the package Value Adjustment between two sides under the ACTIVE
 * package model (packageAdjustPair — the owner-approved geometric model,
 * geom_q078_v1, since 2026-10-17; KTC's adjustPackage port is the
 * rollback model).
 *
 * Under the geometric model each side's pieces are sorted best-first and
 * discounted by q^(i-1); the side that discarded less depth receives the
 * difference, so adjustedA - adjustedB === U_A - U_B.  Equal-count trades
 * can fire; a 1-for-1 never does.
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
  // packageAdjustPair returns side ∈ {0, 1, 2} in the team1/team2
  // convention (inherited from KTC's port).  Map to our 0-indexed
  // recipientIdx.
  const result = packageAdjustPair(aValues, bValues);
  if (!result.displayed || result.value <= 0 || result.side === 0) {
    return { adjustment: 0, recipientIdx: null };
  }
  return {
    adjustment: result.value,
    recipientIdx: result.side === 1 ? 0 : 1,
  };
}

/**
 * One team's package totals under the ACTIVE package model — the JS twin of
 * ``src/valuation_math/package_model.py::adjusted_pair_totals`` (spec
 * docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §5.1 item 1).
 *
 * ``sendValues`` are the values the team GIVES, ``recvValues`` the values it
 * RECEIVES — the first argument is always the gives.  Rules, all the owner's:
 *   * positive filtering: non-positive and non-finite values are dropped
 *     (an unpriced piece never enters as 0);
 *   * an empty side gets no adjustment: ``sendAdj = ΣG``, ``recvAdj = ΣR``;
 *   * otherwise ``packageAdjustPair`` decides: ``side === 1`` → the FIRST
 *     argument (the gives) carries the VA; it applies only when
 *     ``displayed && value > 0``.
 *
 * ``gap = recvAdj − sendAdj`` is the team's own adjusted gap.  The band base
 * is NOT decided here: it is the larger PACKAGE UTILITY of the team's
 * (gives, receives) (fairness_bands_v2, OD-F2 — ``teamFairnessBase``).
 *
 * @param {number[]} sendValues
 * @param {number[]} recvValues
 * @param {{modelId?: string}} [opts]
 * @returns {{sendRaw:number, recvRaw:number, sendAdj:number, recvAdj:number, sendVA:number, recvVA:number}}
 */
export function packageAdjustedPairTotals(sendValues, recvValues, opts = {}) {
  const keep = (xs) =>
    (Array.isArray(xs) ? xs : []).map(Number).filter((v) => Number.isFinite(v) && v > 0);
  const g = keep(sendValues);
  const r = keep(recvValues);
  // Left-to-right sums, the same order as package_model._left_sum.
  const sendRaw = g.reduce((acc, v) => acc + v, 0);
  const recvRaw = r.reduce((acc, v) => acc + v, 0);
  const none = {
    sendRaw,
    recvRaw,
    sendAdj: sendRaw,
    recvAdj: recvRaw,
    sendVA: 0,
    recvVA: 0,
  };
  if (g.length === 0 || r.length === 0) return none;
  const { value, side, displayed } = packageAdjustPair(
    g,
    r,
    opts.modelId ? { modelId: opts.modelId } : {},
  );
  if (!displayed || !(value > 0)) return none;
  return side === 1
    ? { ...none, sendAdj: sendRaw + value, sendVA: value }
    : { ...none, recvAdj: recvRaw + value, recvVA: value };
}

/**
 * Destination of every line in a trade: ``routes[i][k]`` is the side the k-th
 * asset of side i goes to.  Two sides route implicitly to each other; three
 * or more read ``side.destinations`` and fall back to ``defaultDestination``
 * (the same visible seed ``addToSide`` writes) for a missing, self or
 * out-of-range entry.  This is the preliminary indicator's routing only: the
 * authoritative ledger (lib/trade-multi-team.js) refuses such a line instead.
 */
export function tradeRoutes(sides) {
  const n = Array.isArray(sides) ? sides.length : 0;
  return (sides || []).map((side, i) =>
    (Array.isArray(side?.assets) ? side.assets : []).map((asset) => {
      if (n === 2) return 1 - i;
      const parsed = Number((side?.destinations || {})[tradeEntryKey(asset)]);
      return Number.isInteger(parsed) && parsed >= 0 && parsed < n && parsed !== i
        ? parsed
        : defaultDestination(i, n);
    }),
  );
}

/**
 * Per-team package reading of a routed trade of ANY side count (spec §5.1):
 * for each side i, G_i = what it sends, R_i = everything routed to it, and
 * ``packageAdjustedPairTotals(G_i, R_i)``.  Each team is valued in its OWN
 * perspective — there is no "union of every other side" opposition (the
 * retired ``computeMultiSideAdjustments`` collapse, directive §6).
 *
 * ``values[i][k]`` is the value of side i's k-th asset; ``routes`` as
 * ``tradeRoutes``.  Returns, per side:
 *   rawGiven / rawReceived  RAW routed flows (conserved: Σ given = Σ received)
 *   sendAdj / recvAdj / sendVA / recvVA  the team's own package totals
 *   gap      recvAdj − sendAdj (the team's adjusted gap)
 *   larger   max(sendAdj, recvAdj) — a DISPLAY number only (v1's base)
 *   utility / receivedUtility  the package utility of what the team sends /
 *            receives (``packageUtilities``; null when a piece is not finite)
 *   largerUtility  the band base: ``fairnessBase([utility, receivedUtility])``
 *            — the owner's larger package utility (Python twin:
 *            ``fairness_bands.larger_package_utility(G_i, R_i)``)
 *   band     classifyGap(gap, largerUtility) — null when either is unknown
 */
export function perTeamPackageTotals(values, routes, opts = {}) {
  const n = Array.isArray(values) ? values.length : 0;
  const gives = Array.from({ length: n }, () => []);
  const recvs = Array.from({ length: n }, () => []);
  for (let i = 0; i < n; i++) {
    const vs = Array.isArray(values[i]) ? values[i] : [];
    vs.forEach((v, k) => {
      gives[i].push(v);
      const dest = routes?.[i]?.[k];
      if (Number.isInteger(dest) && dest >= 0 && dest < n) recvs[dest].push(v);
    });
  }
  return gives.map((g, i) => {
    const t = packageAdjustedPairTotals(g, recvs[i], opts);
    const gap = t.recvAdj - t.sendAdj;
    const larger = Math.max(t.sendAdj, t.recvAdj);
    // fairness_bands_v2 (OD-F2): the base is the larger PACKAGE UTILITY of
    // this team's (gives, receives), from the package-model layer and the
    // owner's fairnessBase.  A piece that is not a finite number is refused
    // there (FairnessInputError) and leaves the team UNKNOWN (null), never
    // priced as 0 and never read as fair.
    const util = teamPackageUtilities(g, recvs[i], t, opts);
    const band =
      util && Number.isFinite(gap) ? classifyGap(gap, util.largerUtility) : null;
    return {
      rawGiven: t.sendRaw,
      rawReceived: t.recvRaw,
      sendAdj: t.sendAdj,
      recvAdj: t.recvAdj,
      sendVA: t.sendVA,
      recvVA: t.recvVA,
      gap,
      larger,
      utility: util ? util.utility : null,
      receivedUtility: util ? util.receivedUtility : null,
      largerUtility: util ? util.largerUtility : null,
      band,
    };
  });
}

/**
 * One team's package utilities under the active package model —
 * ``{utility, receivedUtility, largerUtility}`` for what it sends / receives
 * and the fairness band's base, or ``null`` when the owner refuses an input
 * (a non-finite piece).  ``totals`` is the team's
 * ``packageAdjustedPairTotals`` (read only by the ktc rollback family).
 */
function teamPackageUtilities(gives, receives, totals, opts = {}) {
  const sortDesc = (xs) => xs.map(Number).sort((a, b) => b - a);
  try {
    const [utility, receivedUtility] = packageUtilities(
      [sortDesc(gives), sortDesc(receives)],
      [totals.sendAdj, totals.recvAdj],
      opts.modelId ? { modelId: opts.modelId } : {},
    );
    return { utility, receivedUtility, largerUtility: fairnessBase([utility, receivedUtility]) };
  } catch (err) {
    if (err instanceof FairnessInputError) return null;
    throw err;
  }
}

/**
 * The fairness band's base for ONE team of a routed trade (fairness_bands_v2,
 * OD-F2): the owner's ``fairnessBase`` over the package utility of what the
 * team sends (``utility``) and what it receives (``receivedUtility``).
 * ``null`` when either is missing or not finite — the team is UNKNOWN, never
 * fair and never priced at 0.  Python twin:
 * ``fairness_bands.larger_package_utility(G_i, R_i)``.
 * @param {{utility:number, receivedUtility:number}} flow
 * @returns {number|null}
 */
export function teamFairnessBase(flow) {
  try {
    return fairnessBase([flow?.utility, flow?.receivedUtility]);
  } catch (err) {
    if (err instanceof FairnessInputError) return null;
    throw err;
  }
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
 * Returns an array of adjustments matching the input order — the VA each
 * side's OWN package (what it sends) carries.  Exactly one element is
 * populated for a 2-side trade.  For N ≥ 3 the adjustment is per team, in
 * that team's own perspective (``packageAdjustedPairTotals(G_i, R_i).sendVA``),
 * so it needs the routing: ``opts.routes`` (``tradeRoutes`` shape).  Without
 * it a 3+-side call returns ``null`` — there is no routing-free per-side
 * number, and the retired "union of every other side" stand-in is gone
 * (spec docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §5.1, directive §6).
 *
 * ``opts.modelId`` selects a registered package model (default: the ACTIVE
 * one).  Only the read-only comparison surfaces pass it (owner directive
 * 2026-10-19: the KTC adjustment method beside Chase Upside's, never blended)
 * — every decision path calls this with no model option.
 *
 * @param {number[][]} sidesValues  — array of raw-value arrays, one per side
 * @param {{modelId?: string, routes?: number[][]}} [opts]
 * @returns {number[] | null}
 */
export function valueAdjustmentFromSideArrays(sidesValues, opts = {}) {
  const pairOpts = opts.modelId ? { modelId: opts.modelId } : {};
  if (!Array.isArray(sidesValues) || sidesValues.length < 2) {
    return (sidesValues || []).map(() => 0);
  }
  if (sidesValues.length === 2) {
    const sorted = sidesValues.map((raw) =>
      (Array.isArray(raw) ? raw : [])
        .map((v) => Number(v) || 0)
        .filter((v) => v > 0)
        .sort((a, b) => b - a),
    );
    const result = packageAdjustPair(sorted[0], sorted[1], pairOpts);
    if (!result.displayed || result.value <= 0) return [0, 0];
    return result.side === 1 ? [result.value, 0] : [0, result.value];
  }
  if (!Array.isArray(opts.routes) || opts.routes.length !== sidesValues.length) return null;
  // Values pass through UNCOERCED: the k-th entry must stay aligned with the
  // k-th route, and packageAdjustedPairTotals drops non-finite / non-positive
  // entries itself, so an unpriced piece is excluded — never priced at 0.
  return perTeamPackageTotals(
    sidesValues.map((raw) => (Array.isArray(raw) ? raw : [])),
    opts.routes,
    pairOpts,
  ).map((t) => t.sendVA);
}

// ── Draft-capital stack effect ───────────────────────────────────────────
//
// A pick's worth depends on the receiving team's existing draft
// capital.  Given the routing (which pick auction-$ moves between which
// teams), recompute the league's zero-sum effective auction power
// before/after the trade; each team's CHANGE in premium-over-raw is the
// stack effect of this trade for that team, in board-value units at the
// LEAGUE DRAFT POOL's board-per-$ rate (``poolBoardPerDollar``).
//
// INFORMATIONAL ONLY (owner directive 2026-09-29).  No decision helper in
// this file consumes it -- side totals, the gap/verdict, side flows,
// imbalance and balancers are raw + Value Adjustment, and none of them
// accepts a stack input (pinned by __tests__/trade-stack-withdrawn.test.js).
// The acceptance audit on #1527 found it dominating whole packages through
// data seams: 2027 picks counted twice in team stacks, synthesized
// future-pick dollars, picks "sent" by teams that do not hold them, and a
// 2026/2027 draft-year split.  The retired per-trade moved-pick rate made a
// $1 late pick price the whole league-wide premium shift at ~1,000+ points
// per $; the pool rate fixed that defect and not the others.  It returns to
// the totals only through a new owner-approved methodology meeting the
// prerequisites recorded in issue #1529 (Calculator Ideas, NOT AUTHORIZED).
//
// stackContext = {
//   sideTeams:      string[]            // side idx → league team (null = unset)
//   leagueStacks:   { [team]: number }  // auction $ for every league team
//   moves:          [{ from, to, dollars }]  // from/to are side idx
//   boardPerDollar: number              // league pool rate; absent → withheld
// }
// Returns number[] (board-unit stack adjustment per side); zeros when
// the context is absent/insufficient.
export function computeStackAdjustments(numSides, stackContext) {
  const zeros = Array(numSides).fill(0);
  if (!stackContext) return zeros;
  const { sideTeams, leagueStacks, moves, boardPerDollar } = stackContext;
  if (!Array.isArray(sideTeams) || !leagueStacks || !Array.isArray(moves)) {
    return zeros;
  }
  if (moves.length === 0) return zeros;
  // No pool rate → no defensible conversion: the effect is withheld.
  const k = Number(boardPerDollar);
  if (!(Number.isFinite(k) && k > 0)) return zeros;

  const post = { ...leagueStacks };
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
    sumDollars += d;
  }
  if (sumDollars <= 0) return zeros;

  // Unrounded: the premium CHANGE is a difference of two effective
  // values, and whole-dollar rounding would dominate it (see
  // effectiveAuctionPowerExact).
  const before = effectiveAuctionPowerExact(leagueStacks);
  const after = effectiveAuctionPowerExact(post);
  return sideTeams.map((team) => {
    if (team == null || !(team in leagueStacks)) return 0;
    const premiumBefore = (before[team] || 0) - (leagueStacks[team] || 0);
    const premiumAfter = (after[team] || 0) - (post[team] || 0);
    return (premiumAfter - premiumBefore) * k;
  });
}

/**
 * Adjusted per-side totals for 2-team trade display.
 * Each entry is { raw, adjustment, adjusted } where
 * `adjusted = raw + adjustment` -- the whole of it.  The KTC value
 * adjustment only credits the recipient side.  The draft-capital stack
 * effect is informational only and is not an input here.
 */
export function adjustedSideTotals(sideA, sideB, valueMode, settings = null) {
  const rawA = sideTotal(sideA, valueMode, settings);
  const rawB = sideTotal(sideB, valueMode, settings);
  const { adjustment, recipientIdx } = computeValueAdjustment(sideA, sideB, valueMode, settings);
  const adjA = recipientIdx === 0 ? adjustment : 0;
  const adjB = recipientIdx === 1 ? adjustment : 0;
  // `utility` is each package's depth-discounted value: the fairness band's
  // base (fairness_bands_v2) -- read it through `fairnessBase`, never the
  // larger `adjusted`.
  const [utilA, utilB] = packageUtilities(
    [sortedSideValues(sideA, valueMode, settings), sortedSideValues(sideB, valueMode, settings)],
    [rawA + adjA, rawB + adjB],
  );
  return [
    { raw: rawA, adjustment: adjA, adjusted: rawA + adjA, utility: utilA },
    { raw: rawB, adjustment: adjB, adjusted: rawB + adjB, utility: utilB },
  ];
}

/**
 * Adjusted per-side totals for N-team trade display (N ≥ 2).
 *
 * ``sides`` are side objects (``{assets, destinations}``); a bare asset array
 * is accepted as a side with no explicit routing.  For N = 2 this is exactly
 * ``adjustedSideTotals`` (one adjusted total per side).  For N ≥ 3 each entry
 * is that team's OWN package reading (``perTeamPackageTotals``):
 * ``{raw, adjustment, adjusted, sendAdj, recvAdj, sendVA, recvVA, gap, larger,
 * band}`` with ``adjustment = sendVA`` and ``adjusted = raw + sendVA`` — the
 * package the side sends as that side values it.  It is a perspective value,
 * not a conserved flow: the same asset can carry a different VA in its
 * receiver's view, so these numbers are never summed across teams.
 *
 * @param {Array<object|object[]>} sides
 * @param {string} valueMode
 * @param {object} [settings]
 */
export function multiAdjustedSideTotals(sides, valueMode, settings = null) {
  const list = (sides || []).map((s) => (Array.isArray(s) ? { assets: s } : s || {}));
  const assets = list.map((s) => (Array.isArray(s.assets) ? s.assets : []));
  if (list.length === 2) return adjustedSideTotals(assets[0], assets[1], valueMode, settings);
  if (list.length < 2) {
    return assets.map((a) => {
      const raw = sideTotal(a, valueMode, settings);
      // `utility`: the package's depth-discounted value (fairness_bands_v2).
      const [utility] = packageUtilities([sortedSideValues(a, valueMode, settings)], [raw]);
      return { raw, adjustment: 0, adjusted: raw, utility };
    });
  }
  const values = assets.map((a) =>
    a.map((r) => Math.max(0, effectiveValue(r, valueMode, settings))),
  );
  const teams = perTeamPackageTotals(values, tradeRoutes(list));
  return teams.map((t, i) => {
    const raw = sideTotal(assets[i], valueMode, settings);
    return { raw, adjustment: t.sendVA, adjusted: raw + t.sendVA, ...t };
  });
}

/**
 * The fairness band's base for a set of side totals (fairness_bands_v2,
 * OD-F2): the largest package `utility` they carry (`fairnessBase`).  A
 * missing container, a missing side total, or a side total without a finite
 * `utility` is refused by the owner (FairnessInputError), never read as 0.
 * Every producer (`adjustedSideTotals`, `multiAdjustedSideTotals`) stamps it,
 * including on an empty side (utility 0).
 * @param {{utility: number}[]} sideTotals
 */
export function sideTotalsFairnessBase(sideTotals) {
  return fairnessBase(Array.isArray(sideTotals) ? sideTotals.map((t) => t?.utility) : sideTotals);
}

/** Gap = Side A adjusted total − Side B adjusted total (active package model). */
export function tradeGapAdjusted(sideA, sideB, valueMode, settings = null) {
  const totals = adjustedSideTotals(sideA, sideB, valueMode, settings);
  return totals[0].adjusted - totals[1].adjusted;
}

// ── Verdict ──────────────────────────────────────────────────────────────
// `largerUtility` is the larger PACKAGE UTILITY (`fairnessBase` over the
// sides' `utility`): the band is relative to it (fairness_bands_v2, OD-F2).
const VERDICT_WORDS = {
  fair: "Near even",
  slight: "Lean",
  unfair: "Strong lean",
  lopsided: "Major gap",
};

export function verdictFromGap(gap, largerUtility) {
  return VERDICT_WORDS[classifyGap(gap, largerUtility).level];
}

export function colorFromGap(gap, largerUtility) {
  if (classifyGap(gap, largerUtility).level === "fair") return "";
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

  // How far our model value sits from canonical KTC MARKET (owner
  // directive 2026-09-23): the backend-stamped ``row.ktcMarket`` block is
  // the ONE market definition — KTC's published Crowd+Trades, never a blend
  // of other sources.  ``normalizedValue`` is that price on the board's
  // 0-9999 scale (the same encoding the signal direction is computed on),
  // so the percentage and the BUY/SELL direction can never disagree.
  // Falls back to the published value, then to the pre-split Crowd-only
  // board for historical fixtures only.
  let edgePct = 0;
  const ourValue = Number(row?.values?.full);
  const market = row?.ktcMarket && typeof row.ktcMarket === "object" ? row.ktcMarket : null;
  const ktcValue =
    Number(market?.normalizedValue) ||
    Number(market?.value) ||
    Number(row?.rawSourceValues?.ktcCrowdTradesSfTep) ||
    Number(row?.canonicalSites?.ktcCrowdTradesSfTep) ||
    Number(row?.rawSourceValues?.ktcSfTep) ||
    Number(row?.canonicalSites?.ktcSfTep);
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
 * "early" | "mid" | "late" for a slot number — the frontend's ONE slot→tier
 * rule (12-team convention).  Mirrors the tier OWNER,
 * src/picks/site_pick_map.py::slot_tier_ranges(12); the literal is pinned
 * and checked against the owner by
 * tests/identity/test_pick_grammar_frontend_parity.py.
 */
export function tierForSlot(slot) {
  return slot <= 4 ? "early" : slot <= 8 ? "mid" : "late";
}

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
    return { year: slotMatch[1], round, tier: tierForSlot(slot), slot };
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

// ── Structured pick search ──────────────────────────────────────────────
//
// TC-A / UX audit P1-8: "2027 1st", "2027 Mid" and "2027 Round 1" returned
// "No matches" — the current class is priced on SLOT rows ("2027 Pick 1.05")
// and its tier rows are suppressed aliases, so plain text matching could not
// connect a round / tier / generic query to the rows that price it.  A pick
// query is parsed with the same grammar as ``parsePickToken`` and matched
// against each pick row's own shape (slot / tier / generic grade).  Nothing
// here prices anything: it only decides which existing board rows a query
// names.

/** A board pick row name → its {year, round, tier, slot}, or null. */
export function pickRowShape(name) {
  const s = String(name || "").trim();
  const generic = s.match(/^(\d{4})\s+round\s+([1-6])$/i);
  if (generic) return { year: generic[1], round: ROUND_LABELS[generic[2]], tier: null, slot: null };
  const parsed = parsePickToken(s.replace(/^(\d{4})\s+pick\s+/i, "$1 "));
  if (!parsed) return null;
  return { year: parsed.year, round: parsed.round, tier: parsed.tier || null, slot: parsed.slot ?? null };
}

/**
 * Parse a search query as a pick query, or null when it is not one.  Accepts
 * any order of: a year ("2027"), a slot ("1.05"), a tier ("early/mid/late"), a
 * round ("1st", "round 1", "rd 1", "r1"), and the word "pick(s)".  It must
 * name a round, slot or tier, plus a year unless it gives a slot or round
 * (a bare "mid" is not a pick query).  Any other word → null.
 */
export function parsePickQuery(query) {
  let q = String(query || "").toLowerCase().trim();
  if (!q) return null;
  const out = { year: null, round: null, tier: null, slot: null };
  const take = (re, fn) => {
    const m = q.match(re);
    if (!m) return;
    fn(m);
    q = q.replace(m[0], " ");
  };
  take(/\b(\d)\.(\d{1,2})\b/, (m) => {
    out.round = ROUND_LABELS[m[1]] || null;
    out.slot = parseInt(m[2], 10);
  });
  take(/\b(19|20)(\d{2})\b/, (m) => {
    out.year = `${m[1]}${m[2]}`;
  });
  take(/\b(early|mid|late)\b/, (m) => {
    out.tier = m[1];
  });
  take(/\b([1-6])(st|nd|rd|th)\b/, (m) => {
    out.round = ROUND_LABELS[m[1]];
  });
  take(/\b(?:round|rd|r)\s*([1-6])\b/, (m) => {
    out.round = ROUND_LABELS[m[1]];
  });
  q = q.replace(/\bpicks?\b/g, " ");
  if (q.trim()) return null;
  if (!out.round && !out.slot && !out.tier) return null;
  if (!out.year && !out.round && !out.slot) return null;
  return out;
}

/** Does a pick row (by name) satisfy a parsed pick query? */
export function pickRowMatchesQuery(name, pq) {
  if (!pq) return false;
  const shape = pickRowShape(name);
  if (!shape) return false;
  if (pq.year && shape.year !== pq.year) return false;
  if (pq.round && shape.round !== pq.round) return false;
  if (pq.slot != null) {
    // An exact slot row, or -- when the query names its year -- the tier
    // row that slot belongs to (future classes are priced at tier grade).
    // Never a generic row.
    if (shape.slot != null) return shape.slot === pq.slot;
    if (!pq.year || !shape.tier || shape.tier !== tierForSlot(pq.slot)) return false;
  }
  if (pq.tier) {
    const rowTier = shape.slot != null ? tierForSlot(shape.slot) : shape.tier;
    if (rowTier !== pq.tier) return false;
  }
  return true;
}

// Structured pick matches rank with the loosest text matches (tier 3).
const PICK_QUERY_MATCH_TIER = 3;

/**
 * Board rows matching a search query, most relevant first.
 *
 * Relevance is ``searchMatchTier`` (exact > prefix > substring > every
 * word present), so "2027 Late 1st" returns exactly that row first; within
 * a tier, rows sort by blended source rank — the most relevant dynasty
 * assets first, the KTC trade-calculator UX.
 *
 * Nothing is excluded for being in the trade: every asset is repeatable
 * (owner decision 2026-10-03), so a row already in the trade stays
 * searchable.  There is deliberately no exclusion parameter.
 *
 * Extracted from `/trade`'s `searchAssets` so the asset-eligibility
 * rule is one testable function rather than an inline predicate
 * repeated beside three other copies of itself.
 */
export function searchTradeAssets(rows, query, limit = 5) {
  if (!String(query || "").trim()) return [];
  const pq = parsePickQuery(query);
  const scored = [];
  for (const r of rows || []) {
    if (!r || !isTradeableBoardRow(r)) continue;
    let tier = searchMatchTier(r.name, query);
    if (tier < 0 && pq && r.assetClass === "pick" && pickRowMatchesQuery(r.name, pq)) {
      tier = PICK_QUERY_MATCH_TIER;
    }
    if (tier >= 0) scored.push({ r, tier });
  }
  scored.sort(
    (a, b) =>
      a.tier - b.tier ||
      (a.r.blendedSourceRank ?? Infinity) - (b.r.blendedSourceRank ?? Infinity),
  );
  return scored.slice(0, limit).map((x) => x.r);
}

// Per-group limits for the calculator search (see ``searchCalculatorAssets``).
export const SEARCH_BOARD_LIMIT = 8;
export const SEARCH_OWNED_LIMIT = 5;

/**
 * The calculator's search: board rows FIRST, then the side's owned picks,
 * each group with its OWN limit — the single composition both search
 * boxes on /trade use.
 *
 *   1. board rows (players, Early/Mid/Late tier picks for every active
 *      future year, current-year slot picks) via ``searchTradeAssets`` —
 *      exact-query relevance first, nothing hidden for being in the trade;
 *   2. ``ownedEntries`` (the side's team's owned picks, each carrying its
 *      canonical ``assetId``) via ``searchPickEntries``.
 *
 * Owned picks used to come first and share one short list, so on a phone
 * with the keyboard up a team's own "2027 1st / 2nd" rows were all that was
 * visible and the 2027 Early/Mid/Late market references — present, priced
 * and unsuppressed on the board — read as missing.  Market references and
 * owned picks are different assets and both stay addable.  Values are the
 * board rows' own canonical values; nothing here prices anything.
 */
export function searchCalculatorAssets(
  rows,
  query,
  ownedEntries = [],
  { boardLimit = SEARCH_BOARD_LIMIT, ownedLimit = SEARCH_OWNED_LIMIT } = {},
) {
  const board = searchTradeAssets(rows, query, boardLimit);
  const pq = parsePickQuery(query);
  const owned = searchPickEntries(
    (ownedEntries || []).filter((e) => e && e.assetId),
    query,
    ownedLimit,
    pq ? (e) => pickRowMatchesQuery(e.name, pq) : null,
  );
  return [...board, ...owned];
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

/**
 * The row a trade entry should be priced on.
 *
 * A suppressed generic-tier pick row ("2027 Mid 1st" once 2027 is the
 * current class) carries no value: the board aliases it to its slot row
 * ("2027 Pick 1.06") through ``pickAliases``.  Search already hides those
 * rows, but every path that turns a NAME back into a row — a saved
 * workspace, a share link, a KTC import, a trade imported from history —
 * matched the name exactly and landed on the unpriced alias.  A trade saved
 * while 2027 was still a future class then rehydrated as "—" / unpriced
 * after the class roll.
 *
 * Follows the alias (``resolvePickRow``); an owned pick keeps its canonical
 * ``assetId`` and label.  When nothing resolves the entry is returned
 * unchanged — still visible and labelled unpriced, never dropped.
 */
export function canonicalTradeEntry(entry, rowLookup, pickAliases) {
  if (!entry || !isSuppressedGenericPickRow(entry)) return entry;
  const target = resolvePickRow(entry.name, rowLookup, pickAliases);
  if (!target || target === entry) return entry;
  if (!entry.assetId) return target;
  return { ...target, assetId: entry.assetId, assetLabel: entry.assetLabel || entry.name };
}

/**
 * ``sides`` with every suppressed-alias entry re-anchored to its priced row
 * (``canonicalTradeEntry``).  Destinations keyed by the old entry key move
 * with the entry.  Returns the SAME array when nothing changed, so a React
 * effect can call it on every board refresh without looping.
 */
export function reanchorSuppressedPickEntries(sides, rowLookup, pickAliases) {
  let changed = false;
  const next = (sides || []).map((side) => {
    const assets = side?.assets || [];
    if (!assets.some(isSuppressedGenericPickRow)) return side;
    const destinations = { ...(side.destinations || {}) };
    const mapped = assets.map((entry) => {
      const fixed = canonicalTradeEntry(entry, rowLookup, pickAliases);
      if (fixed !== entry) {
        changed = true;
        const oldKey = tradeEntryKey(entry);
        const newKey = tradeEntryKey(fixed);
        if (oldKey in destinations && oldKey !== newKey) {
          if (!(newKey in destinations)) destinations[newKey] = destinations[oldKey];
          delete destinations[oldKey];
        }
      }
      return fixed;
    });
    return { ...side, assets: mapped, destinations };
  });
  return changed ? next : sides;
}

// ── Trade Side Helpers ───────────────────────────────────────────────────
// Identity and quantity rules live in ./trade-assets.js.  Every asset is
// repeatable in the calculator (owner decision 2026-10-03, superseding
// T-NEW-02's uniqueness rule): an add is never refused, and removal takes
// ONE copy.
export function addAssetToSide(side, row) {
  if (!row) return side;
  if (!canAddEntry([side], row)) return side;
  return [...side, row];
}

export function removeAssetFromSide(side, key) {
  return removeOneEntry(side, key);
}

export function isAssetInTrade(sideA, sideB, key) {
  return [...sideA, ...sideB].some((r) => tradeEntryKey(r) === key);
}

// ── Balancing Suggestions ────────────────────────────────────────────────
/**
 * Find add-ons that actually close the gap the user is being shown.
 *
 * ──────────────────────────────────────────────────────────────────────
 * Why this simulates instead of matching a value (defect #800)
 * ──────────────────────────────────────────────────────────────────────
 * The gap on screen is the ADJUSTED gap — ``raw + Value Adjustment``
 * (the draft-capital stack effect is informational only), from ``adjustedSideTotals`` / ``tradeImbalance``.  This
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
 * @param {object[]} sides       — the two side objects (``{ assets }``); a
 *        3+-team trade returns ``[]`` (no balancing objective is approved)
 * @param {number} behindIdx     — index of the side that must sweeten
 * @param {object[]} rosterRows  — candidate rows to choose from
 * @param {string} valueMode
 * @param {object}  [opts]
 * @param {object}  [opts.settings]
 * @param {number}  [opts.maxResults=5]
 * @param {boolean} [opts.combos=false] — TC-B / TCM-F03: when NO single
 *        candidate lands inside the fair band, also try every PAIR of the
 *        best ``BALANCER_PAIR_POOL`` singles, each pair simulated through the
 *        same ``tradeImbalance`` path (never the sum of two raw values), and
 *        lead with up to ``BALANCER_MAX_PAIRS`` pairs that land closer than
 *        the best single.  A pair is ``{isCombo: true, entries: [a, b]}``.
 * @returns {{name: string, pos: string, value: number, gapBefore: number|null,
 *            gapAfter: number|null, imbalanceBefore: number,
 *            imbalanceAfter: number}[]}
 *        Sorted best-first.  Empty when the trade is already near even or
 *        nothing in the pool improves it.
 */
export function findBalancers(sides, behindIdx, rosterRows, valueMode, opts = {}) {
  const { settings = null, maxResults = 5, combos = false } = opts;
  if (!Array.isArray(sides) || sides.length < 2) return [];
  // Disabled for 3+ teams (spec docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §5.1
  // R10d, SD-13): adding an asset from team b to team d moves only gap_b and
  // gap_d, so a 3+-team balancing objective is an undecided methodology
  // choice.  The page says so ("Balancing suggestions aren't available …").
  if (sides.length > 2) return [];
  if (!Number.isInteger(behindIdx) || behindIdx < 0 || behindIdx >= sides.length) {
    return [];
  }

  const before = tradeImbalance(sides, valueMode, settings);
  // Inside the fair band (the ONE fairness-band owner): nothing to balance.
  if (classifyGap(before.imbalance, before.largerUtility).level === "fair") return [];

  const withCandidates = (rows) =>
    tradeImbalance(
      sides.map((side, i) =>
        i === behindIdx
          ? {
              ...side,
              assets: [...(Array.isArray(side?.assets) ? side.assets : []), ...rows],
            }
          : side,
      ),
      valueMode,
      settings,
    );
  const withCandidate = (row) => withCandidates([row]);

  const scored = [];
  // Candidates are scored per IDENTITY, not per label: two distinct owned
  // picks that both read "2027 Mid 1st" are two candidates, while the same
  // market row offered twice in the pool is one suggestion.
  const scoredKeys = new Set();
  for (const row of rosterRows || []) {
    const key = tradeEntryKey(row);
    if (!key || scoredKeys.has(key)) continue;
    scoredKeys.add(key);
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
      key,
      label: row.assetLabel || row.name,
      entry: row,
      pos: row.pos,
      value,
      gapBefore: before.gap,
      gapAfter: after.gap,
      imbalanceBefore: before.imbalance,
      imbalanceAfter: after.imbalance,
      largerUtilityAfter: after.largerUtility,
    });
  }

  const byLanding = (a, b) =>
    a.imbalanceAfter - b.imbalanceAfter ||
    a.name.localeCompare(b.name) ||
    a.key.localeCompare(b.key);
  scored.sort(byLanding);
  const singles = scored.slice(0, maxResults);
  if (!combos || !scored.length) return singles;
  const best = scored[0];
  if (classifyGap(best.imbalanceAfter, best.largerUtilityAfter).level === "fair") return singles;

  // No single asset closes the gap: try pairs of the best singles.  Each pair
  // is re-simulated as a whole -- two pieces change the package count, so
  // their effect is NOT the sum of their single effects (defect #800).
  const pool = scored.slice(0, BALANCER_PAIR_POOL);
  const pairs = [];
  for (let i = 0; i < pool.length; i += 1) {
    for (let j = i + 1; j < pool.length; j += 1) {
      const a = pool[i];
      const b = pool[j];
      const after = withCandidates([a.entry, b.entry]);
      if (!(after.imbalance < best.imbalanceAfter)) continue;
      pairs.push({
        isCombo: true,
        entries: [a.entry, b.entry],
        name: `${a.name} + ${b.name}`,
        key: `${a.key}|${b.key}`,
        label: `${a.label} + ${b.label}`,
        pos: `${a.pos} + ${b.pos}`,
        value: a.value + b.value,
        gapBefore: before.gap,
        gapAfter: after.gap,
        imbalanceBefore: before.imbalance,
        imbalanceAfter: after.imbalance,
        largerUtilityAfter: after.largerUtility,
      });
    }
  }
  pairs.sort(byLanding);
  return [...pairs.slice(0, BALANCER_MAX_PAIRS), ...singles];
}

/**
 * Pair search bounds for ``findBalancers({combos: true})`` (TC-B / TCM-F03).
 * Declared PRIORs, not fitted: the best 8 singles give 28 pair simulations
 * (bounded, one trade at a time), and at most 2 pairs are offered so the
 * single-asset suggestions stay visible beside them.
 */
export const BALANCER_PAIR_POOL = 8;
export const BALANCER_MAX_PAIRS = 2;

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
 * Load an imported trade (KTC URL, screenshot) into sides A and B — the ONE
 * bulk-load rule both importers share, so they cannot drift apart.
 *
 *   mode "replace" — sides A and B take exactly the imported entries; any
 *                    3rd+ side is left untouched.  Destinations are rebuilt
 *                    from scratch: in a 3+-team trade each imported entry is
 *                    seeded with ``defaultDestination``; a 2-team trade keeps
 *                    an empty map (``computeSideFlows`` routes implicitly).
 *                    Old routing for entries no longer present is dropped.
 *   mode "add"     — the imported entries are APPENDED to sides A and B.
 *                    Existing routing is kept; a newly seen line in a 3+-team
 *                    trade gets the default, exactly as ``addToSide`` does.
 *
 * Nothing is deduped, in either mode: an asset imported twice is two copies,
 * and adding an asset already in the trade adds another copy (owner decision
 * 2026-10-03, lib/trade-assets).  Entries are the caller's board rows,
 * unchanged — nothing here values anything.  Pure: returns a new array; the
 * input sides are not mutated and untouched sides keep their identity.
 *
 * @param {Array} sides - current trade sides (``createSide`` shape)
 * @param {[Array, Array]} importedSides - entries for side A and side B
 * @param {"replace"|"add"} mode
 */
export function applyImportedSides(sides, importedSides, mode = "replace") {
  const list = Array.isArray(sides) ? sides : [];
  const n = list.length;
  const add = mode === "add";
  return list.map((s, i) => {
    if (i !== 0 && i !== 1) return s; // leave 3rd+ sides alone
    const incoming = Array.isArray(importedSides?.[i]) ? importedSides[i] : [];
    const assets = add ? [...(s.assets || []), ...incoming] : [...incoming];
    const destinations = add ? { ...(s.destinations || {}) } : {};
    if (n > 2) {
      for (const asset of incoming) {
        const key = tradeEntryKey(asset);
        if (destinations[key] == null)
          destinations[key] = defaultDestination(i, n);
      }
    }
    return { ...s, assets, destinations };
  });
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
        const raw = destinations[tradeEntryKey(asset)];
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
 * Per-side package reading for a routed trade of ANY side count — the
 * calculator's PRELIMINARY indicator (the final multi-team result comes from
 * ``POST /api/trade/analyze-multi``).
 *
 * Each side i is read in its OWN perspective (``perTeamPackageTotals``, spec
 * docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §5.1): G_i = what it sends, R_i =
 * everything routed to it.  Returns, per side and in order:
 *
 *   given / received  ``sendAdj`` / ``recvAdj`` — the adjusted package it
 *                     sends and the one it receives, as THAT team values them
 *   net               ``recvAdj − sendAdj`` — the team's own adjusted gap
 *   adjustment        ``sendVA``
 *   rawGiven / rawReceived  RAW routed flows, the only conserved quantities
 *                     (Σ rawGiven === Σ rawReceived)
 *   sendAdj, recvAdj, sendVA, recvVA, gap, larger, utility, receivedUtility,
 *   largerUtility, band  (perTeamPackageTotals; ``utility`` is the package
 *   utility of what the side SENDS — every flow carries it, fairness_bands_v2)
 *
 * ``given`` / ``received`` / ``net`` are perspective values: an asset can
 * carry a different VA in its receiver's view than in its sender's, so they
 * are never added across teams and never drawn as routed flows.  For N = 2
 * every number is what it was before the per-team rule (the two teams'
 * readings are mirror images), and ``nets[1] === tradeGapAdjusted(A, B)``.
 *
 * Routing: two sides route implicitly to each other; three or more read
 * ``side.destinations`` (``tradeRoutes``, with the visible default seed for a
 * missing or invalid entry).
 *
 * @param {object[]} sides  - array of side objects
 * @param {string} valueMode
 * @param {object} [settings]
 */
export function computeSideFlows(sides, valueMode, settings = null) {
  const n = Array.isArray(sides) ? sides.length : 0;
  if (n < 2) {
    return Array.from({ length: n }, () => ({
      given: 0,
      received: 0,
      net: 0,
      adjustment: 0,
      rawGiven: 0,
      rawReceived: 0,
      utility: 0,
      receivedUtility: 0,
      largerUtility: 0,
    }));
  }
  const values = sides.map((side) =>
    (Array.isArray(side?.assets) ? side.assets : []).map((a) =>
      Math.max(0, effectiveValue(a, valueMode, settings)),
    ),
  );
  return perTeamPackageTotals(values, tradeRoutes(sides)).map((t) => ({
    given: t.sendAdj,
    received: t.recvAdj,
    net: t.gap,
    adjustment: t.sendVA,
    ...t,
  }));
}

const BAND_SEVERITY = { fair: 0, slight: 1, unfair: 2, lopsided: 3 };

/**
 * The team with the worst package band in a 3+-team trade (spec §5.1 R10c):
 * lopsided > unfair > slight > fair, ties broken by the larger relative gap,
 * then the lower side index.  A flow whose gap is not a finite number is
 * INDETERMINATE and wins outright (``level: null``) — an unknown is never
 * read as fair.  Flows are ``computeSideFlows`` entries: ``net`` and the band
 * base ``teamFairnessBase(flow)`` — the team's larger PACKAGE UTILITY
 * (fairness_bands_v2, OD-F2).  A flow without a finite ``utility`` /
 * ``receivedUtility`` is INDETERMINATE.  ``null`` for an empty list.
 */
export function worstTeamBand(flows) {
  const list = Array.isArray(flows) ? flows : [];
  let worst = null;
  list.forEach((f, index) => {
    const gap = Number(f?.net);
    const largerUtility = teamFairnessBase(f);
    if (!Number.isFinite(gap) || largerUtility == null) {
      if (!worst || worst.level != null)
        worst = { index, level: null, relPct: null, gap: null, largerUtility: null };
      return;
    }
    if (worst && worst.level == null) return;
    const band = classifyGap(gap, largerUtility);
    // Tie-break only (the band already decided severity); an empty pairing
    // (base 0) can only be in the fair band, where every rel ties at 0.
    const rel = largerUtility > 0 ? Math.abs(gap) / largerUtility : 0;
    const cand = {
      index,
      level: band.level,
      relPct: band.relativePct,
      gap,
      largerUtility,
      rel,
    };
    if (
      !worst ||
      BAND_SEVERITY[cand.level] > BAND_SEVERITY[worst.level] ||
      (BAND_SEVERITY[cand.level] === BAND_SEVERITY[worst.level] && cand.rel > worst.rel)
    ) {
      worst = cand;
    }
  });
  if (worst && "rel" in worst) delete worst.rel;
  return worst;
}

/**
 * The package imbalance of a trade, for ANY side count.
 *
 * N = 2: ``{ imbalance, nets, gap, largerUtility }`` — the signed gap (side A
 * minus side B), its magnitude, the per-side nets and the larger PACKAGE
 * UTILITY the band is relative to (fairness_bands_v2, OD-F2: the owner's
 * ``fairnessBase`` over each side's ``utility``).  ``nets[1] ===
 * tradeGapAdjusted(A, B)`` holds exactly, and a test pins it.
 *
 * N ≥ 3 (spec docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §5.1 R10c):
 * ``{ perTeam: [{gap, larger, largerUtility, level}], worst: {index, level,
 * relPct, largerUtility}, largerUtility, nets, gap: null }``.  Each team is
 * graded on its OWN gap against its OWN larger package utility
 * (``teamFairnessBase``); ``worst`` (``worstTeamBand``) is the only scalar and
 * the top-level ``largerUtility`` is its base (``null`` when it is unknown).  There is no
 * "max(net) − min(net)": per-team gaps are perspective quantities and do
 * not subtract across teams.
 *
 * The draft-capital stack effect is not an input (informational only, owner
 * directive 2026-09-29).
 */
export function tradeImbalance(sides, valueMode, settings = null) {
  const n = Array.isArray(sides) ? sides.length : 0;
  // No sides is an empty pairing: base 0 (the owner's `fairnessBase([])`).
  if (n < 2) return { imbalance: 0, nets: [], gap: null, largerUtility: 0 };
  const flows = computeSideFlows(sides, valueMode, settings);
  const nets = flows.map((f) => f.net);
  if (n === 2) {
    // The base the fairness band is relative to (fairness_bands_v2, OD-F2): the
    // larger PACKAGE UTILITY of the two packages, max(U_A, U_B) --
    // byte-identical to the larger adjusted side on a 1-for-1.
    const largerUtility = fairnessBase(flows.map((f) => f.utility));
    const gap = tradeGapAdjusted(
      Array.isArray(sides[0]?.assets) ? sides[0].assets : [],
      Array.isArray(sides[1]?.assets) ? sides[1].assets : [],
      valueMode,
      settings,
    );
    return { imbalance: Math.abs(gap), nets, gap, largerUtility };
  }
  const worst = worstTeamBand(flows);
  return {
    perTeam: flows.map((f) => ({
      gap: f.gap,
      larger: f.larger,
      largerUtility: f.largerUtility ?? null,
      level: f.band?.level ?? null,
    })),
    worst: worst
      ? {
          index: worst.index,
          level: worst.level,
          relPct: worst.relPct,
          largerUtility: worst.largerUtility,
        }
      : null,
    largerUtility: worst ? worst.largerUtility : null,
    nets,
    gap: null,
  };
}

/**
 * The meter badge for a package gap -- the Immediate Result, package only.
 * Bands from the ONE fairness-band owner (./fairness-bands.js): relative to
 * the larger PACKAGE UTILITY, with an absolute minimum (fairness_bands_v2; it
 * replaced v1's larger adjusted side, which replaced the absolute 350 / 900 /
 * 1800).  It labels the package gap; the trade DECISION is the backend's
 * (POST /api/trade/analyze).
 *
 * `percentText` is THE percentage to print beside the badge: the band's own
 * relative gap (|gap| / larger package utility), floored to one decimal and
 * printed without a trailing ".0".  Flooring the UNROUNDED value keeps it on
 * the same side of every cut as the badge (cuts 3.5 / 9 / 18 are exact at one
 * decimal and IEEE multiplication is monotone), so SLIGHT EDGE never sits
 * beside "3%" and FAIR (on the relative test) never beside "3.5%".  A gap
 * under ABSOLUTE_MINIMUM is FAIR whatever its percentage.  `null` when the
 * base is 0.  Never print `percentageGap` (the adjusted-side basis) beside a
 * badge.
 * @param {number} gap - package gap (sign ignored)
 * @param {number} largerUtility - larger package utility (`fairnessBase`)
 * @returns {{ label: string, level: 'fair'|'slight'|'unfair'|'lopsided', relativePct: number|null, percentText: string|null }}
 */
export function meterVerdict(gap, largerUtility) {
  const band = classifyGap(gap, largerUtility);
  const rel = relativeGapPct(gap, largerUtility);
  return {
    label: FAIRNESS_LABELS[band.level],
    level: band.level,
    relativePct: band.relativePct,
    percentText: rel == null ? null : formatBandPct(rel),
  };
}

/** One decimal, floored (see meterVerdict); "20" not "20.0". */
function formatBandPct(rel) {
  const tenths = Math.floor(rel * 10);
  return tenths % 10 === 0 ? String(tenths / 10) : (tenths / 10).toFixed(1);
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

/**
 * The 3+-team package reading the multi-team meter renders, as ONE helper so
 * the meter and the persistent summary bar cannot drift (TC-D2).  PRELIMINARY:
 * the final per-team result comes from ``POST /api/trade/analyze-multi``.
 *
 * Per-team rule (spec §5.1, fairness_bands_v2 OD-F2): each side's ``net`` is
 * its OWN adjusted gap and its band is ``meterVerdict(net,
 * teamFairnessBase(flow))`` — the team's own larger PACKAGE UTILITY (what it
 * sends vs what it receives), never the largest package anyone sends and
 * never an adjusted side.  The headline is the worst team (``worstTeamBand``).
 * Package-only; never a decision.
 *
 * Returns ``{ nets, perTeam, worstIndex, worst, largerUtility, verdict,
 * withheld }``: ``worst`` is the worst team's |gap|, ``largerUtility`` its
 * band base, and ``verdict`` its meter badge — or ``{label: "Indeterminate",
 * level: null}`` when a team's gap or package utility is not a number
 * (unknown, never fair).  A team that is not withheld but states no finite
 * ``utility`` / ``receivedUtility`` is REFUSED: this throws
 * FairnessInputError, which the meter renders as NO VERDICT.
 *
 * ``withheldBySide`` (``withheldAssetsBySide``, optional): a team whose part
 * of the trade carries a WITHHELD value (quarantined / stale) has no gap and
 * no band — its ``net`` is ``null`` (never the sum the withheld number is
 * in, never 0) and it is INDETERMINATE for the headline, whose verdict then
 * reads ``{label: "Withheld", level: null}``.  ``withheld[i]`` says which.
 * @param {{given:number, received:number, net:number, utility:number, receivedUtility:number}[]} flows
 * @param {object[][]} [withheldBySide]
 */
export function multiTeamNetSummary(flows, withheldBySide = null) {
  const raw = Array.isArray(flows) ? flows : [];
  const withheld = raw.map((_, i) =>
    Array.isArray(withheldBySide?.[i]) ? withheldBySide[i].length > 0 : false,
  );
  // A withheld team's gap is not a number: it enters the band reading as
  // indeterminate (``worstTeamBand``), exactly like any other unknown gap.
  const list = raw.map((f, i) => (withheld[i] ? { ...f, net: Number.NaN } : f));
  // Every team that is not withheld must state BOTH package utilities
  // (computeSideFlows stamps them, 0 for an empty package): a flow without
  // one is refused by the owner (FairnessInputError -- the meter renders NO
  // VERDICT), never dropped from the base and never read as 0.
  list.forEach((f, i) => {
    if (!withheld[i]) fairnessBase([f?.utility, f?.receivedUtility]);
  });
  // A net that is not a number stays unknown (null), never a fabricated 0.
  const nets = list.map((f) => {
    const n = Number(f?.net);
    return Number.isFinite(n) ? n : null;
  });
  const perTeam = list.map((f, i) => {
    const largerUtility = teamFairnessBase(f);
    return nets[i] == null || largerUtility == null ? null : meterVerdict(nets[i], largerUtility);
  });
  const unknown = (label) => ({ label, level: null, relativePct: null, percentText: null });
  const w = worstTeamBand(list);
  if (!w) {
    return {
      nets,
      perTeam,
      worstIndex: null,
      worst: 0,
      largerUtility: 0,
      verdict: meterVerdict(0, 0),
      withheld,
    };
  }
  if (w.level == null) {
    return {
      nets,
      perTeam,
      worstIndex: w.index,
      worst: null,
      largerUtility: null,
      verdict: withheld.some(Boolean) ? unknown("Withheld") : unknown("Indeterminate"),
      withheld,
    };
  }
  return {
    nets,
    perTeam,
    worstIndex: w.index,
    worst: Math.abs(w.gap),
    largerUtility: w.largerUtility,
    verdict: meterVerdict(w.gap, w.largerUtility),
    withheld,
  };
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
      // One item per COPY (Jefferson x4 is four items), and an owned pick
      // keeps its canonical id — see ./trade-assets.js.  Players and market
      // picks stay bare names, so this is byte-identical to the
      // pre-T-NEW-02 format for any trade that has no owned pick.
      const assets = (s.assets || []).map(serializeEntry).filter((x) => x != null);
      const destSource = s.destinations || {};
      const destinations = {};
      for (const entry of s.assets || []) {
        const key = tradeEntryKey(entry);
        if (Object.prototype.hasOwnProperty.call(destSource, key)) {
          destinations[key] = destSource[key];
        }
      }
      return { label: s.label, assets, destinations };
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
    // Canonical only (TC-A P0-4): the legacy composite (``values.raw``) is
    // never exported as the trade value, whatever mode a caller passes, and
    // a missing canonical value is a blank cell, never the composite.
    void valueMode;
    const v = vals.full;
    return v == null ? "" : Math.round(Number(v));
  };
  const basis = valueBasis || "unspecified";
  // One line per COPY, so any asset x2 exports as two lines and the
  // column sums agree with the calculator.  ``Asset ID`` carries an owned
  // pick's canonical identity, which the label alone cannot: two distinct
  // owned picks may both read "2027 Mid 1st" (T-NEW-02).
  const lines = ["Side,Asset,Position,Team,Value,Value Basis,Asset ID"];
  for (const s of sides || []) {
    for (const r of s.assets || []) {
      lines.push(
        [s.label, r.name, r.pos || "", r.team || "", pickVal(r), basis, r.assetId || ""]
          .map(esc)
          .join(","),
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
    // Items are bare names (every payload ever written, and players /
    // market picks now) or ``{name, assetId, label}`` for an owned pick.
    // Repeated items are copies and ALL survive, for every kind of asset
    // and on both sides at once — calculator quantities are hypothetical,
    // not inventory (owner decision 2026-10-03).
    const entryLists = parsed.sides.map((s) =>
      Array.isArray(s?.assets)
        ? s.assets.map((item) => deserializeEntry(item, rowByName)).filter(Boolean)
        : [],
    );
    const sides = parsed.sides.map((s, i) => {
      const assets = entryLists[i];
      const destSource =
        s.destinations && typeof s.destinations === "object" ? s.destinations : {};
      const destinations = {};
      for (const asset of assets) {
        const key = tradeEntryKey(asset);
        const raw = destSource[key];
        const parsedIdx = Number(raw);
        if (
          Number.isInteger(parsedIdx) &&
          parsedIdx >= 0 &&
          parsedIdx < sideCount &&
          parsedIdx !== i
        ) {
          destinations[key] = parsedIdx;
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

// ``sideA`` / ``sideB`` are kept for call-site stability.  Nothing already
// in the trade is hidden: every asset stays pickable after its first copy
// (owner decision 2026-10-03).
export function filterPickerRows(rows, _sideA, _sideB, query, filter) {
  const q = query.trim().toLowerCase();
  let list = rows.filter(Boolean);
  if (filter !== "all") list = list.filter((r) => r.assetClass === filter);
  if (q) list = list.filter((r) => r.name.toLowerCase().includes(q));
  return list.slice(0, 80);
}
