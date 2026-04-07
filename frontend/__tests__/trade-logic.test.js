/**
 * Tests for lib/trade-logic.js — the pure trade calculator logic
 * extracted from the Next.js trade page.
 */
import { describe, expect, it } from "vitest";
import {
  VALUE_MODES,
  STORAGE_KEY,
  RECENT_KEY,
  verdictFromGap,
  colorFromGap,
  sideTotal,
  tradeGap,
  linearGap,
  powerWeightedTotal,
  effectiveValue,
  pickYearDiscount,
  addAssetToSide,
  removeAssetFromSide,
  isAssetInTrade,
  serializeWorkspace,
  deserializeWorkspace,
  addRecent,
  filterPickerRows,
  getPlayerEdge,
  parsePickToken,
  findBalancers,
  verdictBarPosition,
  lamMultiplier,
  scarcityMultiplier,
  buildScarcityModel,
} from "@/lib/trade-logic";

// ── Test fixtures ────────────────────────────────────────────────────

function makeRow(name, fullValue, pos = "QB", assetClass = "offense") {
  return {
    name,
    pos,
    assetClass,
    values: { full: fullValue, raw: fullValue, scoring: fullValue, scarcity: fullValue },
  };
}

const ALLEN = makeRow("Josh Allen", 9000);
const MAHOMES = makeRow("Patrick Mahomes", 8800);
const CHASE = makeRow("Ja'Marr Chase", 8500, "WR");
const PARSONS = makeRow("Micah Parsons", 5000, "LB", "idp");
const PICK_2026 = makeRow("2026 Early 1st", 7000, "PICK", "pick");

// ── Constants ────────────────────────────────────────────────────────

describe("constants", () => {
  it("VALUE_MODES has 4 modes", () => {
    expect(VALUE_MODES.length).toBe(4);
    expect(VALUE_MODES.map((m) => m.key)).toEqual(["full", "raw", "scoring", "scarcity"]);
  });

  it("storage keys are stable strings", () => {
    expect(STORAGE_KEY).toBe("next_trade_workspace_v1");
    expect(RECENT_KEY).toBe("next_trade_recent_assets_v1");
  });
});

// ── verdictFromGap ───────────────────────────────────────────────────

describe("verdictFromGap", () => {
  // Thresholds on 1–9999 display scale: 256, 769, 1538
  it("returns 'Near even' for gaps under 256", () => {
    expect(verdictFromGap(0)).toBe("Near even");
    expect(verdictFromGap(255)).toBe("Near even");
    expect(verdictFromGap(-255)).toBe("Near even");
  });

  it("returns 'Lean' for gaps 256-768", () => {
    expect(verdictFromGap(256)).toBe("Lean");
    expect(verdictFromGap(768)).toBe("Lean");
    expect(verdictFromGap(-400)).toBe("Lean");
  });

  it("returns 'Strong lean' for gaps 769-1537", () => {
    expect(verdictFromGap(769)).toBe("Strong lean");
    expect(verdictFromGap(1537)).toBe("Strong lean");
    expect(verdictFromGap(-1000)).toBe("Strong lean");
  });

  it("returns 'Major gap' for gaps >= 1538", () => {
    expect(verdictFromGap(1538)).toBe("Major gap");
    expect(verdictFromGap(5000)).toBe("Major gap");
    expect(verdictFromGap(-2000)).toBe("Major gap");
  });

  it("treats gap symmetrically (absolute value)", () => {
    expect(verdictFromGap(500)).toBe(verdictFromGap(-500));
  });
});

// ── colorFromGap ─────────────────────────────────────────────────────

describe("colorFromGap", () => {
  it("returns empty string for near-even gaps", () => {
    expect(colorFromGap(0)).toBe("");
    expect(colorFromGap(255)).toBe("");
    expect(colorFromGap(-100)).toBe("");
  });

  it("returns 'green' when Side A wins (positive gap)", () => {
    expect(colorFromGap(500)).toBe("green");
    expect(colorFromGap(2000)).toBe("green");
  });

  it("returns 'red' when Side B wins (negative gap)", () => {
    expect(colorFromGap(-500)).toBe("red");
    expect(colorFromGap(-2000)).toBe("red");
  });
});

// ── sideTotal ────────────────────────────────────────────────────────

