import { describe, expect, it } from "vitest";
import {
  posBadgeClass,
  confBadgeClass,
  confBadgeLabel,
  marketGapLabel,
  marketAction,
  isEligibleForBoard,
  isEligibleForAnalysis,
  idpMarketEdge,
  idpMarketAction,
  isIdpInTopByIdptc,
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
    expect(marketGapLabel({ sourceRanks: { ktcSfTep: 5, idpTradeCalc: 50 } })).toBe("KTC TE+ +45");
  });
  it("returns Consensus label when consensus mean ranks higher than KTC", () => {
    // KTC 80 vs mean(IDPTC 10) = 10 → Consensus premium 70
    expect(marketGapLabel({ sourceRanks: { ktcSfTep: 80, idpTradeCalc: 10 } })).toBe("Consensus +70");
  });
  it("averages multiple consensus sources", () => {
    // KTC 10 vs mean(IDPTC 50, DLF 70) = 60 → KTC premium 50
    expect(
      marketGapLabel({ sourceRanks: { ktcSfTep: 10, idpTradeCalc: 50, dlfIdp: 70 } })
    ).toBe("KTC TE+ +50");
  });
  it("returns null for small differences", () => {
    expect(marketGapLabel({ sourceRanks: { ktcSfTep: 10, idpTradeCalc: 15 } })).toBeNull();
  });
  it("returns null when KTC is missing", () => {
    expect(marketGapLabel({ sourceRanks: { idpTradeCalc: 20, dlfIdp: 30 } })).toBeNull();
  });
  it("returns null when only KTC is present", () => {
    expect(marketGapLabel({ sourceRanks: { ktcSfTep: 10 } })).toBeNull();
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
      sourceRanks: { ktcSfTep: 200, idpTradeCalc: 10, dlfIdp: 20 },
      effectiveSourceRanks: { idpTradeCalc: 10, dlfIdp: 20 },
    };
    // KTC dropped → no retail rank → null per the "KTC missing" rule.
    expect(marketGapLabel(row)).toBeNull();
  });
  it("falls back to sourceRanks when effectiveSourceRanks is empty", () => {
    // Legacy / pre-Hampel payloads stamp effectiveSourceRanks as {}.
    // Display helpers must still work off sourceRanks in that case.
    const row = {
      sourceRanks: { ktcSfTep: 5, idpTradeCalc: 50 },
      effectiveSourceRanks: {},
    };
    expect(marketGapLabel(row)).toBe("KTC TE+ +45");
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
    if (ktc != null) sourceRanks.ktcSfTep = ktc;
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


// ── idpMarketAction (IDP BUY / SELL / HOLD vs IDPTC) ────────────────

describe("idpMarketAction", () => {
  // Build an IDP row with IDPTC + IDP-expert ranks.
  function _idp({ idptc, dlf, ipd, fp, fbg, ds }) {
    const sourceRanks = {};
    if (idptc != null) sourceRanks.idpTradeCalc = idptc;
    if (dlf != null) sourceRanks.dlfIdp = dlf;
    if (ipd != null) sourceRanks.idpShow = ipd;
    if (fp != null) sourceRanks.fantasyProsIdp = fp;
    if (fbg != null) sourceRanks.footballGuysIdp = fbg;
    if (ds != null) sourceRanks.draftSharksIdp = ds;
    return { assetClass: "idp", pos: "LB", sourceRanks };
  }

  it("BUY when IDP experts rank well above IDPTC", () => {
    // IDPTC=50, experts mean ~12 — experts ~38 ranks above IDPTC
    const a = idpMarketAction(_idp({ idptc: 50, dlf: 10, fp: 12, fbg: 14 }));
    expect(a.label).toBe("BUY");
    expect(a.kind).toBe("buy");
    expect(a.css).toBe("edge-buy");
    expect(a.title.toLowerCase()).toContain("idptc is undervaluing");
  });

  it("SELL when IDPTC ranks well above IDP experts", () => {
    // IDPTC=10, experts mean ~55 — IDPTC ~45 ranks above
    const a = idpMarketAction(_idp({ idptc: 10, dlf: 50, fp: 55, fbg: 60 }));
    expect(a.label).toBe("SELL");
    expect(a.kind).toBe("sell");
    expect(a.css).toBe("edge-sell");
    expect(a.title.toLowerCase()).toContain("idptc is overvaluing");
  });

  it("HOLD when IDPTC and IDP experts agree within threshold", () => {
    const a = idpMarketAction(_idp({ idptc: 25, dlf: 26, fp: 24 }));
    expect(a.label).toBe("HOLD");
    expect(a.kind).toBe("hold");
  });

  it("— when only IDPTC ranks (no IDP-expert sources)", () => {
    const a = idpMarketAction(_idp({ idptc: 25 }));
    expect(a.label).toBe("—");
    expect(a.css).toBe("edge-none");
  });

  it("— when only IDP-expert sources rank (no IDPTC)", () => {
    const a = idpMarketAction(_idp({ dlf: 25, fp: 26 }));
    expect(a.label).toBe("—");
  });

  it("— when no IDP source ranks at all", () => {
    const a = idpMarketAction({ assetClass: "idp", sourceRanks: {} });
    expect(a.label).toBe("—");
  });

  it("uses effectiveSourceRanks when present (post-Hampel)", () => {
    // sourceRanks contains an IDPTC outlier; effectiveSourceRanks
    // is the post-Hampel set the backend would use.
    const row = {
      assetClass: "idp",
      sourceRanks: { idpTradeCalc: 200, dlfIdp: 50, fantasyProsIdp: 55 },
      effectiveSourceRanks: { idpTradeCalc: 50, dlfIdp: 50, fantasyProsIdp: 55 },
    };
    const a = idpMarketAction(row);
    // With effective ranks, IDPTC=50 vs experts mean ~52 → aligned →
    // idpMarketAction translates "aligned" → label "HOLD" / kind "hold"
    expect(a.kind).toBe("hold");
    expect(a.label).toBe("HOLD");
  });

  it("ignores non-IDP sources (e.g. KTC) in the consensus calculation", () => {
    // KTC's offense rank should NOT count toward IDP consensus.
    const a = idpMarketAction({
      assetClass: "idp",
      sourceRanks: { idpTradeCalc: 50, ktcSfTep: 1, dlfIdp: 12, fantasyProsIdp: 14 },
    });
    // Experts mean = (12+14)/2 = 13 vs IDPTC 50 → BUY (consensus_higher)
    expect(a.label).toBe("BUY");
  });
});


// ── isIdpInTopByIdptc ───────────────────────────────────────────────

describe("isIdpInTopByIdptc", () => {
  it("includes IDP rows ranked at or above the limit by IDPTC", () => {
    expect(
      isIdpInTopByIdptc(
        { assetClass: "idp", sourceRanks: { idpTradeCalc: 1 } },
        200,
      ),
    ).toBe(true);
    expect(
      isIdpInTopByIdptc(
        { assetClass: "idp", sourceRanks: { idpTradeCalc: 200 } },
        200,
      ),
    ).toBe(true);
  });

  it("excludes IDP rows ranked below the IDPTC limit", () => {
    expect(
      isIdpInTopByIdptc(
        { assetClass: "idp", sourceRanks: { idpTradeCalc: 201 } },
        200,
      ),
    ).toBe(false);
  });

  it("excludes IDP rows IDPTC didn't rank", () => {
    expect(
      isIdpInTopByIdptc(
        { assetClass: "idp", sourceRanks: { dlfIdp: 50 } },
        200,
      ),
    ).toBe(false);
  });

  it("excludes non-IDP rows (offense, picks)", () => {
    expect(
      isIdpInTopByIdptc(
        { assetClass: "offense", sourceRanks: { idpTradeCalc: 50 } },
        200,
      ),
    ).toBe(false);
    expect(
      isIdpInTopByIdptc(
        { assetClass: "pick", sourceRanks: { idpTradeCalc: 50 } },
        200,
      ),
    ).toBe(false);
  });

  it("excludes quarantined rows", () => {
    expect(
      isIdpInTopByIdptc(
        {
          assetClass: "idp",
          quarantined: true,
          sourceRanks: { idpTradeCalc: 50 },
        },
        200,
      ),
    ).toBe(false);
  });

  it("prefers effectiveSourceRanks over sourceRanks when present", () => {
    // sourceRanks says IDPTC=50 (in top-200); effectiveSourceRanks
    // dropped IDPTC entirely → row should be excluded.
    expect(
      isIdpInTopByIdptc(
        {
          assetClass: "idp",
          sourceRanks: { idpTradeCalc: 50 },
          effectiveSourceRanks: { dlfIdp: 50 },
        },
        200,
      ),
    ).toBe(false);
  });

  it("handles null / undefined input", () => {
    expect(isIdpInTopByIdptc(null, 200)).toBe(false);
    expect(isIdpInTopByIdptc(undefined, 200)).toBe(false);
    expect(isIdpInTopByIdptc({}, 200)).toBe(false);
  });
});


// ── idpMarketEdge — descriptor shape ────────────────────────────────

describe("idpMarketEdge", () => {
  it("returns retail_only when only IDPTC is ranked", () => {
    const e = idpMarketEdge({
      assetClass: "idp",
      sourceRanks: { idpTradeCalc: 25 },
    });
    expect(e.kind).toBe("retail_only");
    expect(e.label).toBe("IDPTC only");
  });

  it("returns consensus_only when only IDP experts ranked", () => {
    const e = idpMarketEdge({
      assetClass: "idp",
      sourceRanks: { dlfIdp: 25, fantasyProsIdp: 26 },
    });
    expect(e.kind).toBe("consensus_only");
    expect(e.label).toBe("expert only");
  });

  it("returns retail_higher with diff in label when IDPTC > experts", () => {
    const e = idpMarketEdge({
      assetClass: "idp",
      sourceRanks: { idpTradeCalc: 10, dlfIdp: 50, fantasyProsIdp: 60 },
    });
    expect(e.kind).toBe("retail_higher");
    expect(e.label).toMatch(/^IDPTC higher by \d+$/);
  });

  it("returns consensus_higher with diff in label when experts > IDPTC", () => {
    const e = idpMarketEdge({
      assetClass: "idp",
      sourceRanks: { idpTradeCalc: 50, dlfIdp: 10, fantasyProsIdp: 12 },
    });
    expect(e.kind).toBe("consensus_higher");
    expect(e.label).toMatch(/^Experts higher by \d+$/);
  });
});
