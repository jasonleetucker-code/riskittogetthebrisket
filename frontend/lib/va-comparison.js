/**
 * Value Adjustment comparison — Chase Upside's ACTIVE package model beside the
 * KTC adjustment method, over the SAME canonical per-asset values (owner
 * directive 2026-10-19, part 2).
 *
 * What this is:
 *   ONE helper that runs the canonical package-model dispatch
 *   (`trade-logic.js::valueAdjustmentFromSideArrays` → `packageAdjustPair`)
 *   twice — once per registered model — on the same per-side value arrays,
 *   and reports each run on its own: raw totals, the adjustment per side, the
 *   adjusted totals, the gap, which side has more adjusted value, and the
 *   headline's own fairness band word for that gap.
 *
 * What it never does:
 *   * duplicate either model's math (both go through the one dispatch);
 *   * blend, add, average or chain the two adjustments — they are two
 *     alternative whole-package evaluations of the same packages;
 *   * change an asset's value (it reads the values it is given);
 *   * decide anything.  Chase Upside's model is the active, authoritative one
 *     (`ACTIVE_PACKAGE_MODEL_ID`, geom_q078_v1); the KTC method is a read-only
 *     analytical comparator.  No verdict, recommendation or tally reads this.
 *
 * "KTC adjustment method" means KeepTradeCut's published package-adjustment
 * FORMULA (the April 2026 port, `ktc_2026_04`) applied to Chase Upside's
 * values.  It is not KTC's own player values and not KTC's calculator output.
 *
 * Missing is never zero: a piece with no value makes the comparison
 * UNAVAILABLE (named, counted), never a 0 inside a total.  A 3+-team trade is
 * MULTI_TEAM: both models are two-side models, the active one reaches 3+ teams
 * only through a structural extension, and the comparator is not extended.
 */

import { classifyGap } from "./fairness-bands.js";
import {
  ACTIVE_PACKAGE_MODEL_ID,
  PACKAGE_MODEL_IDS,
  packageModelReceipt,
  valueAdjustmentFromSideArrays,
} from "./trade-logic.js";

/** The read-only comparator model. */
export const COMPARATOR_PACKAGE_MODEL_ID = PACKAGE_MODEL_IDS.KTC_2026_04;

/** Plain-English method names. Never "KTC" alone: KTC-native values are a different thing. */
export const ACTIVE_METHOD_LABEL = "Chase Upside adjustment";
export const COMPARATOR_METHOD_LABEL = "KTC adjustment method";

export const VA_COMPARISON_STATUS = Object.freeze({
  /** Both models evaluated. */
  OK: "ok",
  /** A side holds no asset: nothing to compare. */
  EMPTY: "empty",
  /** A piece has no value: unknown, not 0 — no comparison. */
  UNAVAILABLE: "unavailable",
  /** 3+ teams: the comparator is a two-side model and is not extended. */
  MULTI_TEAM: "multi_team",
  /** The active model IS the comparator (a rollback): nothing to compare. */
  SAME_MODEL: "same_model",
});