describe("sideTotal", () => {
  it("sums values for the selected mode", () => {
    expect(sideTotal([ALLEN, CHASE], "full")).toBe(9000 + 8500);
  });

  it("returns 0 for empty side", () => {
    expect(sideTotal([], "full")).toBe(0);
  });

  it("handles missing value mode gracefully", () => {
    expect(sideTotal([ALLEN], "nonexistent")).toBe(0);
  });

  it("uses different modes", () => {
    const row = {
      name: "Test",
      values: { full: 9000, raw: 7000, scoring: 8000, scarcity: 8500 },
    };
    expect(sideTotal([row], "raw")).toBe(7000);
    expect(sideTotal([row], "scoring")).toBe(8000);
    expect(sideTotal([row], "scarcity")).toBe(8500);
  });
});

// ── tradeGap ─────────────────────────────────────────────────────────

describe("tradeGap (power-weighted)", () => {
  it("single-asset sides equal linear gap", () => {
    // With one asset per side, power-weighted = linear
    expect(tradeGap([ALLEN], [CHASE], "full")).toBe(500);
    expect(tradeGap([CHASE], [ALLEN], "full")).toBe(-500);
  });

  it("multi-asset sides are power-weighted (less than linear sum)", () => {
    const gap = tradeGap([ALLEN], [CHASE, PICK_2026], "full");
    const linGapVal = linearGap([ALLEN], [CHASE, PICK_2026], "full");
    // Power-weighted sum of B < linear sum, so gap magnitude is smaller
    expect(linGapVal).toBe(9000 - (8500 + 7000));
    expect(Math.abs(gap)).toBeLessThan(Math.abs(linGapVal));
    expect(gap).toBeLessThan(0); // B still wins
  });

  it("returns 0 for empty vs empty", () => {
    expect(tradeGap([], [], "full")).toBe(0);
  });
});

describe("linearGap", () => {
  it("computes simple difference", () => {
    expect(linearGap([ALLEN], [CHASE, PICK_2026], "full")).toBe(9000 - (8500 + 7000));
  });
});

// ── addAssetToSide / removeAssetFromSide ─────────────────────────────

describe("addAssetToSide", () => {
  it("adds a new asset", () => {
    const result = addAssetToSide([], ALLEN);
    expect(result.length).toBe(1);
    expect(result[0].name).toBe("Josh Allen");
  });

  it("does not duplicate an existing asset", () => {
    const result = addAssetToSide([ALLEN], ALLEN);
    expect(result.length).toBe(1);
  });

  it("returns same array for null row", () => {
    const side = [ALLEN];
    expect(addAssetToSide(side, null)).toBe(side);
  });

  it("preserves existing assets when adding", () => {
    const result = addAssetToSide([ALLEN], CHASE);
    expect(result.length).toBe(2);
    expect(result[0].name).toBe("Josh Allen");
    expect(result[1].name).toBe("Ja'Marr Chase");
  });
});

describe("removeAssetFromSide", () => {
  it("removes a named asset", () => {
    const result = removeAssetFromSide([ALLEN, CHASE], "Josh Allen");
    expect(result.length).toBe(1);
    expect(result[0].name).toBe("Ja'Marr Chase");
  });

  it("returns same contents if name not found", () => {
    const result = removeAssetFromSide([ALLEN], "Not Here");
    expect(result.length).toBe(1);
  });

  it("returns empty array when removing last asset", () => {
    const result = removeAssetFromSide([ALLEN], "Josh Allen");
    expect(result.length).toBe(0);
  });
});

// ── isAssetInTrade ───────────────────────────────────────────────────

describe("isAssetInTrade", () => {
  it("returns true if asset is in side A", () => {
    expect(isAssetInTrade([ALLEN], [], "Josh Allen")).toBe(true);
  });

  it("returns true if asset is in side B", () => {
    expect(isAssetInTrade([], [CHASE], "Ja'Marr Chase")).toBe(true);
  });

  it("returns false if asset is in neither side", () => {
    expect(isAssetInTrade([ALLEN], [CHASE], "Patrick Mahomes")).toBe(false);
  });
});

// ── Workspace serialization/deserialization ──────────────────────────

