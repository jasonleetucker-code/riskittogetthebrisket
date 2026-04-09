import { describe, expect, it } from "vitest";
import {
  posBadgeClass,
  confBadgeClass,
  confBadgeLabel,
  marketGapLabel,
  isEligibleForBoard,
  isEligibleForAnalysis,
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

// ── isEligibleForBoard ──────────────────────────────────────────────

describe("isEligibleForBoard", () => {
  it("includes offense positions", () => {
    expect(isEligibleForBoard({ pos: "QB" })).toBe(true);
    expect(isEligibleForBoard({ pos: "WR" })).toBe(true);
  });
  it("includes IDP positions", () => {
    expect(isEligibleForBoard({ pos: "DL" })).toBe(true);
    expect(isEligibleForBoard({ pos: "LB" })).toBe(true);
  });
  it("excludes PICK", () => {
    expect(isEligibleForBoard({ pos: "PICK" })).toBe(false);
  });
  it("excludes unknown position", () => {
    expect(isEligibleForBoard({ pos: "?" })).toBe(false);
  });
  it("excludes missing position", () => {
    expect(isEligibleForBoard({ pos: "" })).toBe(false);
    expect(isEligibleForBoard({})).toBe(false);
    expect(isEligibleForBoard(null)).toBe(false);
  });
});

// ── isEligibleForAnalysis ───────────────────────────────────────────

describe("isEligibleForAnalysis", () => {
  it("requires rank in addition to board eligibility", () => {
    expect(isEligibleForAnalysis({ pos: "QB", rank: 1 })).toBe(true);
    expect(isEligibleForAnalysis({ pos: "QB" })).toBe(false);
    expect(isEligibleForAnalysis({ pos: "QB", rank: 0 })).toBe(false);
  });
  it("excludes PICK even with rank", () => {
    expect(isEligibleForAnalysis({ pos: "PICK", rank: 1 })).toBe(false);
  });
  it("handles null", () => {
    expect(isEligibleForAnalysis(null)).toBe(false);
  });
});
