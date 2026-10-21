/**
 * Value Adjustment comparison (owner directive 2026-10-19, part 2):
 * Chase Upside's ACTIVE geometric model (geom_q078_v1, q = 0.78) beside the
 * read-only KTC adjustment method (ktc_2026_04), both through the ONE
 * canonical dispatch.
 *
 *   * the KTC comparator reproduces the shared JS/Python parity fixture and
 *     the captured keeptradecut.com observations, known non-monotone cases
 *     included (they are KTC's behaviour, not something to fix here);
 *   * the geometric model is checked independently, in closed form;
 *   * no blending: each model's adjusted totals are raw + ITS OWN adjustment;
 *   * missing is never zero; 3+ teams are named, not fabricated;
 *   * the official headline quantities are identical with or without it.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import parity from "../../tests/fixtures/package_model_parity_cases.json";
import {
  ACTIVE_PACKAGE_MODEL_ID,
  PACKAGE_MODEL_IDS,
  adjustedSideTotals,
  geomPackageUtility,
  ktcAdjustPackage,
  meterVerdict,
  packageAdjustPair,
  packageUtilities,
  sideTotalsFairnessBase,
  tradeGapAdjusted,
} from "@/lib/trade-logic";
import {
  ACTIVE_METHOD_LABEL,
  COMPARATOR_METHOD_LABEL,
  COMPARATOR_PACKAGE_MODEL_ID,
  VA_COMPARISON_STATUS,
  compareValueAdjustments,
  evaluatePackageModel,
  vaComparisonSummary,
} from "@/lib/va-comparison";

const HERE = dirname(fileURLToPath(import.meta.url));
const KTC = PACKAGE_MODEL_IDS.KTC_2026_04;
const GEOM = PACKAGE_MODEL_IDS.GEOM_Q078_V1;
const sum = (xs) => xs.reduce((s, v) => s + v, 0);
const row = (v) => ({ values: { full: v }, rankDerivedValue: v });

/** [value, side, displayed] as the parity fixture states it, from an evaluation. */
function asFixtureTriple(evaluation) {
  const [a, b] = evaluation.adjustments;
  if (a > 0) return [a, 1, true];
  if (b > 0) return [b, 2, true];
  return [0, 0, false];
}

describe("models: the comparator is KTC, the active one is Chase Upside's", () => {
  it("names the models without ever saying 'KTC values'", () => {
    expect(ACTIVE_PACKAGE_MODEL_ID).toBe(GEOM);
    expect(COMPARATOR_PACKAGE_MODEL_ID).toBe(KTC);
    expect(ACTIVE_METHOD_LABEL).toBe("Chase Upside adjustment");
    expect(COMPARATOR_METHOD_LABEL).toBe("KTC adjustment method");
  });
});

