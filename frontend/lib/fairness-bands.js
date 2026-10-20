/**
 * fairness-bands — the JS mirror of the ONE fairness-band owner
 * (src/valuation_math/fairness_bands.py + config/trade/fairness_bands.json).
 *
 * fairness_bands_v2 (owner decisions 2026-10-20, OD-F1/F2/F3/F5): a relative
 * difference with an absolute minimum, relative to the LARGER PACKAGE UTILITY
 * (the active package model's depth-discounted value of each package):
 *   fair      |gap| < ABSOLUTE_MINIMUM  or  relativePct < SLIGHT_PCT
 *   slight    relativePct < UNFAIR_PCT
 *   unfair    relativePct < LOPSIDED_PCT
 *   lopsided  otherwise
 * relativePct = |gap| / larger package utility × 100.  The base comes from
 * `fairnessBase(utilities)` over per-side utilities the package-model layer
 * computes (`trade-logic.js::packageUtilities`, stamped as `utility` on side
 * totals and side flows) — never the larger ADJUSTED side, which was v1.
 *
 * Non-finite input (NaN, ±Infinity, null, undefined, a non-number, a negative
 * base) is REFUSED with a thrown FairnessInputError (code
 * `fairness_input_not_finite`) — identical to Python.  It is never "fair".
 *
 * Every number is an owner-approved PRIOR, validated after launch (OD-F4).
 * The constants below are pinned to the JSON owner by
 * tests/valuation_math/test_fairness_bands.py; change them only by changing
 * the owner.  This module classifies a package gap the page already holds
 * (the Immediate Result); it never decides a trade -- the decision comes from
 * POST /api/trade/analyze.
 */

export const FAIRNESS_BANDS_VERSION = "fairness_bands_v2";
export const FAIRNESS_BANDS_STATUS = "PRIOR_OWNER_APPROVED_2026-10-20";
export const FAIRNESS_BANDS_BASIS = "larger_package_utility";
export const ABSOLUTE_MINIMUM = 250;
export const SLIGHT_PCT = 3.5;
export const UNFAIR_PCT = 9.0;
export const LOPSIDED_PCT = 18.0;
/** OD-F1: the band level(s) that count as a FAIR TRADE. */
export const FAIR_TRADE_LEVELS = Object.freeze(["fair"]);
export const FAIRNESS_INPUT_ERROR_CODE = "fairness_input_not_finite";

export const FAIRNESS_LABELS = Object.freeze({
  fair: "FAIR",
  slight: "SLIGHT EDGE",
  unfair: "UNFAIR",
  lopsided: "LOPSIDED",
});

/** A gap or base that is not a finite number (or a negative base). */
export class FairnessInputError extends Error {
  constructor(message) {
    super(message);
    this.name = "FairnessInputError";
    this.code = FAIRNESS_INPUT_ERROR_CODE;
  }
}

function isFiniteNumber(x) {
  return typeof x === "number" && Number.isFinite(x);
}

function requireGap(gap) {
  if (!isFiniteNumber(gap)) throw new FairnessInputError(`${FAIRNESS_INPUT_ERROR_CODE}: gap=${String(gap)}`);
  return gap;
}

function requireBase(base) {
  if (!isFiniteNumber(base) || base < 0) {
    throw new FairnessInputError(`${FAIRNESS_INPUT_ERROR_CODE}: base=${String(base)}`);
  }
  return base;
}

/**
 * The band's relative base: the LARGEST package utility among the sides.
 * Every entry must be a finite, non-negative number (else FairnessInputError);
 * no sides is an empty pairing with base 0.  Python twin:
 * fairness_bands.fairness_base.
 */
export function fairnessBase(utilities) {
  let base = 0;
  for (const u of utilities || []) base = Math.max(base, requireBase(u));
  return base;
}

/** |gap| as a % of the larger package utility, or null when the base is 0. */
export function relativeGapPct(gap, largerUtility) {
  const g = requireGap(gap);
  const base = requireBase(largerUtility);
  if (base === 0) return null;
  return (Math.abs(g) / base) * 100;
}

/**
 * Classify one package gap.  `gap` is signed (only its size is classified);
 * `largerUtility` is the larger PACKAGE UTILITY (from `fairnessBase`).
 * Throws FairnessInputError on non-finite input.
 * @returns {{level: 'fair'|'slight'|'unfair'|'lopsided', label: string, relativePct: number|null, absoluteGap: number}}
 */
export function classifyGap(gap, largerUtility) {
  const absolute = Math.abs(requireGap(gap));
  const rel = relativeGapPct(gap, largerUtility);
  let level;
  if (absolute < ABSOLUTE_MINIMUM || rel == null || rel < SLIGHT_PCT) level = "fair";
  else if (rel < UNFAIR_PCT) level = "slight";
  else if (rel < LOPSIDED_PCT) level = "unfair";
  else level = "lopsided";
  return {
    level,
    label: FAIRNESS_LABELS[level],
    relativePct: rel == null ? null : Math.round(rel * 100) / 100,
    absoluteGap: absolute,
  };
}

/** True when the gap is inside the fair band (nothing to balance). */
export function isFairGap(gap, largerUtility) {
  return classifyGap(gap, largerUtility).level === "fair";
}

/** OD-F1: whether a band level counts as a FAIR TRADE (fail closed). */
export function countsAsFairTrade(level) {
  return FAIR_TRADE_LEVELS.includes(level);
}