function positive(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

const sum = (values) => values.reduce((s, v) => s + v, 0);

/**
 * One model's evaluation of a two-side trade.  `values` holds positive
 * numbers only (the caller has already refused missing ones).
 *
 *   gap           adjusted A − adjusted B
 *   moreValueIdx  the side with more adjusted value (null when exactly equal)
 *   leaderIdx     the same, but null inside the headline's fair band
 *                 (`fairness-bands.js::classifyGap`, the ONE band owner)
 *   relativeGapPct |gap| as a % of the larger adjusted side — a neutral
 *                 measure, deliberately NOT the headline's verdict words, so
 *                 the comparator column never reads like a second verdict
 *   nearEven      the gap is inside that fair band
 */
export function evaluatePackageModel(values, modelId) {
  const receipt = packageModelReceipt(modelId);
  const adjustments = valueAdjustmentFromSideArrays(values, { modelId }).map(Number);
  const rawTotals = values.map(sum);
  const adjustedTotals = rawTotals.map((t, i) => t + adjustments[i]);
  const gap = adjustedTotals[0] - adjustedTotals[1];
  const larger = Math.max(...adjustedTotals);
  const band = classifyGap(gap, larger);
  const moreValueIdx = gap > 0 ? 0 : gap < 0 ? 1 : null;
  return {
    modelId: receipt.id,
    receipt,
    role: receipt.id === ACTIVE_PACKAGE_MODEL_ID ? "active" : "comparator",
    label: receipt.id === ACTIVE_PACKAGE_MODEL_ID ? ACTIVE_METHOD_LABEL : COMPARATOR_METHOD_LABEL,
    rawTotals,
    adjustments,
    adjustedTotals,
    gap,
    moreValueIdx,
    leaderIdx: band.level === "fair" ? null : moreValueIdx,
    bandLevel: band.level,
    nearEven: band.level === "fair",
    relativeGapPct: band.relativePct,
    recipientIdx: adjustments[0] > 0 ? 0 : adjustments[1] > 0 ? 1 : null,
  };
}

/**
 * Compare the two methods on per-side canonical value arrays.
 *
 * @param {Array<Array<number|null>>} sideValues  one array per side; a
 *   null / non-positive entry is a piece with no value (unpriced).
 * @returns {{status, sideCount, unpriced, active?, comparator?, agree?,
 *   moreValueAgrees?, nearEvenSplit?, noAdjustment?, oneForOne?}}
 *
 *   agree           the two methods name the same leader, judged with the
 *                   headline's fair band (both "near even" counts as the same)
 *   moreValueAgrees the two methods put the SAME side ahead on the raw sign of
 *                   the gap (the directive's "which side has more adjusted
 *                   value"), fair band or not
 *   nearEvenSplit   both are near even, yet each puts a DIFFERENT side
 *                   slightly ahead — reported in words, never as agreement
 */
export function compareValueAdjustments(sideValues) {
  const sides = Array.isArray(sideValues) ? sideValues.map((s) => (Array.isArray(s) ? s : [])) : [];
  const sideCount = sides.length;
  const base = { sideCount, unpriced: [] };
  if (sideCount < 2 || sides.some((s) => s.length === 0)) {
    return { ...base, status: VA_COMPARISON_STATUS.EMPTY };
  }
  if (sideCount > 2) return { ...base, status: VA_COMPARISON_STATUS.MULTI_TEAM };
  const unpriced = [];
  sides.forEach((s, side) =>
    s.forEach((v, index) => {
      if (positive(v) == null) unpriced.push({ side, index });
    }),
  );
  if (unpriced.length) return { ...base, unpriced, status: VA_COMPARISON_STATUS.UNAVAILABLE };
  if (ACTIVE_PACKAGE_MODEL_ID === COMPARATOR_PACKAGE_MODEL_ID) {
    return { ...base, status: VA_COMPARISON_STATUS.SAME_MODEL };
  }
  const values = sides.map((s) => s.map(Number));
  const active = evaluatePackageModel(values, ACTIVE_PACKAGE_MODEL_ID);
  const comparator = evaluatePackageModel(values, COMPARATOR_PACKAGE_MODEL_ID);
  return {
    ...base,
    status: VA_COMPARISON_STATUS.OK,
    active,
    comparator,
    agree: active.leaderIdx === comparator.leaderIdx,
    moreValueAgrees: active.moreValueIdx === comparator.moreValueIdx,
    nearEvenSplit:
      active.nearEven &&
      comparator.nearEven &&
      active.moreValueIdx != null &&
      comparator.moreValueIdx != null &&
      active.moreValueIdx !== comparator.moreValueIdx,
    noAdjustment:
      active.adjustments.every((v) => v === 0) && comparator.adjustments.every((v) => v === 0),
    oneForOne: values[0].length === 1 && values[1].length === 1,
  };
}

const fmt = (v) => Math.round(Math.abs(v)).toLocaleString("en-US");

function leaningPhrase(evaluation, sideLabels) {
  if (evaluation.leaderIdx == null) return "near even";
  return `Side ${sideLabels[evaluation.leaderIdx]}'s package is worth more`;
}

function gapPhrase(evaluation, sideLabels) {
  if (evaluation.moreValueIdx == null) return "no gap";
  return `Side ${sideLabels[evaluation.moreValueIdx]} by ${fmt(evaluation.gap)}`;
}

/**
 * Plain-English words for a comparison: `{tone, headline, gapLine}`.
 * `tone` ∈ none | agree | split | disagree | unavailable | multi | empty —
 * `split` is "both near even, different side slightly ahead", which is never
 * worded as agreement.
 * Copy only — every number comes from `compareValueAdjustments`.
 */
export function vaComparisonSummary(comparison, sideLabels = ["A", "B"]) {
  const c = comparison || {};
  if (c.status === VA_COMPARISON_STATUS.EMPTY || c.status === VA_COMPARISON_STATUS.SAME_MODEL) {
    return { tone: "empty", headline: null, gapLine: null };
  }
  if (c.status === VA_COMPARISON_STATUS.MULTI_TEAM) {
    return {
      tone: "multi",
      headline:
        "The adjustment comparison covers two-team trades. With three or more teams, Chase Upside's adjustment is an extension of its two-team model, and the KTC adjustment method is not extended.",
      gapLine: null,
    };
  }
  if (c.status === VA_COMPARISON_STATUS.UNAVAILABLE) {
    const n = c.unpriced.length;
    return {
      tone: "unavailable",
      headline: `Adjustment comparison unavailable: ${n} piece${n === 1 ? " has" : "s have"} no Chase Upside value (unknown, not 0).`,
      gapLine: null,
    };
  }
  if (c.noAdjustment) {
    return {
      tone: "none",
      headline: c.oneForOne
        ? "No package adjustment under either method: a one-for-one trade carries none."
        : "No package adjustment under either method for this trade.",
      gapLine: null,
    };
  }
  const gapLine = `Gap after adjustment: ${gapPhrase(c.active, sideLabels)} (${ACTIVE_METHOD_LABEL}) · ${gapPhrase(c.comparator, sideLabels)} (${COMPARATOR_METHOD_LABEL})`;
  if (c.nearEvenSplit) {
    return {
      tone: "split",
      headline: "Both methods call it near even, but they differ on which side is slightly ahead.",
      gapLine,
    };
  }
  if (c.agree) {
    return {
      tone: "agree",
      headline:
        c.active.leaderIdx == null
          ? "Both methods agree: the packages are near even after adjustment."
          : `Both methods agree: ${leaningPhrase(c.active, sideLabels)} after adjustment.`,
      gapLine,
    };
  }
  return {
    tone: "disagree",
    headline: `The methods disagree. ${ACTIVE_METHOD_LABEL}: ${leaningPhrase(c.active, sideLabels)}. ${COMPARATOR_METHOD_LABEL}: ${leaningPhrase(c.comparator, sideLabels)}. The recommendation uses Chase Upside's.`,
    gapLine,
  };
}
