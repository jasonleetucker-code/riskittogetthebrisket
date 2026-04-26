import { describe, it, expect } from "vitest";
import {
  POSITION_FAMILIES,
  familyForPos,
  buildValueIndex,
  totalsByFamily,
  grandTotal,
} from "@/lib/roster-compare";

describe("familyForPos", () => {
  it("maps offense positions to their family", () => {
    expect(familyForPos("QB")).toBe("QB");
    expect(familyForPos("RB")).toBe("RB");
    expect(familyForPos("FB")).toBe("RB");
    expect(familyForPos("WR")).toBe("WR");
    expect(familyForPos("TE")).toBe("TE");
  });

  it("maps IDP variants to their family", () => {
    expect(familyForPos("DT")).toBe("DL");
    expect(familyForPos("EDGE")).toBe("DL");
    expect(familyForPos("ILB")).toBe("LB");
    expect(familyForPos("CB")).toBe("DB");
    expect(familyForPos("FS")).toBe("DB");
  });

  it("returns null for unknown positions", () => {
    expect(familyForPos("K")).toBe(null);
    expect(familyForPos("DEF")).toBe(null);
    expect(familyForPos("")).toBe(null);
    expect(familyForPos(null)).toBe(null);
  });

  it("is case-insensitive", () => {
    expect(familyForPos("qb")).toBe("QB");
    expect(familyForPos("edge")).toBe("DL");
  });
});

describe("buildValueIndex", () => {
  it("indexes rows by lowercase name", () => {
    const ix = buildValueIndex([
      { name: "Caleb Williams", pos: "QB", rankDerivedValue: 6500 },
      { name: "Bo Nix", pos: "QB", rankDerivedValue: 4000 },
    ]);
    expect(ix.size).toBe(2);
    expect(ix.get("caleb williams").value).toBe(6500);
    expect(ix.get("bo nix").pos).toBe("QB");
  });

  it("falls back to values.full when rankDerivedValue is absent", () => {
    const ix = buildValueIndex([
      { name: "X", pos: "WR", values: { full: 3000 } },
    ]);
    expect(ix.get("x").value).toBe(3000);
  });

  it("coerces non-finite values to 0", () => {
    const ix = buildValueIndex([
      { name: "X", pos: "WR", rankDerivedValue: "garbage" },
    ]);
    expect(ix.get("x").value).toBe(0);
  });

  it("skips rows with empty names", () => {
    const ix = buildValueIndex([
      { name: "", pos: "QB", rankDerivedValue: 1 },
      { name: null, pos: "QB", rankDerivedValue: 2 },
    ]);
    expect(ix.size).toBe(0);
  });
});

describe("totalsByFamily", () => {
  const ix = buildValueIndex([
    { name: "QB1", pos: "QB", rankDerivedValue: 7000 },
    { name: "QB2", pos: "QB", rankDerivedValue: 4500 },
    { name: "RB1", pos: "RB", rankDerivedValue: 6000 },
    { name: "WR1", pos: "WR", rankDerivedValue: 8000 },
    { name: "EDGE1", pos: "EDGE", rankDerivedValue: 3000 },
    { name: "LB1", pos: "ILB", rankDerivedValue: 2000 },
    { name: "K1", pos: "K", rankDerivedValue: 500 },
  ]);

  it("sums values per family with counts", () => {
    const totals = totalsByFamily(
      ["QB1", "QB2", "RB1", "WR1", "EDGE1", "LB1"],
      ix,
    );
    expect(totals.QB).toEqual({ total: 11500, count: 2 });
    expect(totals.RB).toEqual({ total: 6000, count: 1 });
    expect(totals.WR).toEqual({ total: 8000, count: 1 });
    expect(totals.DL).toEqual({ total: 3000, count: 1 });
    expect(totals.LB).toEqual({ total: 2000, count: 1 });
  });

  it("ignores positions outside the recognised families", () => {
    const totals = totalsByFamily(["K1"], ix);
    expect(totals.QB.count).toBe(0);
    expect(totals.WR.count).toBe(0);
    // K → no family, so doesn't appear anywhere
    for (const f of Object.values(totals)) expect(f.count).toBe(0);
  });

  it("returns zeros for an empty roster", () => {
    const totals = totalsByFamily([], ix);
    for (const f of POSITION_FAMILIES) {
      expect(totals[f.key]).toEqual({ total: 0, count: 0 });
    }
  });

  it("ignores names not present in the index", () => {
    const totals = totalsByFamily(["nobody"], ix);
    for (const f of POSITION_FAMILIES) {
      expect(totals[f.key].count).toBe(0);
    }
  });

  it("is case-insensitive when matching player names", () => {
    const totals = totalsByFamily(["qb1"], ix);
    expect(totals.QB.count).toBe(1);
    expect(totals.QB.total).toBe(7000);
  });
});

describe("grandTotal", () => {
  it("sums every family's total", () => {
    const sum = grandTotal({
      QB: { total: 100, count: 1 },
      RB: { total: 200, count: 2 },
      WR: { total: 300, count: 3 },
    });
    expect(sum).toBe(600);
  });

  it("handles missing or malformed families gracefully", () => {
    expect(grandTotal({})).toBe(0);
    expect(grandTotal(null)).toBe(0);
    expect(grandTotal({ QB: null, RB: { total: 5 } })).toBe(5);
  });
});
