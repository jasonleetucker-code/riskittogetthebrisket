/**
 * TC-B2 — lib/trade-package-facts.js (TCM-M01, M02, M04, M05).
 *
 * Pins: values are the side totals' own per-copy numbers (override included),
 * VA is the page's number and its own segment, ranks are backend stamps only,
 * and MISSING IS NEVER ZERO — an unpriced asset is a named piece, never an
 * average's 0; an average with no member is null.
 */
import { describe, expect, it } from "vitest";
import {
  IDENTITY_SERIES_LIMIT,
  sidePackageFacts,
  sideValueSegments,
  tradeAssetIdentities,
  valueConcentration,
} from "@/lib/trade-package-facts";
import { sideTotal } from "@/lib/trade-logic";

const player = (name, v, extra = {}) => ({
  name,
  pos: "WR",
  assetClass: "offense",
  rankDerivedValue: v,
  values: { full: v },
  ...extra,
});
const pick = (name, v) => ({
  name,
  pos: "PICK",
  assetClass: "pick",
  rankDerivedValue: v,
  values: { full: v },
});
const unpriced = (name) => ({ name, pos: "RB", assetClass: "offense", rankDerivedValue: null, values: {} });

describe("tradeAssetIdentities (M02)", () => {
  it("numbers lines in order of first appearance, one identity per line across sides", () => {
    const a = player("A", 100);
    const b = player("B", 50);
    const ids = tradeAssetIdentities([
      { assets: [a, a, b] },
      { assets: [player("C", 70), a] },
    ]);
    expect([...ids.entries()].map(([k, v]) => [k, v.marker])).toEqual([
      ["A", 1],
      ["B", 2],
      ["C", 3],
    ]);
  });

  it("gives the fixed series to the first lines only; later lines keep a marker", () => {
    const assets = Array.from({ length: IDENTITY_SERIES_LIMIT + 2 }, (_, i) => player(`P${i}`, 10));
    const ids = tradeAssetIdentities([{ assets }, { assets: [] }]);
    const series = [...ids.values()].map((v) => v.series);
    expect(series.slice(0, IDENTITY_SERIES_LIMIT)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(series.slice(IDENTITY_SERIES_LIMIT)).toEqual([null, null]);
    expect([...ids.values()].map((v) => v.marker)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });
});

describe("sidePackageFacts (M04)", () => {
  it("counts copies, sums exactly what the side total sums, and skips nothing silently", () => {
    const assets = [
      player("A", 6000, { age: 24, canonicalConsensusRank: 10 }),
      player("A", 6000, { age: 24, canonicalConsensusRank: 10 }),
      pick("2027 Mid 1st", 3000),
      unpriced("Ghost"),
      // An override prices a row the board does not.
      { ...unpriced("Typed"), customValue: 500 },
    ];
    const f = sidePackageFacts(assets, "full");
    expect(f.pieces).toBe(5);
    expect(f.players).toBe(4);
    expect(f.picks).toBe(1);
    expect(f.pricedPieces).toBe(4);
    expect(f.unpriced).toEqual(["Ghost"]);
    expect(f.rawPriced).toBe(sideTotal(assets, "full"));
    expect(f.averageValue).toBe((6000 + 6000 + 3000 + 500) / 4);
    // Ages: only players with an age; picks never count.
    expect(f.averageAge).toBe(24);
    expect(f.agedPlayers).toBe(2);
    // Ranks: backend stamps only, never a display ordinal.
    expect(f.averageRank).toBe(10);
    expect(f.rankedPieces).toBe(2);
  });

  it("an average with nothing to average is null, never 0", () => {
    const f = sidePackageFacts([unpriced("Ghost"), pick("2028 Round 2", 0)], "full");
    expect(f.averageValue).toBeNull();
    expect(f.averageAge).toBeNull();
    expect(f.averageRank).toBeNull();
    expect(f.rawPriced).toBe(0);
    expect(f.unpriced).toEqual(["Ghost", "2028 Round 2"]);
  });

  it("ignores a frontend display rank (`rank`) and non-integer stamps", () => {
    const f = sidePackageFacts([player("A", 10, { rank: 900, canonicalConsensusRank: null })], "full");
    expect(f.averageRank).toBeNull();
  });
});

describe("valueConcentration (M05)", () => {
  it("one piece is fully concentrated", () => {
    expect(valueConcentration([player("A", 8000)], "full")).toEqual({
      topShare: 1,
      effectiveCount: 1,
      pricedPieces: 1,
    });
  });

  it("n equal pieces behave like n pieces; copies count", () => {
    const c = valueConcentration([player("A", 100), player("A", 100), player("B", 100)], "full");
    expect(c.topShare).toBeCloseTo(1 / 3);
    expect(c.effectiveCount).toBeCloseTo(3);
  });

  it("a star plus filler sits between, and unpriced pieces are not 0s", () => {
    const c = valueConcentration([player("Star", 9000), player("F", 1000), unpriced("Ghost")], "full");
    expect(c.pricedPieces).toBe(2);
    expect(c.topShare).toBeCloseTo(0.9);
    expect(c.effectiveCount).toBeCloseTo(100 / 82);
  });

  it("nothing priced is null", () => {
    expect(valueConcentration([unpriced("Ghost")], "full")).toBeNull();
    expect(valueConcentration([], "full")).toBeNull();
  });
});

describe("sideValueSegments (M01)", () => {
  it("one segment per line (all copies), then VA as its own segment", () => {
    const a = player("A", 1000);
    const assets = [a, a, unpriced("Ghost")];
    const ids = tradeAssetIdentities([{ assets }]);
    const segs = sideValueSegments(assets, 440.4, "full", ids);
    expect(segs.map((s) => [s.kind, s.label, s.count, s.value, s.marker])).toEqual([
      ["asset", "A", 2, 2000, 1],
      ["asset", "Ghost", 1, null, 2],
      ["va", "Value Adjustment", 1, 440.4, null],
    ]);
  });

  it("no VA, no VA segment (never a +0)", () => {
    expect(sideValueSegments([player("A", 1)], 0, "full", new Map()).map((s) => s.kind)).toEqual([
      "asset",
    ]);
  });
});
