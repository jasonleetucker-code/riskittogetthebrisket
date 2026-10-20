/**
 * N-team package-math parity, JavaScript half (spec
 * docs/trade/NTEAM_TRADE_ENGINE_SPEC.md I12).
 *
 * tests/fixtures/multi_team_trade_parity_cases.json carries, per team of a
 * routed multi-team trade, the value arrays it gives and receives and the
 * Python owners' answer (package_model.adjusted_pair_totals over
 * (gives, receives), gap = recvAdj - sendAdj, fairness_bands.classify).  The
 * browser's existing primitives — packageAdjustPair (the package-model
 * dispatch) and classifyGap (the fairness-band mirror) — must reproduce every
 * team's numbers from the same arrays.  Only the PURE math is in scope; value
 * resolution is a separate seam (spec §5.1 item 9).
 *
 * The per-team composition below is the spec's §5.1 rule written with the
 * existing exports; Lane B's packageAdjustedPairTotals must equal it.
 */
import { describe, expect, it } from "vitest";
import fixture from "../../tests/fixtures/multi_team_trade_parity_cases.json";
import {
  ACTIVE_PACKAGE_MODEL_ID,
  packageAdjustPair,
  packageAdjustedPairTotals,
} from "@/lib/trade-logic";
import { classifyGap } from "@/lib/fairness-bands";

const positive = (xs) => xs.filter((v) => Number.isFinite(v) && v > 0);
const leftSum = (xs) => xs.reduce((acc, v) => acc + v, 0);

// The spec §5.1 per-team rule: the FIRST argument is the team's gives.
function teamTotals(gives, receives) {
  const g = positive(gives);
  const r = positive(receives);
  const sendRaw = leftSum(g);
  const recvRaw = leftSum(r);
  if (g.length === 0 || r.length === 0) {
    return { sendAdj: sendRaw, recvAdj: recvRaw, sendVA: 0, recvVA: 0 };
  }
  const { value, side, displayed } = packageAdjustPair(g, r);
  if (!displayed || value <= 0) {
    return { sendAdj: sendRaw, recvAdj: recvRaw, sendVA: 0, recvVA: 0 };
  }
  return side === 1
    ? { sendAdj: sendRaw + value, recvAdj: recvRaw, sendVA: value, recvVA: 0 }
    : { sendAdj: sendRaw, recvAdj: recvRaw + value, sendVA: 0, recvVA: value };
}

describe("multi-team package math parity (I12)", () => {
  it("the fixture is for the active package model", () => {
    expect(fixture.model).toBe(ACTIVE_PACKAGE_MODEL_ID);
    expect(fixture.cases.length).toBeGreaterThanOrEqual(6);
  });

  for (const c of fixture.cases) {
    describe(c.id, () => {
      for (const [team, t] of Object.entries(c.teams)) {
        it(`team ${team}: adjusted totals, VA, gap and band`, () => {
          const exp = t.expected;
          const got = teamTotals(t.gives, t.receives);
          // Lane B's JS twin of adjusted_pair_totals is the same composition.
          const twin = packageAdjustedPairTotals(t.gives, t.receives);
          expect(twin.sendVA).toBe(got.sendVA);
          expect(twin.recvVA).toBe(got.recvVA);
          expect(twin.sendAdj).toBe(got.sendAdj);
          expect(twin.recvAdj).toBe(got.recvAdj);
          expect(got.sendVA).toBe(exp.sendVA);
          expect(got.recvVA).toBe(exp.recvVA);
          expect(got.sendAdj).toBeCloseTo(exp.sendAdj, 6);
          expect(got.recvAdj).toBeCloseTo(exp.recvAdj, 6);
          const gap = got.recvAdj - got.sendAdj;
          expect(gap).toBeCloseTo(exp.gap, 6);
          const larger = Math.max(got.sendAdj, got.recvAdj);
          expect(larger).toBeCloseTo(exp.larger, 6);
          const band = classifyGap(gap, larger);
          expect(band.level).toBe(exp.level);
        });
      }
    });
  }

  it("a one-for-one cycle's per-team gaps sum to zero", () => {
    const c = fixture.cases.find(
      (x) => x.id === "three_team_cycle_one_for_one",
    );
    const total = Object.values(c.teams)
      .map((t) => {
        const r = teamTotals(t.gives, t.receives);
        return r.recvAdj - r.sendAdj;
      })
      .reduce((a, b) => a + b, 0);
    expect(total).toBe(0);
  });
});
