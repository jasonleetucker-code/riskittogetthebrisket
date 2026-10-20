// TC-B / TCM-F03 — the equalizer covers COMBINATIONS: when no single asset
// lands inside the fair band, findBalancers({combos: true}) also offers
// pairs of the best singles, each pair re-simulated through the same
// tradeImbalance path the meter renders (never two raw values added up).
import { describe, expect, it } from "vitest";
import {
  BALANCER_MAX_PAIRS,
  BALANCER_PAIR_POOL,
  findBalancers,
  tradeImbalance,
} from "@/lib/trade-logic";
import { classifyGap } from "@/lib/fairness-bands";

const rowOf = (name, v, pos = "RB") => ({ name, pos, values: { full: v } });
const sidesOf = (a, b) => [
  { assets: a.map((v, i) => rowOf(`a${i}`, v, "WR")) },
  { assets: b.map((v, i) => rowOf(`b${i}`, v, "WR")) },
];
const withAdded = (sides, idx, rows) =>
  sides.map((s, i) => (i === idx ? { ...s, assets: [...s.assets, ...rows] } : s));

// Side B is far behind and its roster holds only mid-sized pieces: no one
// piece closes the gap.
const SIDES = sidesOf([9000], [3000]);
const POOL = [2600, 2400, 2200, 2000, 1800, 1500, 1200, 900, 600, 300].map((v) => rowOf(`R${v}`, v));

describe("findBalancers pairs", () => {
  it("is off by default — the single-asset contract is unchanged", () => {
    const out = findBalancers(SIDES, 1, POOL, "full");
    expect(out.length).toBeGreaterThan(0);
    expect(out.some((b) => b.isCombo)).toBe(false);
  });

  it("leads with pairs when no single lands inside the fair band", () => {
    const singles = findBalancers(SIDES, 1, POOL, "full");
    const best = singles[0];
    expect(classifyGap(best.imbalanceAfter, best.largerUtilityAfter).level).not.toBe("fair");

    const out = findBalancers(SIDES, 1, POOL, "full", { combos: true });
    const pairs = out.filter((b) => b.isCombo);
    expect(pairs.length).toBeGreaterThan(0);
    expect(pairs.length).toBeLessThanOrEqual(BALANCER_MAX_PAIRS);
    // Pairs first, then the unchanged singles.
    expect(out.slice(0, pairs.length).every((b) => b.isCombo)).toBe(true);
    expect(out.slice(pairs.length)).toEqual(singles);
    for (const p of pairs) {
      expect(p.entries).toHaveLength(2);
      // Simulated whole, through the meter's own path.
      const truth = tradeImbalance(withAdded(SIDES, 1, p.entries), "full");
      expect(p.imbalanceAfter).toBe(truth.imbalance);
      expect(p.imbalanceAfter).toBeLessThan(best.imbalanceAfter);
      // Its pieces come from the best singles only (bounded search).
      const top = new Set(singles.concat(findBalancers(SIDES, 1, POOL, "full", { maxResults: BALANCER_PAIR_POOL })).map((s) => s.key));
      for (const e of p.entries) expect(top.has(e.name)).toBe(true);
    }
    // Ordered by landing.
    for (let i = 1; i < pairs.length; i += 1) {
      expect(pairs[i].imbalanceAfter).toBeGreaterThanOrEqual(pairs[i - 1].imbalanceAfter);
    }
  });

  it("offers no pair when a single asset already lands inside the fair band", () => {
    const sides = sidesOf([5000], [4000]);
    const pool = [rowOf("Close", 1282, "QB"), rowOf("Small", 300)];
    const out = findBalancers(sides, 1, pool, "full", { combos: true });
    expect(classifyGap(out[0].imbalanceAfter, out[0].largerUtilityAfter).level).toBe("fair");
    expect(out.some((b) => b.isCombo)).toBe(false);
  });

  it("never pairs an unpriced row (missing is never zero)", () => {
    const pool = [...POOL, { name: "Unpriced", pos: "RB", values: { full: null } }];
    const out = findBalancers(SIDES, 1, pool, "full", { combos: true });
    for (const b of out) {
      for (const e of b.entries || [b.entry]) expect(e.name).not.toBe("Unpriced");
    }
  });
});