describe("KTC comparator against the existing KTC parity fixtures", () => {
  const twoSided = parity.cases.filter((c) => c.team1.length && c.team2.length);

  it("reproduces every two-sided parity case for BOTH models", () => {
    expect(twoSided.length).toBeGreaterThan(40);
    for (const c of twoSided) {
      const cmp = compareValueAdjustments([c.team1, c.team2]);
      expect(cmp.status).toBe(VA_COMPARISON_STATUS.OK);
      expect(asFixtureTriple(cmp.comparator), JSON.stringify(c)).toEqual(c.expected[KTC]);
      expect(asFixtureTriple(cmp.active), JSON.stringify(c)).toEqual(c.expected[GEOM]);
    }
  });

  it("known non-monotone KTC cases come through unchanged (comparator only)", () => {
    const gap = (a, b) => compareValueAdjustments([a, b]).comparator.gap;
    const geomGap = (a, b) => compareValueAdjustments([a, b]).active.gap;
    // [7200] vs [6000] → +500 on B WIDENS A's lead under KTC (2900 to A).
    expect(gap([7200], [6000])).toBe(1200);
    expect(gap([7200], [6000, 500])).toBe(3600);
    expect(gap([7200], [6000, 1])).toBeGreaterThan(1200);
    expect(gap([9000], [8500, 1])).toBeGreaterThan(gap([9000], [8500]));
    // [8200] vs [5500, 4900]: the KTC port's documented ~3636 to the stud.
    expect(compareValueAdjustments([[8200], [5500, 4900]]).comparator.adjustments).toEqual([
      3636, 0,
    ]);
    // Twelve 2000s beat a 9000 under KTC; not under the geometric model.
    expect(gap([9000], Array(12).fill(2000))).toBeLessThan(0);
    expect(geomGap([9000], Array(12).fill(2000))).toBeGreaterThan(0);
    // The geometric model is monotone on the same cases.
    expect(geomGap([7200], [6000, 500])).toBeLessThanOrEqual(geomGap([7200], [6000]));
    expect(geomGap([9000], [8500, 1])).toBeLessThanOrEqual(geomGap([9000], [8500]));
  });

  it("the comparator IS the dispatch's KTC port (no second implementation)", () => {
    for (const c of twoSided) {
      const r = ktcAdjustPackage(c.team1, c.team2);
      const viaDispatch = packageAdjustPair(c.team1, c.team2, { modelId: KTC });
      expect(viaDispatch).toEqual(r);
      expect(asFixtureTriple(compareValueAdjustments([c.team1, c.team2]).comparator)).toEqual([
        r.value,
        r.side,
        r.displayed,
      ]);
    }
  });

  it("tracks the captured keeptradecut.com display values (139 observed trades)", () => {
    const obs = JSON.parse(
      readFileSync(resolve(HERE, "../../scripts/ktc_va_observations.json"), "utf-8"),
    ).observations;
    expect(obs.length).toBeGreaterThan(100);
    let sq = 0;
    let n = 0;
    let sideMisses = 0;
    for (const o of obs) {
      if (!o.team1Values?.length || !o.team2Values?.length) continue;
      const cmp = compareValueAdjustments([o.team1Values, o.team2Values]).comparator;
      const observed = (o.valueAdjustmentTeam1 || 0) - (o.valueAdjustmentTeam2 || 0);
      const ported = cmp.adjustments[0] - cmp.adjustments[1];
      sq += (ported - observed) ** 2;
      n += 1;
      if (Math.sign(ported) !== Math.sign(observed)) sideMisses += 1;
      // The port's one documented miss (UNEQ_4v5_a) is ~306.
      expect(Math.abs(ported - observed), o.label).toBeLessThanOrEqual(320);
    }
    expect(Math.sqrt(sq / n)).toBeLessThan(40);
    expect(sideMisses).toBe(0);
  });
});

describe("geometric (active) model — independently, in closed form", () => {
  it("adjusted gap equals U_A − U_B (q = 0.78), whatever the comparator says", () => {
    let seed = 4242;
    const rnd = () => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    };
    const side = () =>
      Array.from({ length: 1 + Math.floor(rnd() * 5) }, () => 300 + Math.floor(rnd() * 9600));
    for (let i = 0; i < 500; i++) {
      const a = side();
      const b = side();
      const { active } = compareValueAdjustments([a, b]);
      expect(Math.abs(active.gap - (geomPackageUtility(a) - geomPackageUtility(b)))).toBeLessThan(
        1,
      );
      expect(active.adjustments.filter((v) => v > 0).length).toBeLessThanOrEqual(1);
    }
  });

  it("a lone stud receives exactly what the other side discards (660 here)", () => {
    // [4000, 3000]: 3000 × (1 − 0.78) = 660.
    const ev = evaluatePackageModel([[8000], [4000, 3000]], GEOM);
    expect(ev.adjustments).toEqual([660, 0]);
    expect(ev.role).toBe("active");
    expect(ev.receipt.classification).toBe("ACTIVE");
  });
});

describe("never blended: two alternative whole-package evaluations", () => {
  it("each model's adjusted totals are raw + its own adjustment, and raw totals are shared", () => {
    const cmp = compareValueAdjustments([[9000], [8200, 2000]]);
    for (const ev of [cmp.active, cmp.comparator]) {
      expect(ev.rawTotals).toEqual([9000, 10200]);
      expect(ev.adjustedTotals).toEqual([
        ev.rawTotals[0] + ev.adjustments[0],
        ev.rawTotals[1] + ev.adjustments[1],
      ]);
    }
    const ktc = packageAdjustPair([9000], [8200, 2000], { modelId: KTC });
    const geom = packageAdjustPair([9000], [8200, 2000], { modelId: GEOM });
    expect(cmp.comparator.adjustments[0]).toBe(ktc.value);
    expect(cmp.active.adjustments[0]).toBe(geom.value);
    // Not the sum, not the mean, not one applied on top of the other.
    expect(cmp.active.adjustedTotals[0]).not.toBe(9000 + ktc.value + geom.value);
    expect(cmp.active.adjustedTotals[0]).not.toBe(9000 + (ktc.value + geom.value) / 2);
  });

  it("does not mutate the values it is given", () => {
    const a = Object.freeze([9000]);
    const b = Object.freeze([8200, 2000]);
    const input = Object.freeze([a, b]);
    expect(() => compareValueAdjustments(input)).not.toThrow();
    expect(input).toEqual([[9000], [8200, 2000]]);
  });
});