describe("serializeWorkspace", () => {
  it("serializes trade state to name-only arrays", () => {
    const result = serializeWorkspace([ALLEN], [CHASE], "full", "A");
    expect(result).toEqual({
      valueMode: "full",
      activeSide: "A",
      sideA: ["Josh Allen"],
      sideB: ["Ja'Marr Chase"],
    });
  });

  it("handles empty sides", () => {
    const result = serializeWorkspace([], [], "raw", "B");
    expect(result.sideA).toEqual([]);
    expect(result.sideB).toEqual([]);
    expect(result.valueMode).toBe("raw");
    expect(result.activeSide).toBe("B");
  });
});

describe("deserializeWorkspace", () => {
  it("restores trade state from serialized names", () => {
    const rowByName = new Map([
      ["Josh Allen", ALLEN],
      ["Ja'Marr Chase", CHASE],
    ]);
    const parsed = {
      valueMode: "raw",
      activeSide: "B",
      sideA: ["Josh Allen"],
      sideB: ["Ja'Marr Chase"],
    };
    const result = deserializeWorkspace(parsed, rowByName);
    expect(result.valueMode).toBe("raw");
    expect(result.activeSide).toBe("B");
    expect(result.sideA.length).toBe(1);
    expect(result.sideA[0].name).toBe("Josh Allen");
    expect(result.sideB[0].name).toBe("Ja'Marr Chase");
  });

  it("drops players not found in current data", () => {
    const rowByName = new Map([["Josh Allen", ALLEN]]);
    const parsed = {
      sideA: ["Josh Allen", "Retired Player"],
      sideB: [],
    };
    const result = deserializeWorkspace(parsed, rowByName);
    expect(result.sideA.length).toBe(1);
  });

  it("defaults to 'full' mode for invalid valueMode", () => {
    const rowByName = new Map();
    const result = deserializeWorkspace({ valueMode: "invalid" }, rowByName);
    expect(result.valueMode).toBe("full");
  });

  it("defaults activeSide to A for non-B values", () => {
    const rowByName = new Map();
    const result = deserializeWorkspace({ activeSide: "C" }, rowByName);
    expect(result.activeSide).toBe("A");
  });

  it("returns null for null/non-object input", () => {
    const rowByName = new Map();
    expect(deserializeWorkspace(null, rowByName)).toBeNull();
    expect(deserializeWorkspace("bad", rowByName)).toBeNull();
  });
});

// ── addRecent ────────────────────────────────────────────────────────

describe("addRecent", () => {
  it("adds name to front of list", () => {
    const result = addRecent(["A", "B"], "C");
    expect(result[0]).toBe("C");
    expect(result.length).toBe(3);
  });

  it("deduplicates — moves existing name to front", () => {
    const result = addRecent(["A", "B", "C"], "B");
    expect(result).toEqual(["B", "A", "C"]);
  });

  it("caps at 20 entries", () => {
    const existing = Array.from({ length: 20 }, (_, i) => `P${i}`);
    const result = addRecent(existing, "New");
    expect(result.length).toBe(20);
    expect(result[0]).toBe("New");
    expect(result).not.toContain("P19");
  });
});

// ── filterPickerRows ─────────────────────────────────────────────────

describe("filterPickerRows", () => {
  const allRows = [ALLEN, MAHOMES, CHASE, PARSONS, PICK_2026];

  it("excludes assets already in trade", () => {
    const result = filterPickerRows(allRows, [ALLEN], [CHASE], "", "all");
    expect(result.map((r) => r.name)).not.toContain("Josh Allen");
    expect(result.map((r) => r.name)).not.toContain("Ja'Marr Chase");
    expect(result.length).toBe(3);
  });

  it("filters by asset class", () => {
    const result = filterPickerRows(allRows, [], [], "", "idp");
    expect(result.every((r) => r.assetClass === "idp")).toBe(true);
    expect(result.length).toBe(1);
  });

  it("filters by search query (case insensitive)", () => {
    const result = filterPickerRows(allRows, [], [], "allen", "all");
    expect(result.length).toBe(1);
    expect(result[0].name).toBe("Josh Allen");
  });

  it("combines filter and query", () => {
    const result = filterPickerRows(allRows, [], [], "parsons", "idp");
    expect(result.length).toBe(1);
    expect(result[0].name).toBe("Micah Parsons");
  });

  it("returns empty for no matches", () => {
    const result = filterPickerRows(allRows, [], [], "nonexistent", "all");
    expect(result.length).toBe(0);
  });

  it("limits to 80 results", () => {
    const manyRows = Array.from({ length: 200 }, (_, i) => makeRow(`Player ${i}`, 1000 - i));
    const result = filterPickerRows(manyRows, [], [], "", "all");
    expect(result.length).toBe(80);
  });

  it("shows all when filter is 'all' and query is empty", () => {
    const result = filterPickerRows(allRows, [], [], "", "all");
    expect(result.length).toBe(5);
  });

  it("filters picks", () => {
    const result = filterPickerRows(allRows, [], [], "", "pick");
    expect(result.length).toBe(1);
    expect(result[0].name).toBe("2026 Early 1st");
  });
});

