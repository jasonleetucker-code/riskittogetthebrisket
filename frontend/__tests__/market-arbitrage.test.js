import { describe, expect, it } from "vitest";
import {
  arbitrageDescriptor,
  buildArbitrageRows,
  publicMarketFor,
  publicMarketValueOf,
} from "@/lib/market-arbitrage";

function row(overrides = {}) {
  return {
    name: "Test Player",
    pos: "WR",
    assetClass: "offense",
    rank: 25,
    values: { full: 6300 },
    rankDerivedValue: 6300,
    canonicalSites: { ktcSfTep: 5000, idpTradeCalc: 5200 },
    confidenceBucket: "high",
    quarantined: false,
    ...overrides,
  };
}

describe("market arbitrage", () => {
  it("routes offense to KTC and IDP to IDP Trade Calculator", () => {
    expect(publicMarketFor(row())).toEqual({ key: "ktcSfTep", label: "KTC" });
    expect(
      publicMarketFor(row({ assetClass: "idp", pos: "LB" })),
    ).toEqual({ key: "idpTradeCalc", label: "IDP Trade Calculator" });
  });

  it("measures our canonical value directly against the public transaction anchor", () => {
    const edge = arbitrageDescriptor(row());
    expect(edge.action).toBe("strong_buy");
    expect(edge.ourValue).toBe(6300);
    expect(edge.marketValue).toBe(5000);
    expect(edge.edgePoints).toBe(1300);
    expect(edge.edgeRatio).toBeCloseTo(0.26);
  });

  it("does not require broad source disagreement to surface a buy", () => {
    const opportunities = buildArbitrageRows([
      row({ sourceRankSpread: 0, hasSourceDisagreement: false }),
    ], { action: "buy" });
    expect(opportunities).toHaveLength(1);
    expect(opportunities[0].edge.action).toBe("strong_buy");
  });

  it("keeps missing public prices missing instead of coercing them to zero", () => {
    const missing = row({ canonicalSites: {} });
    expect(publicMarketValueOf(missing)).toBeNull();
    expect(arbitrageDescriptor(missing)).toBeNull();
    expect(buildArbitrageRows([missing], { action: "buy" })).toEqual([]);
  });

  it("uses IDP Trade Calculator rather than KTC for an IDP buy", () => {
    const idp = row({
      assetClass: "idp",
      pos: "LB",
      values: { full: 6000 },
      canonicalSites: { ktcSfTep: 1000, idpTradeCalc: 5000 },
    });
    const edge = arbitrageDescriptor(idp);
    expect(edge.marketLabel).toBe("IDP Trade Calculator");
    expect(edge.marketValue).toBe(5000);
    expect(edge.edgeRatio).toBeCloseTo(0.20);
    expect(edge.action).toBe("strong_buy");
  });

  it("surfaces public-friendly win-win offers only when both sides clear their margins", () => {
    const edge = arbitrageDescriptor(row());
    expect(edge.winWin).toBe(true);
    expect(edge.publicFriendlyOfferCeiling).toBe(5250);
    expect(edge.publicWinRatio).toBeCloseTo(0.05);
    expect(edge.internalWinRatio).toBeCloseTo(0.20);
  });

  it("sorts by actionable percentage edge, not sourceRankSpread", () => {
    const opportunities = buildArbitrageRows([
      row({ name: "Huge disagreement small edge", values: { full: 5400 }, sourceRankSpread: 400 }),
      row({ name: "Tight consensus big edge", values: { full: 6500 }, sourceRankSpread: 0 }),
    ], { action: "buy" });
    expect(opportunities.map((x) => x.row.name)).toEqual([
      "Tight consensus big edge",
      "Huge disagreement small edge",
    ]);
  });
});
