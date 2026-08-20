import { describe, it, expect } from "vitest";
import { computeMovers } from "@/lib/market-movers";

function row(overrides = {}) {
  return {
    name: "Test Player",
    pos: "WR",
    rankDerivedValue: 5000,
    canonicalConsensusRank: 42,
    rankChange: 10,
    confidence: 0.8,
    ...overrides,
  };
}

describe("computeMovers", () => {
  it("passes through the row's canonical confidence verbatim", () => {
    const rows = [row({ name: "A", confidence: 0.72 })];
    const [item] = computeMovers({ rows, scope: "top150", limit: 20 });
    expect(item.confidence).toBe(0.72);
  });

  it("reports null confidence rather than coercing an unmeasured row to 0", () => {
    const rows = [row({ name: "A", confidence: null })];
    const [item] = computeMovers({ rows, scope: "top150", limit: 20 });
    expect(item.confidence).toBeNull();
  });

  it("reports null confidence when the field is absent entirely", () => {
    const rows = [row({ name: "A" })];
    delete rows[0].confidence;
    const [item] = computeMovers({ rows, scope: "top150", limit: 20 });
    expect(item.confidence).toBeNull();
  });

  it("excludes rows with no meaningful rank change", () => {
    const rows = [row({ name: "Quiet", rankChange: 0 }), row({ name: "Unranked", rankChange: null })];
    const items = computeMovers({ rows, scope: "top150", limit: 20 });
    expect(items).toHaveLength(0);
  });

  it("sorts by magnitude of change, descending", () => {
    const rows = [
      row({ name: "Small", rankChange: 3 }),
      row({ name: "Big", rankChange: -20 }),
      row({ name: "Medium", rankChange: 8 }),
    ];
    const items = computeMovers({ rows, scope: "top150", limit: 20 });
    expect(items.map((i) => i.name)).toEqual(["Big", "Medium", "Small"]);
  });
});
