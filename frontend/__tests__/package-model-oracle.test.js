/**
 * Independent oracle for the ACTIVE package model geom_q078_v1 — JS owner.
 * The expected values are the hand-computed table (arithmetic per row) plus an
 * exact-rational seeded sweep written from the spec; both live in
 * tests/fixtures/package_model_oracle_cases.json and are ALSO pinned on the
 * Python owner by tests/valuation_math/test_package_model_oracle.py, so the two
 * owners are held to one oracle.  QA directive 2026-11-06 (CW-49 Phase 2).
 */
import { describe, expect, it } from "vitest";
import oracle from "../../tests/fixtures/package_model_oracle_cases.json";
import {
  ACTIVE_PACKAGE_MODEL_ID,
  PACKAGE_MODEL_IDS,
  geomPackageUtility,
  packageAdjustPair,
} from "@/lib/trade-logic";

const GEOM = PACKAGE_MODEL_IDS.GEOM_Q078_V1;
const sum = (a) => a.reduce((s, v) => s + v, 0);
const pos = (a) => a.filter((v) => v > 0);

function gap(a, b) {
  const r = packageAdjustPair(a, b, { modelId: GEOM });
  const vaA = r.displayed && r.side === 1 ? r.value : 0;
  const vaB = r.displayed && r.side === 2 ? r.value : 0;
  return sum(pos(a)) + vaA - (sum(pos(b)) + vaB);
}

// mulberry32 — seeded, deterministic
function rng(seed) {
  let t = seed >>> 0;
  return () => {
    t += 0x6d2b79f5;
    let x = Math.imul(t ^ (t >>> 15), 1 | t);
    x ^= x + Math.imul(x ^ (x >>> 7), 61 | x);
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

describe("geom_q078_v1 independent oracle (JS owner)", () => {
  it("is the active model with q = 0.78", () => {
    expect(ACTIVE_PACKAGE_MODEL_ID).toBe(GEOM);
    expect(oracle.q).toBe(0.78);
  });

  for (const c of oracle.handCases) {
    it(`hand-computed: ${c.name}`, () => {
      const r = packageAdjustPair(c.team1, c.team2);
      expect({ value: r.value, side: r.side }).toEqual({ value: c.value, side: c.side });
      expect(r.displayed).toBe(c.value > 0);
    });
  }

  it("matches the exact-rational seeded sweep (150 cases)", () => {
    for (const c of oracle.randomSweep) {
      const r = packageAdjustPair(c.team1, c.team2);
      expect({ value: r.value, side: r.side }).toEqual({ value: c.value, side: c.side });
    }
  });

  it("Math.round is half-up on positive .5 boundaries", () => {
    for (const [x, e] of [
      [0.5, 1],
      [1.5, 2],
      [2.5, 3],
      [880.5, 881],
      [0.49999, 0],
    ]) {
      expect(Math.round(x)).toBe(e);
    }
  });

  it("properties over a seeded sweep: permutation, antisymmetry, U-gap, monotone U", () => {
    const rand = rng(20261106);
    const ri = (n) => Math.floor(rand() * n);
    const mk = () => Array.from({ length: 1 + ri(6) }, () => ri(10000));
    for (let i = 0; i < 1500; i++) {
      const a = mk();
      const b = mk();
      const a2 = [...a].reverse();
      expect(packageAdjustPair(a, b)).toEqual(packageAdjustPair(a2, b));
      expect(gap(a, b)).toBe(-gap(b, a));
      if (pos(a).length && pos(b).length) {
        const uGap = geomPackageUtility(a) - geomPackageUtility(b);
        expect(Math.abs(gap(a, b) - uGap)).toBeLessThanOrEqual(0.5 + 1e-6);
      }
      expect(geomPackageUtility([...a, 1 + ri(9999)])).toBeGreaterThanOrEqual(
        geomPackageUtility(a),
      );
    }
  });
});
