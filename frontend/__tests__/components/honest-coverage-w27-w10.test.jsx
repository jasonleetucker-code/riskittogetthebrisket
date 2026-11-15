/**
 * UI-honesty disclosures for audit W27-F001 (IDP Edge).  (The W10-F003
 * Next Best Targets half was retired with the panel; see
 * audit-w10-f003-regression.test.js.)  Display only: no detector / threshold /
 * contract field / draft math changes.
 */
import { describe, it, expect } from "vitest";

import {
  marketAction,
  marketActionDisclosed,
  IDP_EDGE_DISCLOSURE_TITLE,
} from "@/lib/display-helpers";
import { rowMatches } from "@/lib/player-filters";

const IDP = {
  name: "Abdul Carter",
  assetClass: "idp",
  position: "DL",
  marketGapDirection: "none",
  marketGapValueRatio: null,
  ktcMarket: { value: null, available: false, reason: "no_ktc_coverage" },
  rankDerivedValue: 4407,
};
const OFFENSE_SELL = {
  name: "Offense Sell",
  assetClass: "offense",
  position: "WR",
  marketGapDirection: "retail_premium",
  marketGapValueRatio: 0.2,
  ktcMarket: { value: 5000, normalizedValue: 5000, available: true },
  rankDerivedValue: 4000,
};

describe("W27-F001 disclosure", () => {
  it("IDP rows get an explicit offense-only state pointing to /edge", () => {
    const a = marketActionDisclosed(IDP);
    expect(a.label).toBe("offense only");
    expect(a.title).toBe(IDP_EDGE_DISCLOSURE_TITLE);
    expect(a.title).toContain("/edge");
    expect(a.css).toBe("edge-none");
  });
  it("offense rows are identical to marketAction", () => {
    expect(marketActionDisclosed(OFFENSE_SELL)).toEqual(marketAction(OFFENSE_SELL));
    expect(marketActionDisclosed(OFFENSE_SELL).label).toBe("SELL");
  });
  it("underlying detector/filter unchanged (still no IDP verdict)", () => {
    expect(marketAction(IDP).label).toBe("—");
    expect(rowMatches(IDP, { edge: "sell" })).toBe(false);
  });
});
