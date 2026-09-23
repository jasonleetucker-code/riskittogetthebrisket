import { describe, expect, it } from "vitest";
import {
  posBadgeClass,
  confBadgeClass,
  confBadgeLabel,
  marketGapLabel,
  marketEdge,
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

// Rank -> per-source value stamp.  The market gap is measured in VALUE
// space now (sourceRankMeta[key].valueContribution), because differencing
// raw ordinals across pools of unequal depth measured pool depth and TE
// format basis rather than opinion.  These fixtures were written in ranks,
// so this keeps each case's INTENT — "source A rates him well above B" —
// while expressing it in the units the helper actually reads.  Monotone
// decreasing, so a better (lower) rank is a higher value.
function _valueFor(rank) {
  return 10000 - Number(rank) * 100;
}
function _metaFrom(sourceRanks) {
  const meta = {};
  for (const [key, rank] of Object.entries(sourceRanks)) {
    if (rank != null) meta[key] = { valueContribution: _valueFor(rank) };
  }
  return meta;
}

describe("marketGapLabel", () => {
  const row = (direction, ratio, model = 5000, market = 6000) => ({
    rankDerivedValue: model,
    ktcMarket: { available: true, value: market, normalizedValue: market },
    marketGapDirection: direction,
    marketGapValueRatio: ratio,
  });
  it("names KTC Market when the market prices the asset higher", () => {
    expect(marketGapLabel(row("retail_premium", 0.62))).toBe("KTC Market +62%");
  });
  it("names our model when it prices the asset higher", () => {
    expect(marketGapLabel(row("consensus_premium", 0.27))).toBe("Model +27%");
  });
  it("returns null for small differences", () => {
    expect(marketGapLabel(row("retail_premium", 0.02))).toBeNull();
  });
  it("returns null when KTC Market is missing", () => {
    expect(
      marketGapLabel({ rankDerivedValue: 5000, ktcMarket: { available: false }, marketGapValueRatio: null }),
    ).toBeNull();
  });
  it("returns null for no stamps", () => {
    expect(marketGapLabel({})).toBeNull();
  });
  it("returns null for null row", () => {
    expect(marketGapLabel(null)).toBeNull();
  });
});

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
  // OUR MODEL vs canonical KTC MARKET (owner directive 2026-09-23): the
  // backend stamps ktcMarket + marketGapDirection/marketGapValueRatio and
  // these helpers only format them — nothing is recomputed client-side.
  function _row({ model, market, direction, ratio }) {
    const row = {};
    if (model != null) row.rankDerivedValue = model;
    if (market != null) row.ktcMarket = { available: true, value: market, normalizedValue: market };
    else row.ktcMarket = { available: false, value: null, reason: "no_ktc_coverage" };
    row.marketGapDirection = direction ?? "none";
    row.marketGapValueRatio = ratio ?? null;
    return row;
  }

  it("BUY when our model prices the asset above KTC Market", () => {
    const a = marketAction(_row({ model: 6000, market: 5000, direction: "consensus_premium", ratio: 0.18 }));
    expect(a.label).toBe("BUY");
    expect(a.kind).toBe("buy");
    expect(a.css).toBe("edge-buy");
  });

  it("SELL when KTC Market prices the asset above our model", () => {
    const a = marketAction(_row({ model: 5000, market: 6000, direction: "retail_premium", ratio: 0.18 }));
    expect(a.label).toBe("SELL");
    expect(a.kind).toBe("sell");
    expect(a.css).toBe("edge-sell");
  });

  it("HOLD when the two are within the display threshold", () => {
    const a = marketAction(_row({ model: 5000, market: 5050, direction: "retail_premium", ratio: 0.01 }));
    expect(a.label).toBe("HOLD");
    expect(a.kind).toBe("hold");
    expect(a.css).toBe("edge-hold");
  });

  it("— when KTC Market does not price the asset (IDP)", () => {
    const a = marketAction(_row({ model: 4000 }));
    expect(a.label).toBe("—");
    expect(a.css).toBe("edge-none");
    expect(marketEdge(_row({ model: 4000 })).kind).toBe("consensus_only");
  });

  it("— when only KTC Market prices the asset", () => {
    const a = marketAction(_row({ market: 4000 }));
    expect(a.label).toBe("—");
    expect(marketEdge(_row({ market: 4000 })).kind).toBe("retail_only");
  });

  it("— when neither side is available", () => {
    expect(marketAction({}).label).toBe("—");
    expect(marketAction({ sourceRanks: {} }).label).toBe("—");
  });

  it("title surfaces direction context", () => {
    const a = marketAction(_row({ model: 6000, market: 5000, direction: "consensus_premium", ratio: 0.18 }));
    expect(a.title.toLowerCase()).toContain("market is undervaluing");
  });

  it("never recomputes from per-source ranks", () => {
    // Source ranks that WOULD have read as a retail premium under the retired
    // client-side split change nothing: only the backend stamps are read.
    const row = _row({ model: 6000, market: 5000, direction: "consensus_premium", ratio: 0.18 });
    row.sourceRanks = { ktcCrowdSfTep: 1, dlfSf: 400 };
    expect(marketAction(row).label).toBe("BUY");
  });
});

