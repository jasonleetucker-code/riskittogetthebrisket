/**
 * Package-model dispatch — JS half (owner package 2026-10-17).
 * Twin: tests/valuation_math/test_package_model.py; shared fixture
 * tests/fixtures/package_model_parity_cases.json.
 */
import { describe, expect, it } from "vitest";
import fixture from "../../tests/fixtures/package_model_parity_cases.json";
import floatFixture from "../../tests/fixtures/package_model_float_cases.json";
import {
  ACTIVE_PACKAGE_MODEL_ID,
  PACKAGE_MODEL_IDS,
  adjustedSideTotals,
  computeValueAdjustment,
  geomPackageUtility,
  packageAdjustPair,
  packageModelReceipt,
  valueAdjustmentFromSideArrays,
} from "@/lib/trade-logic";
import { computeTradeVANet } from "@/lib/league-analysis";

const KTC = PACKAGE_MODEL_IDS.KTC_2026_04;
const GEOM = PACKAGE_MODEL_IDS.GEOM_Q078_V1;

function gap(a, b, modelId) {
  const r = packageAdjustPair(a, b, { modelId });
  const vaA = r.displayed && r.side === 1 ? r.value : 0;
  const vaB = r.displayed && r.side === 2 ? r.value : 0;
  const sum = (x) => x.reduce((s, v) => s + v, 0);
  return sum(a) + vaA - (sum(b) + vaB);
}

describe("package model dispatch", () => {
  it("the active model is owner-approved GEOM q=0.78", () => {
    expect(ACTIVE_PACKAGE_MODEL_ID).toBe("geom_q078_v1");
    expect(packageModelReceipt().classification).toBe("ACTIVE");
    expect(packageModelReceipt(KTC).classification).toBe("FALLBACK");
    expect(() => packageModelReceipt("nope")).toThrow();
  });

  it("the active path is exactly the geometric model", () => {
    for (const { team1, team2 } of fixture.cases) {
      expect(packageAdjustPair(team1, team2)).toEqual(
        packageAdjustPair(team1, team2, { modelId: GEOM }),
      );
    }
  });

  it("matches the shared JS/Python fixture for every model", () => {
    for (const c of fixture.cases) {
      for (const [modelId, expected] of Object.entries(c.expected)) {
        const r = packageAdjustPair(c.team1, c.team2, { modelId });
        expect([r.value, r.side, r.displayed]).toEqual(expected);
      }
    }
  });

  it("consumers route through the promoted model", () => {
    const row = (v) => ({ values: { full: v }, rankDerivedValue: v });
    const va = computeValueAdjustment(
      [row(7200)],
      [row(6000), row(500)],
      "full",
    );
    expect(va).toEqual({ adjustment: 110, recipientIdx: 0 });
    expect(valueAdjustmentFromSideArrays([[7200], [6000, 500]])).toEqual([
      110, 0,
    ]);
    expect(computeTradeVANet([7200], [6000, 500])).toBe(110);
    const totals = adjustedSideTotals(
      [row(7200)],
      [row(6000), row(500)],
      "full",
    );
    expect(totals[0].adjusted - totals[1].adjusted).toBe(810);
  });
});

describe("legacy KTC KNOWN_DEFECT pins (preserved for rollback parity)", () => {
  it("adding a positive asset to B widens A's lead", () => {
    expect(gap([7200], [6000], KTC)).toBe(1200);
    expect(gap([7200], [6000, 500], KTC)).toBe(3600);
    expect(gap([7200], [6000, 1], KTC)).toBeGreaterThan(1200);
    expect(gap([9000], [8500, 1], KTC)).toBeGreaterThan(
      gap([9000], [8500], KTC),
    );
  });
  it("twelve 2000s beat a 9000 under KTC", () => {
    expect(gap([9000], Array(12).fill(2000), KTC)).toBeLessThan(0);
  });
});

describe("promoted geometric model: structural guarantees, zero failures", () => {
  it("closed form", () => {
    expect(geomPackageUtility([6000, 500])).toBeCloseTo(6390, 6);
    expect(gap([7200], [6000, 500], GEOM)).toBe(810);
    expect(packageAdjustPair([7200], [6000], { modelId: GEOM })).toEqual({
      value: 0,
      side: 0,
      displayed: false,
    });
    expect(gap([9000], Array(12).fill(2000), GEOM)).toBeGreaterThan(0);
    expect(gap([9000], Array(12).fill(2500), GEOM)).toBeLessThan(0);
  });

  it("monotone, side-symmetric, order-invariant and homogeneous on a seeded suite", () => {
    let seed = 98231;
    const rnd = () => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    };
    const side = () =>
      Array.from(
        { length: 1 + Math.floor(rnd() * 4) },
        () => 500 + Math.floor(rnd() * 9500),
      );
    const fails = { addA: 0, addB: 0, raiseB: 0, swap: 0, order: 0, scale: 0 };
    for (let i = 0; i < 3000; i++) {
      const a = side();
      const b = side();
      const g = gap(a, b, GEOM);
      const x = 1 + Math.floor(rnd() * 3000);
      if (gap([...a, x], b, GEOM) < g - 1) fails.addA++;
      if (gap(a, [...b, x], GEOM) > g + 1) fails.addB++;
      const raised = [...b];
      raised[Math.floor(rnd() * raised.length)] += 1 + Math.floor(rnd() * 2000);
      if (gap(a, raised, GEOM) > g + 1) fails.raiseB++;
      if (Math.abs(gap(b, a, GEOM) + g) > 1) fails.swap++;
      if (Math.abs(gap([...a].reverse(), [...b].reverse(), GEOM) - g) > 1)
        fails.order++;
      if (
        Math.abs(
          gap(
            a.map((v) => 2 * v),
            b.map((v) => 2 * v),
            GEOM,
          ) -
            2 * g,
        ) > 2
      )
        fails.scale++;
    }
    expect(fails).toEqual({
      addA: 0,
      addB: 0,
      raiseB: 0,
      swap: 0,
      order: 0,
      scale: 0,
    });
  });
});

// Brisket Trade Advisor B0-e: the geometric utility is BIT-identical to the
// Python owner (iterative w *= q + left fold in both languages; `**` and
// CPython's compensated sum() diverged).  Twin:
// tests/valuation_math/test_package_model_float.py.
describe("package model float determinism", () => {
  it("geomPackageUtility reproduces the shared float fixture exactly", () => {
    expect(floatFixture.q).toBe(0.78);
    expect(floatFixture.cases.length).toBeGreaterThanOrEqual(200);
    for (const c of floatFixture.cases) {
      expect(geomPackageUtility(c.team1)).toBe(Number(c.utility1));
      expect(geomPackageUtility(c.team2)).toBe(Number(c.utility2));
      const r = packageAdjustPair(c.team1, c.team2, { modelId: GEOM });
      expect([r.value, r.side, r.displayed]).toEqual(c.expected);
    }
  });
});
