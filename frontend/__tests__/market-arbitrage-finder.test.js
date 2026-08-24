import { describe, expect, it } from "vitest";
import {
  applyLens,
  getLens,
  publicMarketArbitrage,
} from "../lib/edge-helpers.js";

function row(overrides = {}) {
  return {
    name: "Test Player",
    pos: "WR",
    assetClass: "offense",
    rank: 50,
    rankDerivedValue: 6000,
    values: { full: 6000 },
    rawSourceValues: {},
    canonicalSites: { ktcSfTep: 5000 },
    confidenceBucket: "high",
    sourceCount: 5,
    sourceRankSpread: 5,
    quarantined: false,
    ...overrides,
  };
}

describe("publicMarketArbitrage", () => {
  it("finds offense buy arbitrage directly against KTC even with tight source agreement", () => {
    const edge = publicMarketArbitrage(
      row({ rankDerivedValue: 6000, canonicalSites: { ktcSfTep: 5000 } }),
    );

    expect(edge.market).toBe("KTC");
    expect(edge.direction).toBe("buy");
    expect(edge.internalValue).toBe(6000);
    expect(edge.publicValue).toBe(5000);
    expect(edge.hiddenSurplus).toBe(1000);
    expect(edge.ratio).toBeCloseTo(0.2);
    expect(edge.winWinRoom).toBeGreaterThan(0);
  });

  it("uses IDP Trade Calculator as the public transaction market for IDP", () => {
    const edge = publicMarketArbitrage(
      row({
        pos: "LB",
        assetClass: "idp",
        rankDerivedValue: 4200,
        canonicalSites: { idpTradeCalc: 3500, ktcSfTep: 8000 },
      }),
    );

    expect(edge.market).toBe("IDPTC");
    expect(edge.direction).toBe("buy");
    expect(edge.publicValue).toBe(3500);
    expect(edge.ratio).toBeCloseTo(0.2);
  });

  it("prefers the raw vendor-visible price when the backend provides one", () => {
    const edge = publicMarketArbitrage(
      row({
        rankDerivedValue: 6000,
        rawSourceValues: { ktcSfTep: 4800 },
        canonicalSites: { ktcSfTep: 5200 },
      }),
    );

    expect(edge.publicValue).toBe(4800);
    expect(edge.ratio).toBeCloseTo(0.25);
  });

  it("returns sell arbitrage when public market exceeds our canonical value", () => {
    const edge = publicMarketArbitrage(
      row({ rankDerivedValue: 4500, canonicalSites: { ktcSfTep: 6000 } }),
    );

    expect(edge.direction).toBe("sell");
    expect(edge.hiddenSurplus).toBe(-1500);
    expect(edge.ratio).toBeCloseTo(-0.25);
    expect(edge.winWinRoom).toBe(0);
  });

  it("never coerces a missing public quote to zero", () => {
    expect(
      publicMarketArbitrage(
        row({ rawSourceValues: {}, canonicalSites: {} }),
      ),
    ).toBeNull();
  });
});

describe("Market Arbitrage lens", () => {
  it("keeps the historical inefficiencies key but re-aims its label and meaning", () => {
    const lens = getLens("inefficiencies");
    expect(lens.label).toBe("Market Arbitrage");
    expect(lens.description).toMatch(/canonical value/i);
    expect(lens.description).toMatch(/KTC/i);
    expect(lens.description).toMatch(/IDP Trade Calculator/i);
  });

  it("does not require source disagreement to surface a clean buy", () => {
    const lens = getLens("inefficiencies");
    expect(
      lens.filter(
        row({
          sourceRankSpread: 0,
          rankDerivedValue: 6000,
          canonicalSites: { ktcSfTep: 5000 },
        }),
      ),
    ).toBe(true);
  });

  it("filters noise below the calibrated 5% meaningful-gap floor", () => {
    const lens = getLens("inefficiencies");
    expect(
      lens.filter(
        row({ rankDerivedValue: 5200, canonicalSites: { ktcSfTep: 5000 } }),
      ),
    ).toBe(false);
  });

  it("sorts actionable buys before sells and strongest buys first", () => {
    const rows = [
      row({
        name: "Sell",
        rankDerivedValue: 4000,
        canonicalSites: { ktcSfTep: 5000 },
      }),
      row({
        name: "Buy 10",
        rankDerivedValue: 5500,
        canonicalSites: { ktcSfTep: 5000 },
      }),
      row({
        name: "Buy 25",
        rankDerivedValue: 6250,
        canonicalSites: { ktcSfTep: 5000 },
      }),
    ];

    expect(applyLens(rows, "inefficiencies").map((r) => r.name)).toEqual([
      "Buy 25",
      "Buy 10",
      "Sell",
    ]);
  });

  it("keeps the trade-relevance rank cap", () => {
    const lens = getLens("inefficiencies");
    expect(
      lens.filter(
        row({
          rank: 251,
          rankDerivedValue: 7000,
          canonicalSites: { ktcSfTep: 4000 },
        }),
      ),
    ).toBe(false);
  });
});
