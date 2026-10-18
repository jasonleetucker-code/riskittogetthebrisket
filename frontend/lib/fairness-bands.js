/**
 * fairness-bands — the JS mirror of the ONE fairness-band owner
 * (src/valuation_math/fairness_bands.py + config/trade/fairness_bands.json;
 * TC-C, owner decision 3, 2026-10-18).
 *
 * A relative difference with an absolute minimum, on ADJUSTED package totals:
 *   fair      |gap| < ABSOLUTE_MINIMUM  or  relativePct < SLIGHT_PCT
 *   slight    relativePct < UNFAIR_PCT
 *   unfair    relativePct < LOPSIDED_PCT
 *   lopsided  otherwise
 * relativePct = |gap| / larger adjusted side × 100.
 *
 * PROVISIONAL until validated.  The constants below are pinned to the JSON
 * owner by tests/valuation_math/test_fairness_bands.py; change them only by
 * changing the owner.  This module classifies a package gap the page already
 * holds (the Immediate Result); it never decides a trade -- the decision comes
 * from POST /api/trade/analyze.
 */

export const FAIRNESS_BANDS_VERSION = "fairness_bands_v1";
export const FAIRNESS_BANDS_STATUS = "PROVISIONAL";
export const ABSOLUTE_MINIMUM = 250;
export const SLIGHT_PCT = 3.5;
export const UNFAIR_PCT = 9.0;
export const LOPSIDED_PCT = 18.0;

export const FAIRNESS_LABELS = Object.freeze({
  fair: "FAIR",
  slight: "SLIGHT EDGE",
  unfair: "UNFAIR",
  lopsided: "LOPSIDED",
});

/** |gap| as a % of the larger adjusted side, or null with nothing to be relative to. */
export function relativeGapPct(gap, largerSide) {
  const larger = Number(largerSide);
  if (!Number.isFinite(larger) || larger <= 0) return null;
  return (Math.abs(Number(gap)) / larger) * 100;
}

/**
 * Classify one package gap.  `gap` is signed (only its size is classified);
 * `largerSide` is the larger ADJUSTED package total.
 * @returns {{level: 'fair'|'slight'|'unfair'|'lopsided', label: string, relativePct: number|null, absoluteGap: number|null}}
 */
export function classifyGap(gap, largerSide) {
  const absolute = Math.abs(Number(gap));
  const rel = relativeGapPct(gap, largerSide);
  let level;
  if (!Number.isFinite(absolute) || absolute < ABSOLUTE_MINIMUM || rel == null || rel < SLIGHT_PCT) {
    level = "fair";
  } else if (rel < UNFAIR_PCT) level = "slight";
  else if (rel < LOPSIDED_PCT) level = "unfair";
  else level = "lopsided";
  return {
    level,
    label: FAIRNESS_LABELS[level],
    relativePct: rel == null ? null : Math.round(rel * 100) / 100,
    absoluteGap: Number.isFinite(absolute) ? absolute : null,
  };
}

/** True when the gap is inside the fair band (nothing to balance). */
export function isFairGap(gap, largerSide) {
  return classifyGap(gap, largerSide).level === "fair";
}
