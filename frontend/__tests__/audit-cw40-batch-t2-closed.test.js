/**
 * CW-40 Batch T2 -- frontend findings CONFIRMED CLOSED on main (2026-11-07).
 *
 *  W12-F001  rankings Edge column and the popup's Buy Low / Sell High card used different gap floors
 *            (10 ordinal ranks vs 3), so 83 rows said HOLD in the table and SELL/BUY in the popup.
 *  W12-F004  /edge's Buy / Sell rails gated, sorted and printed `sourceRankSpread` (total source
 *            dispersion) as if it were the retail-vs-consensus gap.
 *
 * Both now read the backend-stamped `marketGapDirection` / `marketGapValueRatio`; the table verdict
 * (`marketAction`) and the popup verdict (`getPlayerEdge`) are checked against EACH OTHER across a
 * sweep that includes the 3..10-rank band the audit measured, so a reintroduced second floor fails.
 */
import { describe, expect, it } from "vitest";

import { marketAction, marketGapRatioOf } from "@/lib/display-helpers";
import { getPlayerEdge } from "@/lib/trade-logic";
import { topConsensusPremium, topRetailPremium } from "@/lib/edge-helpers";
import { MARKET_GAP_MIN_VALUE_RATIO } from "@/lib/thresholds";

function row(extra) {
  return {
    name: "Test Player",
    pos: "WR",
    rank: 20,
    rankDerivedValue: 7000,
    values: { full: 7000 },
    ktcMarket: { available: true, normalizedValue: 7000 },
    marketGapDirection: "none",
    marketGapValueRatio: 0,
    ...extra,
  };
}

const RATIOS = [0, 0.01, 0.03, 0.049, 0.05, 0.051, 0.08, 0.1, 0.15, 0.3, 0.6];
const DIRECTIONS = ["retail_premium", "consensus_premium"];

describe("W12-F001: table verdict and popup verdict cannot disagree", () => {
  it.each(DIRECTIONS)("agree on every gap size (%s)", (direction) => {
    for (const ratio of RATIOS) {
      const r = row({
        marketGapDirection: direction,
        marketGapValueRatio: ratio,
        // the market value is placed consistently with the stamped direction
        ktcMarket: {
          available: true,
          normalizedValue: direction === "retail_premium" ? 7000 * (1 + ratio) : 7000 * (1 - ratio),
        },
      });
      const table = marketAction(r).kind; // buy | sell | hold | ...
      const popup = getPlayerEdge(r).signal; // BUY | SELL | null
      const expectedTable = ratio < MARKET_GAP_MIN_VALUE_RATIO
        ? "hold"
        : direction === "retail_premium"
          ? "sell"
          : "buy";
      expect(table, `table @${ratio}`).toBe(expectedTable);
      const expectedPopup = expectedTable === "hold" ? null : expectedTable.toUpperCase();
      expect(popup, `popup @${ratio}`).toBe(expectedPopup);
    }
  });

  it("a small gap (the audited 3..10-rank band) is HOLD in the table AND silent in the popup", () => {
    const r = row({ marketGapDirection: "retail_premium", marketGapValueRatio: 0.03 });
    expect(marketAction(r).kind).toBe("hold");
    expect(getPlayerEdge(r).signal).toBeNull();
  });

  it("the gap the verdict is measured on is the backend value ratio, not an ordinal", () => {
    const r = row({ marketGapDirection: "retail_premium", marketGapValueRatio: 0.2 });
    expect(marketGapRatioOf(r)).toBe(0.2);
    expect(marketGapRatioOf(row({ marketGapValueRatio: undefined }))).toBeNull();
  });
});

describe("W12-F004: /edge rails rank on the market gap, not on source dispersion", () => {
  const rows = [
    // huge dispersion, tiny gap: must NOT lead (audited: "+/-181" on a 5.9-rank gap)
    row({
      name: "Noisy",
      rank: 10,
      sourceRankSpread: 181,
      marketGapDirection: "retail_premium",
      marketGapValueRatio: 0.16,
    }),
    // tiny dispersion, large gap: must lead
    row({
      name: "Clean",
      rank: 11,
      sourceRankSpread: 4,
      marketGapDirection: "retail_premium",
      marketGapValueRatio: 0.45,
    }),
    // below the premium floor regardless of dispersion
    row({
      name: "Below",
      rank: 12,
      sourceRankSpread: 300,
      marketGapDirection: "retail_premium",
      marketGapValueRatio: 0.06,
    }),
    row({
      name: "BuyClean",
      rank: 13,
      sourceRankSpread: 2,
      marketGapDirection: "consensus_premium",
      marketGapValueRatio: 0.3,
    }),
    row({
      name: "BuyNoisy",
      rank: 14,
      sourceRankSpread: 250,
      marketGapDirection: "consensus_premium",
      marketGapValueRatio: 0.2,
    }),
  ];

  it("Sell rail orders by value ratio and drops sub-floor gaps", () => {
    const names = topRetailPremium(rows, 10).map((x) => x.name);
    expect(names).toEqual(["Clean", "Noisy"]);
  });

  it("Buy rail orders by value ratio", () => {
    expect(topConsensusPremium(rows, 10).map((x) => x.name)).toEqual(["BuyClean", "BuyNoisy"]);
  });

  it("the printed detail is the gap percentage, never a rank-spread number", () => {
    const [clean] = topRetailPremium(rows, 1);
    expect(clean.detail).toContain("45%");
    expect(clean.detail).not.toContain("181");
  });
});
