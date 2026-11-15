/**
 * TC-A #15 — cross-surface package-equity parity (JavaScript half).
 *
 * Every surface that publishes an adjusted package gap reports the SAME gap
 * for the same inputs and the same package model.  Expectations come from ONE
 * shared fixture, tests/fixtures/trade_package_equity_parity_cases.json,
 * derived in closed form from the active model (neither language produced
 * them).  Python twin: tests/trade/test_package_equity_parity.py (Analyze
 * Trade market lens, suggestions, finder, public trade-history grade, Monte
 * Carlo).  Documented intentional differences live in the fixture's
 * `intentionalDifferences`.
 *
 * Surfaces asserted here: the /trade headline (tradeGapAdjusted,
 * adjustedSideTotals, tradeImbalance, computeSideFlows, packageAdjustPair),
 * Second Opinions (evaluateOpinion + valueAdjustmentFromSideArrays), and the
 * private trade-history grade (gradeTradeSides).
 */
import { describe, expect, it } from "vitest";
import fixture from "../../tests/fixtures/trade_package_equity_parity_cases.json";
import {
  ACTIVE_PACKAGE_MODEL_ID,
  TRADE_VALUE_MODE,
  adjustedSideTotals,
  computeSideFlows,
  packageAdjustPair,
  tradeGapAdjusted,
  tradeImbalance,
  valueAdjustmentFromSideArrays,
} from "@/lib/trade-logic";
import { OPINION_ORIGIN, OPINION_STATE, evaluateOpinion } from "@/lib/second-opinions";
import { gradeTradeSides } from "@/lib/league-analysis";

const rows = (values, tag) =>
  values.map((v, i) => ({ name: `${tag}${i}`, assetClass: "offense", values: { full: v } }));

describe("cross-surface package equity parity", () => {
  it("the fixture is for the active model and covers both recipients and none", () => {
    expect(fixture.model).toBe(ACTIVE_PACKAGE_MODEL_ID);
    expect(fixture.cases.length).toBeGreaterThanOrEqual(8);
    expect(new Set(fixture.cases.map((c) => c.expected.vaRecipient))).toEqual(
      new Set(["A", "B", null]),
    );
  });

  for (const c of fixture.cases) {
    const exp = c.expected;
    describe(c.id, () => {
      it("packageAdjustPair (the owner dispatch)", () => {
        const r = packageAdjustPair(c.sideA, c.sideB);
        expect(r.displayed ? r.value : 0).toBe(exp.vaValue);
        expect(r.displayed ? r.side : 0).toBe({ A: 1, B: 2 }[exp.vaRecipient] ?? 0);
      });

      it("the /trade headline: adjusted totals, gap, imbalance and flows", () => {
        const a = rows(c.sideA, "a");
        const b = rows(c.sideB, "b");
        const totals = adjustedSideTotals(a, b, TRADE_VALUE_MODE);
        expect(totals[0].adjusted).toBe(exp.adjustedA);
        expect(totals[1].adjusted).toBe(exp.adjustedB);
        expect(tradeGapAdjusted(a, b, TRADE_VALUE_MODE)).toBe(exp.adjustedGap);
        const sides = [{ assets: a }, { assets: b }];
        const imb = tradeImbalance(sides, TRADE_VALUE_MODE);
        expect(imb.gap).toBe(exp.adjustedGap);
        expect(imb.imbalance).toBe(Math.abs(exp.adjustedGap));
        // 2-side identity: side B's net flow is the adjusted gap.
        const nets = computeSideFlows(sides, TRADE_VALUE_MODE).map((f) => f.net);
        expect(nets[1]).toBeCloseTo(exp.adjustedGap, 6);
      });

      it("Second Opinions: the same values through its VA path", () => {
        const res = (vs) => vs.map((value) => ({ origin: OPINION_ORIGIN.SOURCE, value }));
        const op = evaluateOpinion([res(c.sideA), res(c.sideB)], valueAdjustmentFromSideArrays);
        expect(op.state).toBe(OPINION_STATE.FULL_SOURCE);
        expect(op.adjustedTotals[0] - op.adjustedTotals[1]).toBe(exp.adjustedGap);
      });

      it("the private trade-history grade", () => {
        const [gaveA, gaveB] = gradeTradeSides([
          { got: c.sideB, gave: c.sideA },
          { got: c.sideA, gave: c.sideB },
        ]);
        expect(gaveA.netAdjusted).toBe(-exp.adjustedGap);
        expect(gaveB.netAdjusted).toBe(exp.adjustedGap);
      });
    });
  }
});