// ── Full trade scenario ──────────────────────────────────────────────

describe("full trade scenario", () => {
  it("builds a trade, computes verdict, swaps sides, clears", () => {
    // Build side A: Allen + Chase
    let sideA = addAssetToSide([], ALLEN);
    sideA = addAssetToSide(sideA, CHASE);

    // Build side B: Mahomes + 2026 pick
    let sideB = addAssetToSide([], MAHOMES);
    sideB = addAssetToSide(sideB, PICK_2026);

    // Compute
    const totalA = sideTotal(sideA, "full"); // 9000 + 8500 = 17500
    const totalB = sideTotal(sideB, "full"); // 8800 + 7000 = 15800
    const gap = tradeGap(sideA, sideB, "full"); // power-weighted

    expect(totalA).toBe(17500);
    expect(totalB).toBe(15800);
    // Power-weighted gap is smaller than linear (1700) due to diminishing returns
    expect(gap).toBeGreaterThan(0); // A still wins
    expect(gap).toBeLessThan(1700); // But less than linear
    expect(verdictFromGap(gap)).toBe("Major gap");
    expect(colorFromGap(gap)).toBe("green"); // Side A wins

    // Swap sides
    const [newA, newB] = [sideB, sideA];
    const swappedGap = tradeGap(newA, newB, "full");
    expect(swappedGap).toBeLessThan(0);
    expect(verdictFromGap(swappedGap)).toBe("Major gap");
    expect(colorFromGap(swappedGap)).toBe("red"); // Now Side B wins

    // Remove an asset
    const trimmedB = removeAssetFromSide(newB, "Ja'Marr Chase");
    const newGap = tradeGap(newA, trimmedB, "full");
    // Power-weighted: B (8800+7000) vs A (9000). Gap is positive (B side wins after swap)
    expect(newGap).toBeGreaterThan(0);
    expect(newGap).toBeLessThan(15800 - 9000); // less than linear 6800

    // Serialize and restore
    const serialized = serializeWorkspace(newA, trimmedB, "full", "A");
    const rowByName = new Map([
      ["Josh Allen", ALLEN],
      ["Patrick Mahomes", MAHOMES],
      ["Ja'Marr Chase", CHASE],
      ["2026 Early 1st", PICK_2026],
    ]);
    const restored = deserializeWorkspace(serialized, rowByName);
    expect(restored.sideA.length).toBe(2);
    expect(restored.sideB.length).toBe(1);
    expect(tradeGap(restored.sideA, restored.sideB, "full")).toBe(newGap);
  });
});

// ── New features: power-weighted, edge, pick parsing, LAM, scarcity ──

describe("powerWeightedTotal", () => {
  it("single asset approximately equals its value", () => {
    expect(powerWeightedTotal([ALLEN], "full")).toBeCloseTo(9000, 0);
  });

  it("multiple assets yield less than linear sum", () => {
    const pw = powerWeightedTotal([ALLEN, CHASE], "full");
    const linear = 9000 + 8500;
    expect(pw).toBeLessThan(linear);
    expect(pw).toBeGreaterThan(9000); // more than single best
  });

  it("empty array returns 0", () => {
    expect(powerWeightedTotal([], "full")).toBe(0);
  });
});

describe("verdictBarPosition", () => {
  it("returns 50 for even trade", () => {
    expect(verdictBarPosition(0)).toBe(50);
  });

  it("returns > 50 when A ahead", () => {
    expect(verdictBarPosition(2000)).toBeGreaterThan(50);
  });

  it("returns < 50 when B ahead", () => {
    expect(verdictBarPosition(-2000)).toBeLessThan(50);
  });
});

