/**
 * CW-40 / master-site-audit W27-F001 regression evidence (P1).
 *
 * Finding: the /rankings Edge column and its buy/sell filter carry no signal for
 * IDP rows (KTC publishes no IDP), while /edge labels the same players BUY/SELL
 * from a second detector (`idpMarketAction`, IDPTC as the retail anchor).
 *
 * Adjudication (docs/audits/remediation_2026-11-06/CW40_P1_OPEN_ADJUDICATION.md):
 * OPEN. The backend half moved (the gap is now our value vs KTC Market,
 * `ktcMarket.reason: "no_ktc_coverage"` on IDP rows) but the outcome is unchanged:
 * `marketAction` answers "—" for every IDP row, `edge=buy|sell` matches none, and
 * `idpMarketAction` still gives them a verdict.
 *
 * The IDP row below is a trimmed copy of the real "Abdul Carter" row from the
 * tracked archive board `dynasty_export_20261106_194518` (values are source
 * `valueContribution`s and ranks). Pure functions, no network.
 */
import { describe, expect, it } from "vitest";
import { idpMarketAction, marketAction } from "../lib/display-helpers.js";
import { rowMatches } from "../lib/player-filters.js";

const IDP_ROW = {
  name: "Abdul Carter",
  assetClass: "idp",
  position: "DL",
  marketGapDirection: "none",
  marketGapValueRatio: null,
  ktcMarket: { value: null, available: false, reason: "no_ktc_coverage" },
  sourceRankMeta: {
    idpTradeCalc: { valueContribution: 5414 },
    idpShowCombined: { valueContribution: 4204 },
    fantasyProsIdp: { valueContribution: 2064 },
    draftSharksIdp: { valueContribution: 2562 },
  },
  effectiveSourceRanks: { idpTradeCalc: 64, fantasyProsIdp: 359, draftSharksIdp: 244 },
  sourceRanks: { idpTradeCalc: 64, idpShowCombined: 88, fantasyProsIdp: 359, draftSharksIdp: 244 },
  quarantined: false,
  rankDerivedValue: 4407,
  canonicalConsensusRank: 83,
};

const OFFENSE_SELL_ROW = {
  name: "Offense Sell",
  assetClass: "offense",
  position: "WR",
  marketGapDirection: "retail_premium",
  marketGapValueRatio: 0.2,
  ktcMarket: { value: 5000, normalizedValue: 5000, available: true },
  rankDerivedValue: 4000,
};

describe("W27-F001: two Edge detectors disagree on IDP rows", () => {
  it("control: the offense path labels a priced retail premium SELL and the filter finds it", () => {
    expect(marketAction(OFFENSE_SELL_ROW).label).toBe("SELL");
    expect(rowMatches(OFFENSE_SELL_ROW, { edge: "sell" })).toBe(true);
  });

  it("the /edge IDP detector gives the same IDP row a verdict (IDPTC vs expert values)", () => {
    expect(idpMarketAction(IDP_ROW).kind).toBe("sell");
  });

  it("the /rankings Edge cell is a dash for the IDP row (current behavior, pinned)", () => {
    expect(marketAction(IDP_ROW).label).toBe("—");
  });

  // Flips when /rankings (marketAction / the contract gap) learns to label IDP.
  it.fails("W27-F001: /rankings Edge verdict equals /edge's verdict for the same IDP row", () => {
    expect(marketAction(IDP_ROW).kind).toBe(idpMarketAction(IDP_ROW).kind);
  });

  // Flips when the advanced filter edge=sell can match a defender.
  it.fails("W27-F001: edge=sell filter can match an IDP row that /edge calls SELL", () => {
    expect(rowMatches(IDP_ROW, { edge: "sell" })).toBe(true);
  });
});
