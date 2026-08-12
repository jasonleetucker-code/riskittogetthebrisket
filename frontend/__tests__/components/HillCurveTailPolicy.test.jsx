import { describe, it, expect } from "vitest";

import { hillValue } from "../../components/graphs/HillCurveExplorer.jsx";

/**
 * W30-F023, frontend half.
 *
 * The Hill Curve Explorer plots the same curve the board is priced on. It
 * used to extrapolate smoothly forever while the backend saturated at the
 * reference population, so the picture and the board disagreed about the
 * deep tail — the chart implied the board resolved ranks it had actually
 * collapsed.
 *
 * The fix is NOT a matching tail rule written here. It is that the
 * boundary arrives in the contract (`hillCurves[*].saturationRank`,
 * stamped from `src/canonical/tail_policy`) and this component honours
 * whatever it is handed. A second transcription of the rule is the defect
 * class, not the repair.
 */

const CURVE = { midpoint: 55.89, slope: 1.11 };

describe("hillValue honours the contract's saturation boundary", () => {
  it("keeps resolving ranks inside the boundary", () => {
    const c = { ...CURVE, saturationRank: 904 };
    const deep = [501, 600, 700, 800, 903].map((r) => hillValue(r, c));
    expect(new Set(deep).size).toBe(deep.length);
    // ...and monotonically: deeper is never worth more.
    expect([...deep].sort((a, b) => b - a)).toEqual(deep);
  });

  it("saturates past the boundary instead of extrapolating", () => {
    const c = { ...CURVE, saturationRank: 904 };
    expect(hillValue(905, c)).toBe(hillValue(904, c));
    expect(hillValue(50_000, c)).toBe(hillValue(904, c));
  });

  it("follows the boundary it is given rather than a constant of its own", () => {
    // The whole point: change the contract's number, the chart moves.
    const at904 = hillValue(2000, { ...CURVE, saturationRank: 904 });
    const at600 = hillValue(2000, { ...CURVE, saturationRank: 600 });
    expect(at904).not.toBe(at600);
    expect(at600).toBe(hillValue(600, { ...CURVE, saturationRank: 600 }));
  });

  it("extrapolates when no boundary is stamped, and says so by behaviour", () => {
    // A stale cached payload predating the field must still render a
    // curve rather than collapsing to rank 1 — degrade, never fail.
    const bare = { ...CURVE };
    expect(hillValue(2000, bare)).toBeLessThan(hillValue(904, bare));
    expect(hillValue(1, bare)).toBe(9999);
  });

  it("ignores a nonsensical boundary rather than rendering NaN", () => {
    for (const bad of [null, undefined, "nope", NaN]) {
      const v = hillValue(700, { ...CURVE, saturationRank: bad });
      expect(Number.isFinite(v)).toBe(true);
      expect(v).toBeGreaterThan(0);
    }
  });

  it("still tops out at 9999 for rank 1", () => {
    expect(hillValue(1, { ...CURVE, saturationRank: 904 })).toBe(9999);
  });
});