describe("getPlayerEdge", () => {
  it("returns no signal when no canonical sites", () => {
    const result = getPlayerEdge({ values: { full: 5000 } });
    expect(result.signal).toBeNull();
  });

  it("returns BUY when our value is below external average", () => {
    const row = {
      values: { full: 5000 },
      canonicalSites: { ktc: 7000, fantasyCalc: 7500 },
    };
    const result = getPlayerEdge(row);
    expect(result.signal).toBe("BUY");
    expect(result.edgePct).toBeGreaterThan(0);
  });

  it("returns SELL when our value is above external average", () => {
    const row = {
      values: { full: 9000 },
      canonicalSites: { ktc: 6000, fantasyCalc: 6000 },
    };
    const result = getPlayerEdge(row);
    expect(result.signal).toBe("SELL");
  });
});

describe("parsePickToken", () => {
  it("parses slot format", () => {
    const p = parsePickToken("2026 1.06");
    expect(p.year).toBe("2026");
    expect(p.round).toBe("1st");
    expect(p.tier).toBe("mid");
    expect(p.slot).toBe(6);
  });

  it("parses label format", () => {
    const p = parsePickToken("2026 early 2nd");
    expect(p.year).toBe("2026");
    expect(p.round).toBe("2nd");
    expect(p.tier).toBe("early");
  });

  it("returns null for invalid", () => {
    expect(parsePickToken("not a pick")).toBeNull();
  });
});

describe("lamMultiplier", () => {
  it("returns 1 at strength 0", () => {
    expect(lamMultiplier("QB", 0, "superflex")).toBe(1);
  });

  it("QB gets premium in superflex", () => {
    expect(lamMultiplier("QB", 1, "superflex")).toBeGreaterThan(1);
  });

  it("QB gets discount in standard", () => {
    expect(lamMultiplier("QB", 1, "standard")).toBeLessThan(1);
  });
});

describe("buildScarcityModel", () => {
  it("builds model with pressure values", () => {
    const rows = Array.from({ length: 50 }, (_, i) => ({
      pos: i < 10 ? "QB" : i < 30 ? "RB" : "WR",
      values: { full: 9000 - i * 100 },
    }));
    const model = buildScarcityModel(rows);
    expect(model.QB).toBeDefined();
    expect(model.QB.poolSize).toBe(10);
    expect(model.RB.poolSize).toBe(20);
  });
});

describe("findBalancers", () => {
  it("returns players that could fill the gap", () => {
    const rosterRows = [
      { name: "P1", pos: "WR", values: { full: 500 } },
      { name: "P2", pos: "RB", values: { full: 1000 } },
      { name: "P3", pos: "QB", values: { full: 2000 } },
    ];
    const result = findBalancers(1000, rosterRows, "full");
    expect(result.length).toBeGreaterThan(0);
    expect(result[0].name).toBe("P2"); // closest to gap of 1000
  });

  it("returns empty for small gap", () => {
    expect(findBalancers(100, [], "full")).toEqual([]);
  });
});

// ── effectiveValue + settings-aware totals ───────────────────────────

describe("effectiveValue", () => {
  it("returns raw value when no settings provided", () => {
    expect(effectiveValue(ALLEN, "full")).toBe(9000);
    expect(effectiveValue(ALLEN, "full", null)).toBe(9000);
  });

  it("applies LAM multiplier from settings", () => {
    const sfSettings = { lamStrength: 1.0, leagueFormat: "superflex" };
    // QB in superflex gets 1.15x
    const val = effectiveValue(ALLEN, "full", sfSettings);
    expect(val).toBeCloseTo(9000 * 1.15, 0);
  });

  it("QB gets discount in standard format", () => {
    const stdSettings = { lamStrength: 1.0, leagueFormat: "standard" };
    // QB in standard gets 0.85x
    const val = effectiveValue(ALLEN, "full", stdSettings);
    expect(val).toBeCloseTo(9000 * 0.85, 0);
  });

  it("WR is unaffected by LAM in both formats", () => {
    const sfSettings = { lamStrength: 1.0, leagueFormat: "superflex" };
    // WR multiplier is 1.0 in superflex
    expect(effectiveValue(CHASE, "full", sfSettings)).toBeCloseTo(8500, 0);
  });

  it("strength 0 means no adjustment", () => {
    const settings = { lamStrength: 0, leagueFormat: "superflex" };
    expect(effectiveValue(ALLEN, "full", settings)).toBe(9000);
  });

  it("half strength interpolates", () => {
    const settings = { lamStrength: 0.5, leagueFormat: "superflex" };
    // QB superflex raw=1.15, at strength 0.5: 1 + (1.15-1)*0.5 = 1.075
    const val = effectiveValue(ALLEN, "full", settings);
    expect(val).toBeCloseTo(9000 * 1.075, 0);
  });
});

