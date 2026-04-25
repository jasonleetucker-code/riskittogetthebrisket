import { describe, expect, it } from "vitest";
import {
  posBadgeClass,
  confBadgeClass,
  confBadgeLabel,
  marketGapLabel,
  marketAction,
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
  it("returns green badge for pick", () => {
    // Picks get a distinct green badge so users can spot draft picks
    // inline alongside offense (cyan) and IDP (amber) rows.
    expect(posBadgeClass({ assetClass: "pick" })).toBe("badge badge-green");
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
  it("returns KTC label when KTC ranks higher than consensus mean", () => {
    // KTC 5 vs mean(IDPTC 50) = 50 → KTC premium 45
    expect(marketGapLabel({ sourceRanks: { ktc: 5, idpTradeCalc: 50 } })).toBe("KTC +45");
  });
  it("returns Consensus label when consensus mean ranks higher than KTC", () => {
    // KTC 80 vs mean(IDPTC 10) = 10 → Consensus premium 70
    expect(marketGapLabel({ sourceRanks: { ktc: 80, idpTradeCalc: 10 } })).toBe("Consensus +70");
  });
  it("averages multiple consensus sources", () => {
    // KTC 10 vs mean(IDPTC 50, DLF 70) = 60 → KTC premium 50
    expect(
      marketGapLabel({ sourceRanks: { ktc: 10, idpTradeCalc: 50, dlfIdp: 70 } })
    ).toBe("KTC +50");
  });
  it("returns null for small differences", () => {
    expect(marketGapLabel({ sourceRanks: { ktc: 10, idpTradeCalc: 15 } })).toBeNull();
  });
  it("returns null when KTC is missing", () => {
    expect(marketGapLabel({ sourceRanks: { idpTradeCalc: 20, dlfIdp: 30 } })).toBeNull();
  });
  it("returns null when only KTC is present", () => {
    expect(marketGapLabel({ sourceRanks: { ktc: 10 } })).toBeNull();
  });
  it("returns null for no sourceRanks", () => {
    expect(marketGapLabel({})).toBeNull();
  });
  it("returns null for null row", () => {
    expect(marketGapLabel(null)).toBeNull();
  });
  it("prefers effectiveSourceRanks over sourceRanks when present", () => {
    // sourceRanks contains a Hampel-dropped outlier (ktc: 200) that
    // would otherwise pull the retail mean way out.  effectiveSourceRanks
    // reflects the post-Hampel set the backend uses for its own
    // marketGapDirection — frontend must agree.
    const row = {
      sourceRanks: { ktc: 200, idpTradeCalc: 10, dlfIdp: 20 },
      effectiveSourceRanks: { idpTradeCalc: 10, dlfIdp: 20 },
    };
    // KTC dropped → no retail rank → null per the "KTC missing" rule.
    expect(marketGapLabel(row)).toBeNull();
  });
  it("falls back to sourceRanks when effectiveSourceRanks is empty", () => {
    // Legacy / pre-Hampel payloads stamp effectiveSourceRanks as {}.
    // Display helpers must still work off sourceRanks in that case.
    const row = {
      sourceRanks: { ktc: 5, idpTradeCalc: 50 },
      effectiveSourceRanks: {},
    };
    expect(marketGapLabel(row)).toBe("KTC +45");
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
  it("includes draft picks", () => {
    // Picks are priced by KTC and IDPTradeCalc on the same 0-9999
    // scale as players, get full unified ranks from the backend, and
    // must render alongside players on the rankings board.
    expect(isEligibleForBoard({ pos: "PICK" })).toBe(true);
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


// ── marketAction (BUY / SELL / HOLD) ────────────────────────────────

describe("marketAction", () => {
  // Build a row with rank dict matching the retail/expert split.
  // Retail = ktc by default; everything else = expert/consensus.
  function _row({ ktc, dlf, fc }) {
    const sourceRanks = {};
    if (ktc != null) sourceRanks.ktc = ktc;
    if (dlf != null) sourceRanks.dlf = dlf;
    if (fc != null) sourceRanks.fc = fc;
    return { sourceRanks };
  }

  it("BUY when experts rank well above retail (consensus_higher)", () => {
    // ktc=50, experts=10/12 — experts 38+ ranks above retail.
    const r = _row({ ktc: 50, dlf: 10, fc: 12 });
    const a = marketAction(r);
    expect(a.label).toBe("BUY");
    expect(a.kind).toBe("buy");
    expect(a.css).toBe("edge-buy");
  });

  it("SELL when retail ranks well above experts (retail_higher)", () => {
    // ktc=10, experts=50/55 — market overvalues.
    const r = _row({ ktc: 10, dlf: 50, fc: 55 });
    const a = marketAction(r);
    expect(a.label).toBe("SELL");
    expect(a.kind).toBe("sell");
    expect(a.css).toBe("edge-sell");
  });

  it("HOLD when sides are aligned within threshold", () => {
    const r = _row({ ktc: 25, dlf: 26, fc: 24 });
    const a = marketAction(r);
    expect(a.label).toBe("HOLD");
    expect(a.kind).toBe("hold");
    expect(a.css).toBe("edge-hold");
  });

  it("— when only retail (consensus_only would be inverse here)", () => {
    const r = _row({ ktc: 25 });
    const a = marketAction(r);
    expect(a.label).toBe("—");
    expect(a.css).toBe("edge-none");
  });

  it("— when only experts", () => {
    const r = _row({ dlf: 25, fc: 26 });
    const a = marketAction(r);
    expect(a.label).toBe("—");
    expect(a.css).toBe("edge-none");
  });

  it("— when no source ranks at all", () => {
    expect(marketAction({}).label).toBe("—");
    expect(marketAction({ sourceRanks: {} }).label).toBe("—");
  });

  it("title surfaces direction context", () => {
    const a = marketAction(_row({ ktc: 50, dlf: 10, fc: 12 }));
    expect(a.title.toLowerCase()).toContain("market is undervaluing");
  });
});
