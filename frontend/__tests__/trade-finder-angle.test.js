// /angle threshold copy: the server's market gate is a CEILING only
// (src/trade/angle.py: `if market_gain_pct > max_market_gain_pct: reject`), and
// the numbers must be the thresholds the server applied to the result, not the
// live form inputs.
import { describe, expect, it } from "vitest";
import {
  angleNoResultDescription,
  angleResultsSubtitle,
  appliedAngleThresholds,
} from "@/lib/trade-finder-angle";

const result = (thresholds) => ({ mode: "offer", candidates: [], thresholds });

describe("angle threshold copy", () => {
  it("reads the server's applied thresholds", () => {
    expect(appliedAngleThresholds(result({ min_my_gain_pct: 7, max_market_gain_pct: 3 }))).toEqual({
      minMyGain: 7,
      maxMarketGap: 3,
    });
  });

  it("words the market gate as an upper bound, never a ± band", () => {
    const text = angleResultsSubtitle(result({ min_my_gain_pct: 7, max_market_gain_pct: 3 }));
    expect(text).toBe(
      "Each package gains at least +7% on your board, and on the market the other side consults you receive at most +3% more than you give (a ceiling only — the market gap can be lower).",
    );
    expect(text).not.toContain("±");
    expect(text).not.toMatch(/stays within/);
  });

  it("formats zero, negative and fractional thresholds honestly", () => {
    const text = angleResultsSubtitle(result({ min_my_gain_pct: 0, max_market_gain_pct: -2.5 }));
    expect(text).toContain("at least 0%");
    expect(text).toContain("at most -2.5%");
  });

  it("missing thresholds name no number at all — never the form inputs", () => {
    for (const r of [result(undefined), result({ min_my_gain_pct: 5 }), result({ min_my_gain_pct: "5", max_market_gain_pct: 5 }), null]) {
      expect(appliedAngleThresholds(r)).toBeNull();
      const text = angleResultsSubtitle(r);
      expect(text).not.toMatch(/\d/);
      expect(text).toMatch(/did not report/);
    }
  });

  it("the empty state uses the same applied thresholds", () => {
    expect(angleNoResultDescription(result({ min_my_gain_pct: 10, max_market_gain_pct: 1 }), "Rivals")).toBe(
      "Nothing gains at least +10% on your board with a market gap of at most +1% with this selection against Rivals. Try a different selection, loosen the thresholds under Advanced, or remove the team filter.",
    );
    const missing = angleNoResultDescription(result(undefined), "");
    expect(missing).not.toMatch(/\d/);
    expect(missing).not.toContain("±");
  });
});