describe("settings-aware powerWeightedTotal", () => {
  it("applies LAM when settings provided", () => {
    const sfSettings = { lamStrength: 1.0, leagueFormat: "superflex" };
    const withSettings = powerWeightedTotal([ALLEN], "full", undefined, sfSettings);
    const without = powerWeightedTotal([ALLEN], "full");
    // QB in superflex gets premium, so with settings > without
    expect(withSettings).toBeGreaterThan(without);
  });

  it("settings=null behaves like no settings", () => {
    const a = powerWeightedTotal([ALLEN, CHASE], "full");
    const b = powerWeightedTotal([ALLEN, CHASE], "full", undefined, null);
    expect(a).toBe(b);
  });
});

describe("settings-aware sideTotal", () => {
  it("applies LAM when settings provided", () => {
    const sfSettings = { lamStrength: 1.0, leagueFormat: "superflex" };
    const withSettings = sideTotal([ALLEN], "full", sfSettings);
    expect(withSettings).toBeCloseTo(9000 * 1.15, 0);
  });

  it("mixed positions get different adjustments", () => {
    const sfSettings = { lamStrength: 1.0, leagueFormat: "superflex" };
    const total = sideTotal([ALLEN, CHASE], "full", sfSettings);
    // Allen: 9000 * 1.15 = 10350, Chase: 8500 * 1.0 = 8500
    expect(total).toBeCloseTo(10350 + 8500, 0);
  });
});

// ── Pick year discount ──────────────────────────────────────────────

describe("pickYearDiscount", () => {
  it("current year gets 1.0", () => {
    expect(pickYearDiscount("2026 Early 1st", 2026)).toBe(1.0);
  });

  it("year+1 gets 0.85", () => {
    expect(pickYearDiscount("2027 Mid 2nd", 2026)).toBe(0.85);
  });

  it("year+2 gets 0.72", () => {
    expect(pickYearDiscount("2028 Late 1st", 2026)).toBe(0.72);
  });

  it("year+3 gets 0.60", () => {
    expect(pickYearDiscount("2029 Early 1st", 2026)).toBe(0.60);
  });

  it("non-pick returns 1.0", () => {
    expect(pickYearDiscount("Josh Allen", 2026)).toBe(1.0);
  });
});

// ── TEP in effectiveValue ───────────────────────────────────────────

describe("effectiveValue with TEP", () => {
  const TE_ROW = makeRow("Mark Andrews", 4000, "TE");

  it("TE gets tepMultiplier boost", () => {
    const settings = { lamStrength: 0, leagueFormat: "superflex", tepMultiplier: 1.15 };
    const val = effectiveValue(TE_ROW, "full", settings);
    expect(val).toBeCloseTo(4000 * 1.15, 0);
  });

  it("TE gets no boost when tepMultiplier is 1.0", () => {
    const settings = { lamStrength: 0, leagueFormat: "superflex", tepMultiplier: 1.0 };
    const val = effectiveValue(TE_ROW, "full", settings);
    expect(val).toBe(4000);
  });

  it("non-TE is unaffected by tepMultiplier", () => {
    const settings = { lamStrength: 0, leagueFormat: "superflex", tepMultiplier: 1.15 };
    const val = effectiveValue(CHASE, "full", settings);
    expect(val).toBe(8500);
  });
});

// ── Pick year discount in effectiveValue ────────────────────────────

describe("effectiveValue with pick discount", () => {
  const PICK_2027 = makeRow("2027 Early 1st", 7000, "PICK", "pick");

  it("future pick gets discounted", () => {
    const settings = { lamStrength: 0, leagueFormat: "superflex", pickCurrentYear: 2026 };
    const val = effectiveValue(PICK_2027, "full", settings);
    expect(val).toBeCloseTo(7000 * 0.85, 0);
  });

  it("current year pick is not discounted", () => {
    const settings = { lamStrength: 0, leagueFormat: "superflex", pickCurrentYear: 2027 };
    const val = effectiveValue(PICK_2027, "full", settings);
    expect(val).toBe(7000);
  });
});
