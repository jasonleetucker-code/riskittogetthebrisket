/**
 * TC-C — the JS mirror of the ONE fairness-band owner (owner decision 3).
 * Python twin: tests/valuation_math/test_fairness_bands.py (also pins these
 * constants to config/trade/fairness_bands.json).  Shared cases:
 * tests/fixtures/fairness_band_cases.json.
 */
import { describe, expect, it } from "vitest";
import fixture from "../../tests/fixtures/fairness_band_cases.json";
import { FAIRNESS_BANDS_VERSION, classifyGap, isFairGap } from "@/lib/fairness-bands";

describe("fairness bands (JS mirror)", () => {
  it("is the owner's version", () => {
    expect(fixture.bands).toBe(FAIRNESS_BANDS_VERSION);
  });
  for (const c of fixture.cases) {
    it(`${c.id} (${c.assetMix})`, () => {
      expect(classifyGap(c.adjustedGap, c.largerAdjusted).level).toBe(c.expectedLevel);
      expect(classifyGap(-c.adjustedGap, c.largerAdjusted).level).toBe(c.expectedLevel);
      expect(isFairGap(c.adjustedGap, c.largerAdjusted)).toBe(c.expectedLevel === "fair");
    });
  }
});