describe("agreement, disagreement and the no-adjustment state", () => {
  it("agree: both methods lean the same way — said simply", () => {
    const cmp = compareValueAdjustments([[7200], [6000, 500]]);
    expect(cmp.agree).toBe(true);
    expect(cmp.active.leaderIdx).toBe(0);
    expect(cmp.comparator.leaderIdx).toBe(0);
    const s = vaComparisonSummary(cmp, ["A", "B"]);
    expect(s.tone).toBe("agree");
    expect(s.headline).toBe("Both methods agree: Side A's package is worth more after adjustment.");
  });

  it("disagree: the leaders differ, and the recommendation's method is named", () => {
    const cmp = compareValueAdjustments([[9000], [8200, 2000]]);
    expect(cmp.agree).toBe(false);
    expect(cmp.active.leaderIdx).toBe(1);
    expect(cmp.comparator.leaderIdx).toBe(0);
    const s = vaComparisonSummary(cmp, ["A", "B"]);
    expect(s.tone).toBe("disagree");
    expect(s.headline).toContain("The recommendation uses Chase Upside's.");
    expect(s.gapLine).toBe(
      "Gap after adjustment: Side B by 760 (Chase Upside adjustment) · Side A by 1,020 (KTC adjustment method)",
    );
  });

  it("both inside the fair band with the SAME side ahead: agree, near even", () => {
    const cmp = compareValueAdjustments([[5000, 100], [5000]]);
    expect(cmp.active.leaderIdx).toBeNull();
    expect(cmp.comparator.leaderIdx).toBeNull();
    // The same side is (slightly) ahead under both — a real agreement.
    expect(cmp.active.moreValueIdx).toBe(0);
    expect(cmp.comparator.moreValueIdx).toBe(0);
    expect(cmp.moreValueAgrees).toBe(true);
    expect(cmp.nearEvenSplit).toBe(false);
    expect(cmp.agree).toBe(true);
    const s = vaComparisonSummary(cmp);
    expect(s.tone).toBe("agree");
    expect(s.headline).toBe("Both methods agree: the packages are near even after adjustment.");
  });

  it("both inside the fair band but DIFFERENT sides ahead: never worded as agreement", () => {
    // Review repro: Chase Upside puts B ahead by 383, the KTC method A by 478.
    const cmp = compareValueAdjustments([
      [1378, 5343, 6310],
      [5741, 3842, 4641],
    ]);
    expect(cmp.active.nearEven).toBe(true);
    expect(cmp.comparator.nearEven).toBe(true);
    expect(cmp.active.moreValueIdx).toBe(1);
    expect(cmp.comparator.moreValueIdx).toBe(0);
    expect(Math.round(cmp.active.gap)).toBe(-383);
    expect(Math.round(cmp.comparator.gap)).toBe(478);
    expect(cmp.moreValueAgrees).toBe(false);
    expect(cmp.nearEvenSplit).toBe(true);
    const s = vaComparisonSummary(cmp, ["A", "B"]);
    expect(s.tone).toBe("split");
    expect(s.headline).toBe(
      "Both methods call it near even, but they differ on which side is slightly ahead.",
    );
    expect(s.headline).not.toMatch(/agree/);
    expect(s.gapLine).toBe(
      "Gap after adjustment: Side B by 383 (Chase Upside adjustment) · Side A by 478 (KTC adjustment method)",
    );
  });

  it("a split is only a split when both sides are named: an exact tie is not one", () => {
    for (const [a, b] of [
      [[5000], [5000]],
      [[3000, 2000], [5000]],
    ]) {
      const cmp = compareValueAdjustments([a, b]);
      if (cmp.active.moreValueIdx == null || cmp.comparator.moreValueIdx == null) {
        expect(cmp.nearEvenSplit).toBe(false);
      }
    }
  });

  it("the comparator column carries a neutral gap %, never the headline's verdict words", () => {
    const values = [[9000], [8200, 2000]];
    const cmp = compareValueAdjustments(values);
    for (const ev of [cmp.active, cmp.comparator]) {
      expect(ev).not.toHaveProperty("bandWord");
      // fairness_bands_v2: relative to the larger package UTILITY under that
      // model (the KTC method has none, so its adjusted totals stand in).
      const larger = Math.max(...packageUtilities(values, ev.adjustedTotals, { modelId: ev.modelId }));
      expect(ev.relativeGapPct).toBeCloseTo((Math.abs(ev.gap) / larger) * 100, 1);
    }
    expect(cmp.comparator.relativeGapPct).toBeCloseTo(
      (Math.abs(cmp.comparator.gap) / Math.max(...cmp.comparator.adjustedTotals)) * 100,
      1,
    );
  });

  it("one-for-one: no adjustment under either method, explained instead of numbers", () => {
    const cmp = compareValueAdjustments([[7200], [6000]]);
    expect(cmp.noAdjustment).toBe(true);
    expect(cmp.oneForOne).toBe(true);
    const s = vaComparisonSummary(cmp);
    expect(s.tone).toBe("none");
    expect(s.headline).toBe(
      "No package adjustment under either method: a one-for-one trade carries none.",
    );
    expect(s.gapLine).toBeNull();
  });
});

