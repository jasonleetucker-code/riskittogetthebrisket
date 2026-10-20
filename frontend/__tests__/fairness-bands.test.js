/**
 * The JS mirror of the ONE fairness-band owner — fairness_bands_v2 (owner
 * decisions 2026-10-20).  Python twin: tests/valuation_math/test_fairness_bands.py
 * (also pins these constants to config/trade/fairness_bands.json).  Shared
 * fixtures: tests/fixtures/fairness_band_cases.json (levels on the larger
 * PACKAGE UTILITY) and tests/fixtures/fairness_band_refusal_cases.json
 * (non-finite input is refused identically in both languages).
 */
import { describe, expect, it } from "vitest";
import fixture from "../../tests/fixtures/fairness_band_cases.json";
import refusals from "../../tests/fixtures/fairness_band_refusal_cases.json";
import rounding from "../../tests/fixtures/fairness_band_rounding_cases.json";
import {
  FAIRNESS_BANDS_VERSION,
  FAIRNESS_INPUT_ERROR_CODE,
  FAIRNESS_INPUT_INCONSISTENT_CODE,
  FairnessInputError,
  classifyGap,
  countsAsFairTrade,
  fairnessBase,
  isFairGap,
  relativeGapPct,
} from "@/lib/fairness-bands";
import {
  adjustedSideTotals,
  computeSideFlows,
  meterVerdict,
  multiTeamNetSummary,
  packageAdjustPair,
  packageUtilities,
  PACKAGE_MODEL_IDS,
  sideTotalsFairnessBase,
  tradeImbalance,
} from "@/lib/trade-logic";

/** The refusal fixture's token vocabulary (shared with the Python test). */
function decode(token) {
  if (typeof token !== "string") return token;
  if (token === "NaN") return NaN;
  if (token === "Infinity") return Infinity;
  if (token === "-Infinity") return -Infinity;
  if (token === "null") return null;
  if (token === "undefined") return undefined;
  if (token.startsWith("str:")) return token.slice(4);
  if (token === "bool:true") return true;
  if (token === "object:{}") return {};
  throw new Error(`unknown token ${token}`);
}

const row = (name, value) => ({ name, values: { full: value } });
const side = (...values) => values.map((v, i) => row(`p${v}_${i}`, v));

describe("fairness bands v2 (JS mirror)", () => {
  it("is the owner's version", () => {
    expect(fixture.bands).toBe(FAIRNESS_BANDS_VERSION);
    expect(FAIRNESS_BANDS_VERSION).toBe("fairness_bands_v2");
  });
  for (const c of fixture.cases) {
    it(`${c.id} (${c.assetMix})`, () => {
      expect(classifyGap(c.gap, c.largerUtility).level).toBe(c.expectedLevel);
      expect(classifyGap(-c.gap, c.largerUtility).level).toBe(c.expectedLevel);
      expect(isFairGap(c.gap, c.largerUtility)).toBe(c.expectedLevel === "fair");
    });
    if (c.sideA) {
      it(`${c.id}: the base comes from the package layer, not the adjusted side`, () => {
        const totals = adjustedSideTotals(side(...c.sideA), side(...c.sideB), "full");
        const base = sideTotalsFairnessBase(totals);
        expect(base).toBeCloseTo(c.largerUtility, 2);
        expect(Math.round(Math.max(totals[0].adjusted, totals[1].adjusted))).toBe(c.v1LargerAdjusted);
        expect(meterVerdict(totals[0].adjusted - totals[1].adjusted, base).level).toBe(c.expectedLevel);
        // tradeImbalance (balancers) reads the same base.
        const imb = tradeImbalance(
          [{ assets: side(...c.sideA) }, { assets: side(...c.sideB) }],
          "full",
        );
        expect(imb.largerUtility).toBe(base);
      });
    }
  }
});

describe("1-for-1 is byte-identical to v1 (OD-F2)", () => {
  const GRID = [1, 7, 100, 249, 250, 251, 499.5, 1000, 1389, 2777.8, 3000, 7142.9, 7143, 9999];
  it("over a grid, including a 1-for-0", () => {
    for (const a of GRID) {
      for (const b of [...GRID, null]) {
        const totals = adjustedSideTotals(side(a), b == null ? [] : side(b), "full");
        const gap = totals[0].adjusted - totals[1].adjusted;
        const v1 = classifyGap(gap, Math.max(totals[0].adjusted, totals[1].adjusted));
        const v2 = classifyGap(gap, sideTotalsFairnessBase(totals));
        expect(JSON.stringify(v2)).toBe(JSON.stringify(v1));
      }
    }
  });
});