describe("idpMarketAction", () => {
  // Build an IDP row with IDPTC + IDP-expert ranks.
  function _idp({ idptc, dlf, ipd, fp, fbg, ds }) {
    const sourceRanks = {};
    if (idptc != null) sourceRanks.idpTradeCalc = idptc;
    if (dlf != null) sourceRanks.dlfIdp = dlf;
    if (ipd != null) sourceRanks.idpShowCombined = ipd;
    if (fp != null) sourceRanks.fantasyProsIdp = fp;
    if (ds != null) sourceRanks.draftSharksIdp = ds;
    return {
      assetClass: "idp",
      pos: "LB",
      sourceRanks,
      sourceRankMeta: _metaFrom(sourceRanks),
    };
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
      effectiveSourceRanks: { idpTradeCalc: 50, dlfIdp: 50, fantasyProsIdp: 51 },
    };
    row.sourceRankMeta = _metaFrom(row.effectiveSourceRanks);
    const a = idpMarketAction(row);
    // What this pins is that the EFFECTIVE set is what gets read — the
    // sourceRanks outlier (IDPTC 200) must not reach the comparison.
    // The expert rank was 55 when the gap was measured in ordinals;
    // under _valueFor that is 5000 vs 4750, a 5.1% gap that clears the
    // 5% gate, so the fixture would have been testing the threshold
    // rather than the source selection. 51 keeps the two sides genuinely
    // aligned in the units the helper now reads.
    expect(a.kind).toBe("hold");
    expect(a.label).toBe("HOLD");
  });

  it("ignores non-IDP sources (e.g. KTC) in the consensus calculation", () => {
    // KTC's offense rank should NOT count toward IDP consensus.
    const nonIdpRanks = { idpTradeCalc: 50, ktcCrowdTradesSfTep: 1, dlfIdp: 12, fantasyProsIdp: 14 };
    const a = idpMarketAction({
      assetClass: "idp",
      sourceRanks: nonIdpRanks,
      sourceRankMeta: _metaFrom(nonIdpRanks),
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
    const ranks = { idpTradeCalc: 10, dlfIdp: 50, fantasyProsIdp: 60 };
    const e = idpMarketEdge({
      assetClass: "idp",
      sourceRanks: ranks,
      sourceRankMeta: _metaFrom(ranks),
    });
    expect(e.kind).toBe("retail_higher");
    expect(e.label).toMatch(/^IDPTC higher by \d+%$/);
  });

  it("returns consensus_higher with diff in label when experts > IDPTC", () => {
    const ranks = { idpTradeCalc: 50, dlfIdp: 10, fantasyProsIdp: 12 };
    const e = idpMarketEdge({
      assetClass: "idp",
      sourceRanks: ranks,
      sourceRankMeta: _metaFrom(ranks),
    });
    expect(e.kind).toBe("consensus_higher");
    expect(e.label).toMatch(/^Experts higher by \d+%$/);
  });
});