describe("missing is never zero; 3+ teams are named; empty is nothing", () => {
  it("an unpriced piece makes the comparison unavailable, with a count — never a 0", () => {
    const cmp = compareValueAdjustments([[9000, null], [8200]]);
    expect(cmp.status).toBe(VA_COMPARISON_STATUS.UNAVAILABLE);
    expect(cmp.unpriced).toEqual([{ side: 0, index: 1 }]);
    expect(cmp.active).toBeUndefined();
    expect(cmp.comparator).toBeUndefined();
    expect(vaComparisonSummary(cmp).headline).toBe(
      "Adjustment comparison unavailable: 1 piece has no Chase Upside value (unknown, not 0).",
    );
    expect(compareValueAdjustments([[9000, 0], [8200]]).status).toBe(
      VA_COMPARISON_STATUS.UNAVAILABLE,
    );
  });

  it("3+ teams: the comparator is not extended, and the summary says so", () => {
    const cmp = compareValueAdjustments([[9000], [8200], [3000, 2000]]);
    expect(cmp.status).toBe(VA_COMPARISON_STATUS.MULTI_TEAM);
    expect(cmp.comparator).toBeUndefined();
    expect(vaComparisonSummary(cmp).tone).toBe("multi");
  });

  it("an empty side has nothing to compare", () => {
    expect(compareValueAdjustments([[9000], []]).status).toBe(VA_COMPARISON_STATUS.EMPTY);
    expect(compareValueAdjustments([]).status).toBe(VA_COMPARISON_STATUS.EMPTY);
    expect(vaComparisonSummary(compareValueAdjustments(null)).headline).toBeNull();
  });
});

describe("the official decision quantities do not change when the comparison is shown", () => {
  it("the Chase Upside column equals the headline's own adjusted totals, before and after", () => {
    const cases = [
      [[9000], [8200, 2000]],
      [[7200], [6000, 500]],
      [[8200], [5500, 4900]],
      [[7200], [6000]],
      [[3000, 2000, 1000], [5500]],
    ];
    for (const [a, b] of cases) {
      const sideA = a.map(row);
      const sideB = b.map(row);
      const before = adjustedSideTotals(sideA, sideB, "full");
      const gapBefore = tradeGapAdjusted(sideA, sideB, "full");
      const larger = sideTotalsFairnessBase(before);
      const verdictBefore = meterVerdict(gapBefore, larger);
      const cmp = compareValueAdjustments([a, b]);
      expect(cmp.active.adjustedTotals).toEqual(before.map((t) => t.adjusted));
      expect(cmp.active.gap).toBe(gapBefore);
      // Asking for the comparison changed nothing the headline reads.
      expect(adjustedSideTotals(sideA, sideB, "full")).toEqual(before);
      expect(tradeGapAdjusted(sideA, sideB, "full")).toBe(gapBefore);
      expect(meterVerdict(tradeGapAdjusted(sideA, sideB, "full"), larger)).toEqual(verdictBefore);
      expect(sum(cmp.active.rawTotals)).toBe(sum(a) + sum(b));
    }
  });

  it("no decision owner imports the comparison (structural)", () => {
    const decisionOwners = [
      "lib/trade-logic.js",
      "lib/trade-war-room.js",
      "lib/fairness-bands.js",
      "lib/second-opinions.js",
      "components/trade/TradeMeter.jsx",
      "components/trade/TradeWarRoom.jsx",
      "components/trade/TradeOpinionTally.jsx",
    ];
    for (const rel of decisionOwners) {
      const src = readFileSync(resolve(HERE, "..", rel), "utf-8");
      expect(src, rel).not.toMatch(/va-comparison/);
      expect(src, rel).not.toMatch(/compareModelId/);
    }
  });
});