describe("refusal: non-finite input is never classified (MISSING IS NEVER ZERO)", () => {
  it("shares the Python error code", () => {
    expect(refusals.code).toBe(FAIRNESS_INPUT_ERROR_CODE);
    expect(new FairnessInputError("x").code).toBe(FAIRNESS_INPUT_ERROR_CODE);
  });
  for (const c of refusals.classify) {
    it(`classify(${c.gap}, ${c.base}) -> ${c.expect}`, () => {
      const gap = decode(c.gap);
      const base = decode(c.base);
      if (c.expect === "refuse") {
        expect(() => classifyGap(gap, base)).toThrow(FairnessInputError);
        expect(() => isFairGap(gap, base)).toThrow(FairnessInputError);
        expect(() => meterVerdict(gap, base)).toThrow(FairnessInputError);
        let code = null;
        try {
          classifyGap(gap, base);
        } catch (err) {
          code = err.code;
        }
        expect(code).toBe(c.expectCode ?? refusals.code);
      } else {
        expect(classifyGap(gap, base).level).toBe(c.expect);
      }
    });
  }
  for (const c of refusals.base) {
    it(`fairnessBase(${JSON.stringify(c.utilities)}) -> ${c.expect}`, () => {
      const utilities = c.utilities.map(decode);
      if (c.expect === "refuse") expect(() => fairnessBase(utilities)).toThrow(FairnessInputError);
      else expect(fairnessBase(utilities)).toBe(c.expect);
    });
  }
  it("shares the Python inconsistent-input code", () => {
    expect(refusals.inconsistentCode).toBe(FAIRNESS_INPUT_INCONSISTENT_CODE);
  });
  for (const c of refusals.baseContainers) {
    it(`fairnessBase(<${c.container}>) -> refuse`, () => {
      expect(() => fairnessBase(decode(c.container))).toThrow(FairnessInputError);
      expect(() => sideTotalsFairnessBase(decode(c.container))).toThrow(FairnessInputError);
    });
  }
  for (const c of refusals.packagePieces) {
    it(`packageUtilities(${JSON.stringify(c.a)}, ${JSON.stringify(c.b)}) -> ${c.expect}`, () => {
      const dec = (x) => (typeof x === "string" ? decode(x) : x.map(decode));
      const values = [dec(c.a), dec(c.b)];
      if (c.expect === "refuse") {
        for (const modelId of [undefined, PACKAGE_MODEL_IDS.KTC_2026_04]) {
          expect(() => fairnessBase(packageUtilities(values, [1, 1], { modelId }))).toThrow(
            FairnessInputError,
          );
        }
      } else {
        expect(fairnessBase(packageUtilities(values, []))).toBeCloseTo(c.expect, 9);
      }
    });
  }
  it("a zero base beside a gap above the floor is refused, never FAIR (review of #1886)", () => {
    // The reviewer's multi-team cases: flows with no / NaN / one zero utility.
    for (const flows of [
      [{ net: 5000 }, { net: -3000 }, { net: -2000 }],
      [{ net: 5000, utility: NaN }, { net: -5000, utility: NaN }],
      [{ net: 5000, utility: 0 }],
    ]) {
      expect(() => multiTeamNetSummary(flows)).toThrow(FairnessInputError);
    }
    expect(() => classifyGap(5000, 0)).toThrow(FairnessInputError);
    expect(() => classifyGap(5000, fairnessBase(undefined))).toThrow(FairnessInputError);
    expect(() => sideTotalsFairnessBase(undefined)).toThrow(FairnessInputError);
  });
  it("NaN never reads fair through any helper", () => {
    expect(() => relativeGapPct(NaN, 5000)).toThrow(FairnessInputError);
    expect(() => classifyGap(NaN, 5000)).toThrow(FairnessInputError);
  });
  it("a side total without a utility is refused, never read as 0", () => {
    expect(() => sideTotalsFairnessBase([{ adjusted: 5000 }, { adjusted: 4000, utility: 4000 }])).toThrow(
      FairnessInputError,
    );
    expect(() => sideTotalsFairnessBase([null, { utility: 4000 }])).toThrow(FairnessInputError);
    expect(sideTotalsFairnessBase([])).toBe(0);
  });
  it("placeholder flows that state utility 0 classify their zero nets", () => {
    const flows = [0, 0, 0].map(() => ({ given: 0, received: 0, net: 0, utility: 0 }));
    expect(multiTeamNetSummary(flows).verdict.level).toBe("fair");
  });
});

describe("package utilities (the base's producer)", () => {
  it("ktc rollback: adjusted totals stand in (the v1 basis)", () => {
    const vals = [[7200], [6000, 500]];
    const r = packageAdjustPair(vals[0], vals[1], { modelId: PACKAGE_MODEL_IDS.KTC_2026_04 });
    const adjusted = [7200 + (r.side === 1 ? r.value : 0), 6500 + (r.side === 2 ? r.value : 0)];
    expect(packageUtilities(vals, adjusted, { modelId: PACKAGE_MODEL_IDS.KTC_2026_04 })).toEqual(adjusted);
  });
  it("multi-team: the base is the largest utility any side sends", () => {
    const sides = [
      { assets: side(6000), destinations: {} },
      { assets: side(5000), destinations: {} },
      { assets: side(3000, 2000, 1000), destinations: {} },
    ];
    const flows = computeSideFlows(sides, "full");
    const utils = flows.map((f) => f.utility);
    expect(utils[2]).toBeCloseTo(3000 + 2000 * 0.78 + 1000 * 0.78 * 0.78, 6);
    expect(multiTeamNetSummary(flows).largerUtility).toBe(Math.max(...utils));
    expect(tradeImbalance(sides, "full").largerUtility).toBe(Math.max(...utils));
  });
});

describe("OD-F1: FAIR TRADE is the fair band only", () => {
  it("counts only 'fair'", () => {
    expect(countsAsFairTrade("fair")).toBe(true);
    for (const level of ["slight", "unfair", "lopsided", null, undefined, "FAIR"]) {
      expect(countsAsFairTrade(level)).toBe(false);
    }
  });
});

describe("published rounding equals the Python owner's (shared fixture)", () => {
  it("relativePct and absoluteGap on every case, half-ties included", () => {
    expect(rounding.cases.length).toBeGreaterThan(300);
    for (const c of rounding.cases) {
      const r = classifyGap(c.gap, c.base);
      expect([r.level, r.relativePct, r.absoluteGap]).toEqual([c.level, c.relativePct, c.absoluteGap]);
    }
  });
});
