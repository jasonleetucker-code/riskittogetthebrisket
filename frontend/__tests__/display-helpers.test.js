import { describe, expect, it } from "vitest";
import {
  posBadgeClass,
  confBadgeClass,
  confBadgeLabel,
  marketGapLabel,
} from "../lib/display-helpers.js";

describe("posBadgeClass", () => {
  it("returns cyan for offense", () => {
    expect(posBadgeClass({ assetClass: "offense" })).toBe("badge badge-cyan");
  });
  it("returns amber for idp", () => {
    expect(posBadgeClass({ assetClass: "idp" })).toBe("badge badge-amber");
  });
  it("returns plain badge for pick", () => {
    expect(posBadgeClass({ assetClass: "pick" })).toBe("badge");
  });
  it("handles null row", () => {
    expect(posBadgeClass(null)).toBe("badge");
  });
});

describe("confBadgeClass", () => {
  it("returns green for high", () => {
    expect(confBadgeClass("high")).toBe("badge badge-green");
  });
  it("returns amber for medium", () => {
    expect(confBadgeClass("medium")).toBe("badge badge-amber");
  });
  it("returns red for low", () => {
    expect(confBadgeClass("low")).toBe("badge badge-red");
  });
  it("returns red for none", () => {
    expect(confBadgeClass("none")).toBe("badge badge-red");
  });
});

describe("confBadgeLabel", () => {
  it("returns High for high", () => {
    expect(confBadgeLabel("high")).toBe("High");
  });
  it("returns Med for medium", () => {
    expect(confBadgeLabel("medium")).toBe("Med");
  });
  it("returns Low for low", () => {
    expect(confBadgeLabel("low")).toBe("Low");
  });
  it("returns Low for unknown", () => {
    expect(confBadgeLabel("none")).toBe("Low");
  });
});

describe("marketGapLabel", () => {
  it("returns KTC label when KTC ranks higher", () => {
    expect(marketGapLabel({ sourceRanks: { ktc: 5, idpTradeCalc: 50 } })).toBe("KTC +45");
  });
  it("returns IDPTC label when IDPTC ranks higher", () => {
    expect(marketGapLabel({ sourceRanks: { ktc: 80, idpTradeCalc: 10 } })).toBe("IDPTC +70");
  });
  it("returns null for small differences", () => {
    expect(marketGapLabel({ sourceRanks: { ktc: 10, idpTradeCalc: 15 } })).toBeNull();
  });
  it("returns null when missing sources", () => {
    expect(marketGapLabel({ sourceRanks: { ktc: 10 } })).toBeNull();
  });
  it("returns null for no sourceRanks", () => {
    expect(marketGapLabel({})).toBeNull();
  });
  it("returns null for null row", () => {
    expect(marketGapLabel(null)).toBeNull();
  });
});
