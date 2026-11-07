/**
 * Master-site-audit W12-F003 (CW-40 P1 re-adjudication, 2026-11-06) -- PARTIAL.
 *
 * August claim: FIVE different cutoffs gated the same retail-vs-consensus quantity
 * (>0, >=3, >=10, spread>=20, IDP >=10).  Today the two surfaces the audit named
 * (`getPlayerEdge` -> PlayerPopup / Edge Map, `marketAction` -> /rankings Edge column)
 * read ONE backend-stamped value-space ratio against ONE constant,
 * MARKET_GAP_MIN_VALUE_RATIO, so they cannot disagree about whether a row is
 * BUY/SELL.  The /edge premium panels use the second (PREMIUM_SUMMARY_VALUE_RATIO).
 *
 * Not pinned (still open, owner-reserved): there is no single tracker page / verdict;
 * `idpMarketAction` keeps its own IDPTC-based gate.
 */
import { describe, expect, it } from "vitest";

import { getPlayerEdge } from "@/lib/trade-logic";
import { marketAction } from "@/lib/display-helpers";
import { MARKET_GAP_MIN_VALUE_RATIO, PREMIUM_SUMMARY_VALUE_RATIO } from "@/lib/thresholds";

function row(direction, ratio) {
  return {
    rankDerivedValue: 5000,
    values: { full: 5000 },
    ktcMarket: { available: true, normalizedValue: 5000 * (1 + ratio) },
    marketGapDirection: direction,
    marketGapValueRatio: ratio,
  };
}

describe("W12-F003: one cutoff on the retail-vs-model gap", () => {
  const floor = MARKET_GAP_MIN_VALUE_RATIO;
  const cases = [];
  for (const direction of ["retail_premium", "consensus_premium"]) {
    for (const ratio of [0.01, floor - 0.001, floor, floor + 0.001, 0.2, 0.6]) {
      cases.push([direction, ratio]);
    }
  }

  it.each(cases)("popup and Rankings agree on %s at ratio %s", (direction, ratio) => {
    const edge = getPlayerEdge(row(direction, ratio));
    const action = marketAction(row(direction, ratio));
    const popupSays = edge.signal; // BUY | SELL | null
    const tableSays = action.kind === "buy" ? "BUY" : action.kind === "sell" ? "SELL" : null;
    expect(popupSays).toBe(tableSays);
    expect(popupSays === null).toBe(ratio < floor);
    if (popupSays) {
      expect(popupSays).toBe(direction === "retail_premium" ? "SELL" : "BUY");
    }
  });

  it("a missing gap is no signal on both surfaces, never a zero-gap HOLD-as-signal", () => {
    expect(getPlayerEdge({ marketGapDirection: "retail_premium" }).signal).toBeNull();
    expect(marketAction({ rankDerivedValue: 5000 }).kind).not.toBe("sell");
  });

  it("the whole retail-vs-model concept has two constants, not five", () => {
    expect(floor).toBe(0.05);
    expect(PREMIUM_SUMMARY_VALUE_RATIO).toBe(0.15);
    expect(PREMIUM_SUMMARY_VALUE_RATIO).toBeGreaterThan(floor);
  });
});
