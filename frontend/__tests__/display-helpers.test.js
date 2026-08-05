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
  // REVERSAL RECORDED IN PLACE (audit S-1/C19 + S-4/C10, batch C4).
  //
  // These tests used to feed `sourceRanks` in and assert ordinal
  // arithmetic on the way out — `{ktcSfTep: 5, idpTradeCalc: 50}` was
  // expected to render "KTC +45". That asserted TWO defects as correct:
  //
  //   1. that a rank difference of 45 means the same thing on boards
  //      278 and 900 rows deep (it does not — normalizing flipped the
  //      sign on 42% of offense rows), and
  //   2. that this function should compute the gap AT ALL. It was a
  //      client-side reimplementation of the backend's
  //      `_compute_market_gap`, i.e. a second authority for a number the
  //      contract already stamps — the same shape as the
  //      `computeUnifiedRanks` fallback that was removed from buildRows.
  //
  // Both are gone. The helper now reads `marketGapDirection` /
  // `marketGapMagnitude` verbatim, and the number is rank-space
  // per-mille net of positional basis, not an ordinal rank gap.
  it("renders the backend's retail premium", () => {
    expect(
      marketGapLabel({ marketGapDirection: "retail_premium", marketGapMagnitude: 45 })
    ).toBe("KTC +45");
  });
  it("renders the backend's consensus premium", () => {
    expect(
      marketGapLabel({ marketGapDirection: "consensus_premium", marketGapMagnitude: 70 })
    ).toBe("Consensus +70");
  });
  it("rounds the magnitude for display", () => {
    expect(
      marketGapLabel({ marketGapDirection: "retail_premium", marketGapMagnitude: 50.4 })
    ).toBe("KTC +50");
  });
  it("returns null below the label threshold", () => {
    expect(
      marketGapLabel({ marketGapDirection: "retail_premium", marketGapMagnitude: 5 })
    ).toBeNull();
  });
  it("returns null when the backend reported no direction", () => {
    expect(
      marketGapLabel({ marketGapDirection: "none", marketGapUnknown: { reason: "consensus_only" } })
    ).toBeNull();
  });
  it("returns null for an unstamped row", () => {
    expect(marketGapLabel({})).toBeNull();
  });
  it("returns null for null row", () => {
    expect(marketGapLabel(null)).toBeNull();
  });
  it("IGNORES per-source ranks entirely", () => {
    // The guard on the no-frontend-recompute rule: a row whose raw
    // ranks scream "huge retail premium" but which the backend did not
    // stamp must render nothing. If this ever returns a label again,
    // the client-side gap engine has grown back.
    expect(
      marketGapLabel({
        sourceRanks: { ktcSfTep: 5, idpTradeCalc: 500 },
        effectiveSourceRanks: { ktcSfTep: 5, idpTradeCalc: 500 },
      })
    ).toBeNull();
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
  // REVERSAL RECORDED IN PLACE (batch C4). These rows used to be built
  // from `sourceRanks` and the verb derived by re-averaging them on the
  // client. The helper now reads the backend's stamps, so the fixtures
  // are stamps — which is also the point: there is one place a BUY/SELL
  // verb can come from, and it is the contract.
  const stamped = (direction, magnitude, extra = {}) => ({
    marketGapDirection: direction,
    marketGapMagnitude: magnitude,
    ...extra,
  });

  it("BUY when experts rank above retail (consensus_premium)", () => {
    const a = marketAction(stamped("consensus_premium", 80));
    expect(a.label).toBe("BUY");
    expect(a.kind).toBe("buy");
    expect(a.css).toBe("edge-buy");
  });

  it("SELL when retail ranks above experts (retail_premium)", () => {
    const a = marketAction(stamped("retail_premium", 80));
    expect(a.label).toBe("SELL");
    expect(a.kind).toBe("sell");
    expect(a.css).toBe("edge-sell");
  });

  it("HOLD when the gap is below the label threshold", () => {
    const a = marketAction(stamped("retail_premium", 3));
    expect(a.label).toBe("HOLD");
    expect(a.kind).toBe("hold");
    expect(a.css).toBe("edge-hold");
  });

  it("HOLD on a measured tie", () => {
    const a = marketAction(stamped("none", 0));
    expect(a.label).toBe("HOLD");
    expect(a.kind).toBe("hold");
  });

  it("— when only retail ranked the player", () => {
    const a = marketAction(stamped("none", null, { marketGapUnknown: { reason: "retail_only" } }));
    expect(a.label).toBe("—");
    expect(a.kind).toBe("retail_only");
    expect(a.css).toBe("edge-none");
  });

  it("— when only the experts did, which is every defender", () => {
    // The retail anchor publishes no IDP, so all 386 IDP rows on the
    // live board land here. Before C4 this was indistinguishable from a
    // tie, which is why the gap being unavailable for half the board
    // was invisible.
    const a = marketAction(
      stamped("none", null, { marketGapUnknown: { reason: "consensus_only" } })
    );
    expect(a.label).toBe("—");
    expect(a.kind).toBe("consensus_only");
  });

  it("— when the positional basis could not be established", () => {
    const a = marketAction(
      stamped("none", null, {
        marketGapUnknown: { reason: "position_sample_too_small", detail: "too few" },
      })
    );
    expect(a.label).toBe("—");
    expect(a.kind).toBe("insufficient_basis");
  });

  it("— when no source ranks at all", () => {
    expect(marketAction({}).label).toBe("—");
    expect(marketAction({ sourceRanks: {} }).label).toBe("—");
  });

  it("title surfaces direction context", () => {
    const a = marketAction(stamped("consensus_premium", 80));
    expect(a.title.toLowerCase()).toContain("market is undervaluing");
  });

  it("does NOT derive a verb from per-source ranks", () => {
    // Guard on the no-frontend-recompute rule, same as marketGapLabel's.
    const a = marketAction({ sourceRanks: { ktcSfTep: 5, idpTradeCalc: 500 } });
    expect(a.label).toBe("—");
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
