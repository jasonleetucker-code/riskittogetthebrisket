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
  buildPickLookupCandidates,
  resolvePickRow,
  findBalancers,
  verdictBarPosition,
  meterVerdict,
  percentageGap,
  multiTeamAnalysis,
  createSide,
  serializeWorkspaceMulti,
  deserializeWorkspaceMulti,
  SIDE_LABELS,
  MAX_SIDES,
  MIN_SIDES,
} from "@/lib/trade-logic";

// ── Test fixtures ────────────────────────────────────────────────────

function makeRow(name, fullValue, pos = "QB", assetClass = "offense") {
  return {
    name,
    pos,
    assetClass,
    values: { full: fullValue, raw: fullValue },
  };
}

const ALLEN = makeRow("Josh Allen", 9000);
const MAHOMES = makeRow("Patrick Mahomes", 8800);
const CHASE = makeRow("Ja'Marr Chase", 8500, "WR");
const PARSONS = makeRow("Micah Parsons", 5000, "LB", "idp");
const PICK_2026 = makeRow("2026 Early 1st", 7000, "PICK", "pick");

// ── Constants ────────────────────────────────────────────────────────

describe("constants", () => {
  it("VALUE_MODES has 2 modes", () => {
    expect(VALUE_MODES.length).toBe(2);
    expect(VALUE_MODES.map((m) => m.key)).toEqual(["full", "raw"]);
  });

  it("storage keys are stable strings", () => {
    expect(STORAGE_KEY).toBe("next_trade_workspace_v1");
    expect(RECENT_KEY).toBe("next_trade_recent_assets_v1");
  });
});

// ── verdictFromGap ───────────────────────────────────────────────────

describe("verdictFromGap", () => {
  // Thresholds on 1–9999 display scale: 350, 900, 1800
  it("returns 'Near even' for gaps under 350", () => {
    expect(verdictFromGap(0)).toBe("Near even");
    expect(verdictFromGap(349)).toBe("Near even");
    expect(verdictFromGap(-349)).toBe("Near even");
  });

  it("returns 'Lean' for gaps 350-899", () => {
    expect(verdictFromGap(350)).toBe("Lean");
    expect(verdictFromGap(899)).toBe("Lean");
    expect(verdictFromGap(-500)).toBe("Lean");
  });

  it("returns 'Strong lean' for gaps 900-1799", () => {
    expect(verdictFromGap(900)).toBe("Strong lean");
    expect(verdictFromGap(1799)).toBe("Strong lean");
    expect(verdictFromGap(-1200)).toBe("Strong lean");
  });

  it("returns 'Major gap' for gaps >= 1800", () => {
    expect(verdictFromGap(1800)).toBe("Major gap");
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
      values: { full: 9000, raw: 7000 },
    };
    expect(sideTotal([row], "raw")).toBe(7000);
    expect(sideTotal([row], "full")).toBe(9000);
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
    expect(verdictFromGap(gap)).toBe("Strong lean");
    expect(colorFromGap(gap)).toBe("green"); // Side A wins

    // Swap sides
    const [newA, newB] = [sideB, sideA];
    const swappedGap = tradeGap(newA, newB, "full");
    expect(swappedGap).toBeLessThan(0);
    expect(verdictFromGap(swappedGap)).toBe("Strong lean");
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

// ── New features: power-weighted, edge, pick parsing ──

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
      canonicalSites: { ktc: 7000 },
    };
    const result = getPlayerEdge(row);
    expect(result.signal).toBe("BUY");
    expect(result.edgePct).toBeGreaterThan(0);
  });

  it("returns SELL when our value is above external average", () => {
    const row = {
      values: { full: 9000 },
      canonicalSites: { ktc: 6000 },
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

describe("buildPickLookupCandidates", () => {
  it("emits 'Pick' canonical for Sleeper slot labels with (from X)", () => {
    const c = buildPickLookupCandidates("2026 1.04 (from Chargers Team Doctor)");
    expect(c).toContain("2026 pick 1.04");
    expect(c).toContain("2026 1.04");
    // Also emits tier fallback
    expect(c).toContain("2026 early 1st");
  });

  it("handles (own) annotation", () => {
    const c = buildPickLookupCandidates("2026 5.04 (own)");
    expect(c).toContain("2026 pick 5.04");
    expect(c).toContain("2026 5.04");
  });

  it("handles tier-based labels for future years", () => {
    const c = buildPickLookupCandidates("2027 Mid 1st (own)");
    expect(c).toContain("2027 mid 1st");
    // Tier-centre slot fallback for years that DO have slot rows
    expect(c).toContain("2027 pick 1.06");
  });

  it("returns an empty list for blank input", () => {
    expect(buildPickLookupCandidates("")).toEqual([]);
    expect(buildPickLookupCandidates(null)).toEqual([]);
  });
});

describe("resolvePickRow", () => {
  function mkLookup(entries) {
    const m = new Map();
    for (const [name, value] of entries) {
      m.set(name.toLowerCase(), { name, pos: "PICK", values: { full: value } });
    }
    return m;
  }

  it("resolves Sleeper slot label against rankings 'Pick' row", () => {
    const lookup = mkLookup([["2026 Pick 1.04", 9123]]);
    const row = resolvePickRow("2026 1.04 (from Rage Against The Achane)", lookup);
    expect(row).not.toBeNull();
    expect(row.values.full).toBe(9123);
  });

  it("resolves tier label against tier-based rankings row", () => {
    const lookup = mkLookup([["2027 Mid 1st", 6800]]);
    const row = resolvePickRow("2027 Mid 1st (own)", lookup);
    expect(row).not.toBeNull();
    expect(row.values.full).toBe(6800);
  });

  it("uses pickAliases map when direct candidates miss", () => {
    const lookup = mkLookup([["2026 Pick 1.06", 7700]]);
    const aliases = { "2026 Mid 1st": "2026 Pick 1.06" };
    const row = resolvePickRow("2026 Mid 1st (own)", lookup, aliases);
    expect(row).not.toBeNull();
    expect(row.values.full).toBe(7700);
  });

  it("prefers pickAliases over a suppressed generic-tier row", () => {
    // Backend kept the suppressed generic-tier row on the board (with
    // stale value 1) so name search still resolves it, but pickAliases
    // authoritatively redirects to the slot-specific row (value 7700).
    const m = new Map();
    m.set("2026 mid 1st", {
      name: "2026 Mid 1st",
      pos: "PICK",
      values: { full: 1 },
      raw: { pickGenericSuppressed: true },
    });
    m.set("2026 pick 1.06", { name: "2026 Pick 1.06", pos: "PICK", values: { full: 7700 } });
    const aliases = { "2026 Mid 1st": "2026 Pick 1.06" };
    const row = resolvePickRow("2026 Mid 1st (own)", m, aliases);
    expect(row).not.toBeNull();
    expect(row.name).toBe("2026 Pick 1.06");
    expect(row.values.full).toBe(7700);
  });

  it("skips suppressed generic-tier rows during direct lookup fallback", () => {
    // No pickAliases available — resolver must still skip the
    // suppressed row and continue to the slot-specific candidate that
    // buildPickLookupCandidates derives from the tier-centre slot.
    const m = new Map();
    m.set("2026 mid 1st", {
      name: "2026 Mid 1st",
      pos: "PICK",
      values: { full: 1 },
      raw: { pickGenericSuppressed: true },
    });
    m.set("2026 pick 1.06", { name: "2026 Pick 1.06", pos: "PICK", values: { full: 7700 } });
    const row = resolvePickRow("2026 Mid 1st (own)", m);
    expect(row).not.toBeNull();
    expect(row.name).toBe("2026 Pick 1.06");
    expect(row.values.full).toBe(7700);
  });

  it("does not apply alias redirects to derived tier candidates for slot inputs", () => {
    // Sleeper emits a slot label.  pickAliases contains generic-tier
    // redirects that would point derived candidates at the WRONG slot
    // (Early→1.02, Mid→1.06, Late→1.10).  The resolver must only
    // apply aliases to the input label itself, not to synthesized
    // derived candidates, or slot picks get rewritten to the
    // tier-centre slot.
    const m = new Map();
    m.set("2026 pick 1.04", { name: "2026 Pick 1.04", pos: "PICK", values: { full: 9200 } });
    m.set("2026 pick 1.02", { name: "2026 Pick 1.02", pos: "PICK", values: { full: 9500 } });
    const aliases = { "2026 Early 1st": "2026 Pick 1.02" };
    const row = resolvePickRow("2026 1.04 (from Team X)", m, aliases);
    expect(row).not.toBeNull();
    expect(row.name).toBe("2026 Pick 1.04");
    expect(row.values.full).toBe(9200);
  });

  it("resolves round 6 slot picks", () => {
    const lookup = mkLookup([["2026 Pick 6.04", 420]]);
    const row = resolvePickRow("2026 6.04 (own)", lookup);
    expect(row).not.toBeNull();
    expect(row.name).toBe("2026 Pick 6.04");
    expect(row.values.full).toBe(420);
  });

  it("resolves round 6 tier labels", () => {
    const lookup = mkLookup([["2027 Mid 6th", 280]]);
    const row = resolvePickRow("2027 Mid 6th (own)", lookup);
    expect(row).not.toBeNull();
    expect(row.values.full).toBe(280);
  });

  it("returns null when nothing matches", () => {
    const lookup = mkLookup([["2026 Pick 1.04", 9000]]);
    expect(resolvePickRow("2099 1.01", lookup)).toBeNull();
  });
});

describe("parsePickToken round 6", () => {
  it("parses slot format round 6", () => {
    const p = parsePickToken("2026 6.04");
    expect(p).not.toBeNull();
    expect(p.year).toBe("2026");
    expect(p.round).toBe("6th");
    expect(p.slot).toBe(4);
  });

  it("parses tier label round 6", () => {
    const p = parsePickToken("2027 Mid 6th");
    expect(p).not.toBeNull();
    expect(p.year).toBe("2027");
    expect(p.round).toBe("6th");
    expect(p.tier).toBe("mid");
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

  it("returns raw value with settings (no adjustment)", () => {
    const settings = { leagueFormat: "superflex" };
    expect(effectiveValue(ALLEN, "full", settings)).toBe(9000);
  });
});

describe("settings-aware powerWeightedTotal", () => {
  it("settings=null behaves like no settings", () => {
    const a = powerWeightedTotal([ALLEN, CHASE], "full");
    const b = powerWeightedTotal([ALLEN, CHASE], "full", undefined, null);
    expect(a).toBe(b);
  });
});

describe("settings-aware sideTotal", () => {
  it("returns sum without adjustment", () => {
    const settings = { leagueFormat: "superflex" };
    const total = sideTotal([ALLEN, CHASE], "full", settings);
    expect(total).toBe(9000 + 8500);
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

// ── TEP is backend-authoritative — effectiveValue MUST NOT re-apply it ──
//
// The TE-premium multiplier is threaded through the backend rankings
// override pipeline (see src/api/data_contract.py::_compute_unified_rankings
// and frontend/lib/dynasty-data.js::fetchDynastyData).  By the time a
// TE row reaches `effectiveValue`, its ``values.full`` already reflects
// the TEP-adjusted blended value.  If we multiplied again here we'd
// double-boost every TE whenever the slider is > 1.0 AND would miss
// the TEP-native source carve-out.  These tests pin that behavior.

describe("effectiveValue leaves TEP alone (backend-authoritative)", () => {
  const TE_ROW = makeRow("Mark Andrews", 4000, "TE");

  it("TE full value is returned verbatim even with tepMultiplier set", () => {
    const settings = { leagueFormat: "superflex", tepMultiplier: 1.15 };
    const val = effectiveValue(TE_ROW, "full", settings);
    // Backend already baked in the TEP boost — effectiveValue returns
    // values.full untouched.  The input fixture has values.full=4000,
    // which is what we get back.
    expect(val).toBe(4000);
  });

  it("TE full value is returned verbatim when tepMultiplier is 1.0", () => {
    const settings = { leagueFormat: "superflex", tepMultiplier: 1.0 };
    const val = effectiveValue(TE_ROW, "full", settings);
    expect(val).toBe(4000);
  });

  it("non-TE is also untouched regardless of tepMultiplier", () => {
    const settings = { leagueFormat: "superflex", tepMultiplier: 1.5 };
    const val = effectiveValue(CHASE, "full", settings);
    expect(val).toBe(8500);
  });

  it("pick year discount still applies for future picks", () => {
    // The pick year discount path is the only remaining adjustment
    // inside effectiveValue.  Backend TEP lives elsewhere.
    const FUTURE_PICK = makeRow("2028 Early 1st", 7000, "PICK", "pick");
    const settings = {
      leagueFormat: "superflex",
      tepMultiplier: 1.15,
      pickCurrentYear: 2026,
    };
    const val = effectiveValue(FUTURE_PICK, "full", settings);
    // 2028 - 2026 = 2 year discount = 0.72 multiplier
    expect(val).toBeCloseTo(7000 * 0.72, 0);
  });
});

// ── Pick year discount in effectiveValue ────────────────────────────

describe("effectiveValue with pick discount", () => {
  const PICK_2027 = makeRow("2027 Early 1st", 7000, "PICK", "pick");

  it("future pick gets discounted", () => {
    const settings = { leagueFormat: "superflex", pickCurrentYear: 2026 };
    const val = effectiveValue(PICK_2027, "full", settings);
    expect(val).toBeCloseTo(7000 * 0.85, 0);
  });

  it("current year pick is not discounted", () => {
    const settings = { leagueFormat: "superflex", pickCurrentYear: 2027 };
    const val = effectiveValue(PICK_2027, "full", settings);
    expect(val).toBe(7000);
  });
});

// ══════════════════════════════════════════════════════════════════════════
// NEW: Trade Meter + Multi-Team tests
// ══════════════════════════════════════════════════════════════════════════

// ── meterVerdict ────────────────────────────────────────────────────────

describe("meterVerdict", () => {
  it("returns FAIR for gap < 350", () => {
    expect(meterVerdict(0)).toEqual({ label: "FAIR", level: "fair" });
    expect(meterVerdict(349)).toEqual({ label: "FAIR", level: "fair" });
  });

  it("returns SLIGHT EDGE for gap 350-899", () => {
    expect(meterVerdict(350)).toEqual({ label: "SLIGHT EDGE", level: "slight" });
    expect(meterVerdict(899)).toEqual({ label: "SLIGHT EDGE", level: "slight" });
  });

  it("returns UNFAIR for gap 900-1799", () => {
    expect(meterVerdict(900)).toEqual({ label: "UNFAIR", level: "unfair" });
    expect(meterVerdict(1799)).toEqual({ label: "UNFAIR", level: "unfair" });
  });

  it("returns LOPSIDED for gap >= 1800", () => {
    expect(meterVerdict(1800)).toEqual({ label: "LOPSIDED", level: "lopsided" });
    expect(meterVerdict(5000)).toEqual({ label: "LOPSIDED", level: "lopsided" });
  });
});

// ── percentageGap ───────────────────────────────────────────────────────

describe("percentageGap", () => {
  it("returns 0 when both sides are 0", () => {
    expect(percentageGap(0, 0)).toBe(0);
  });

  it("returns 100% when one side is empty", () => {
    expect(percentageGap(5000, 0)).toBe(100);
    expect(percentageGap(0, 5000)).toBe(100);
  });

  it("returns correct percentage for unequal sides", () => {
    // |5000 - 4000| / 5000 * 100 = 20%
    expect(percentageGap(5000, 4000)).toBe(20);
    expect(percentageGap(4000, 5000)).toBe(20);
  });

  it("returns 0 when sides are equal", () => {
    expect(percentageGap(3000, 3000)).toBe(0);
  });
});

// ── multiTeamAnalysis ───────────────────────────────────────────────────

describe("multiTeamAnalysis", () => {
  it("reports balanced for equal totals", () => {
    const result = multiTeamAnalysis([1000, 1000, 1000]);
    expect(result.overall).toBe("Balanced");
    expect(result.shares).toEqual([33, 33, 33]);
    result.perTeam.forEach((t) => expect(t).toBe("Fair share"));
  });

  it("reports imbalanced when one team overpays", () => {
    const result = multiTeamAnalysis([5000, 1000, 1000]);
    expect(result.overall).toBe("Imbalanced");
    expect(result.perTeam[0]).toBe("Overpaying");
    expect(result.perTeam[1]).toBe("Getting a deal");
    expect(result.perTeam[2]).toBe("Getting a deal");
  });

  it("handles all-zero totals", () => {
    const result = multiTeamAnalysis([0, 0, 0]);
    expect(result.overall).toBe("Empty");
    expect(result.shares).toEqual([0, 0, 0]);
  });

  it("works with 5 teams", () => {
    const result = multiTeamAnalysis([2000, 2000, 2000, 2000, 2000]);
    expect(result.overall).toBe("Balanced");
    expect(result.shares.length).toBe(5);
  });
});

// ── createSide ──────────────────────────────────────────────────────────

describe("createSide", () => {
  it("creates side with correct label", () => {
    expect(createSide(0)).toEqual({ id: 0, label: "A", assets: [] });
    expect(createSide(1)).toEqual({ id: 1, label: "B", assets: [] });
    expect(createSide(4)).toEqual({ id: 4, label: "E", assets: [] });
  });
});

// ── constants ───────────────────────────────────────────────────────────

describe("multi-team constants", () => {
  it("SIDE_LABELS has 5 labels", () => {
    expect(SIDE_LABELS).toEqual(["A", "B", "C", "D", "E"]);
  });

  it("MAX_SIDES is 5, MIN_SIDES is 2", () => {
    expect(MAX_SIDES).toBe(5);
    expect(MIN_SIDES).toBe(2);
  });
});

// ── serializeWorkspaceMulti / deserializeWorkspaceMulti ─────────────────

describe("serializeWorkspaceMulti", () => {
  it("serializes sides array with version 2", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN] },
      { id: 1, label: "B", assets: [CHASE] },
    ];
    const result = serializeWorkspaceMulti(sides, "full", 0);
    expect(result.version).toBe(2);
    expect(result.sides.length).toBe(2);
    expect(result.sides[0].assets).toEqual(["Josh Allen"]);
    expect(result.sides[1].assets).toEqual(["Ja'Marr Chase"]);
    expect(result.valueMode).toBe("full");
    expect(result.activeSide).toBe(0);
  });

  it("handles 3+ sides", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN] },
      { id: 1, label: "B", assets: [CHASE] },
      { id: 2, label: "C", assets: [PARSONS] },
    ];
    const result = serializeWorkspaceMulti(sides, "raw", 2);
    expect(result.sides.length).toBe(3);
    expect(result.sides[2].label).toBe("C");
    expect(result.activeSide).toBe(2);
  });
});

describe("deserializeWorkspaceMulti", () => {
  const rowByName = new Map([
    ["Josh Allen", ALLEN],
    ["Ja'Marr Chase", CHASE],
    ["Patrick Mahomes", MAHOMES],
    ["Micah Parsons", PARSONS],
  ]);

  it("restores version 2 format", () => {
    const parsed = {
      version: 2,
      valueMode: "full",
      activeSide: 1,
      sides: [
        { label: "A", assets: ["Josh Allen"] },
        { label: "B", assets: ["Ja'Marr Chase"] },
      ],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.sides.length).toBe(2);
    expect(result.sides[0].assets[0].name).toBe("Josh Allen");
    expect(result.sides[1].assets[0].name).toBe("Ja'Marr Chase");
    expect(result.activeSide).toBe(1);
    expect(result.valueMode).toBe("full");
  });

  it("migrates legacy sideA/sideB format", () => {
    const parsed = {
      valueMode: "raw",
      activeSide: "B",
      sideA: ["Josh Allen"],
      sideB: ["Ja'Marr Chase"],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.sides.length).toBe(2);
    expect(result.sides[0].label).toBe("A");
    expect(result.sides[0].assets[0].name).toBe("Josh Allen");
    expect(result.sides[1].label).toBe("B");
    expect(result.sides[1].assets[0].name).toBe("Ja'Marr Chase");
    expect(result.activeSide).toBe(1); // "B" → 1
    expect(result.valueMode).toBe("raw");
  });

  it("migrates legacy format with activeSide A", () => {
    const parsed = {
      valueMode: "full",
      activeSide: "A",
      sideA: ["Patrick Mahomes"],
      sideB: [],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.activeSide).toBe(0); // "A" → 0
    expect(result.sides[0].assets[0].name).toBe("Patrick Mahomes");
    expect(result.sides[1].assets.length).toBe(0);
  });

  it("ensures at least 2 sides even if stored data has fewer", () => {
    const parsed = {
      version: 2,
      valueMode: "full",
      activeSide: 0,
      sides: [{ label: "A", assets: [] }],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.sides.length).toBe(2);
  });

  it("drops unknown player names during migration", () => {
    const parsed = {
      sideA: ["Josh Allen", "Unknown Player"],
      sideB: [],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.sides[0].assets.length).toBe(1);
    expect(result.sides[0].assets[0].name).toBe("Josh Allen");
  });

  it("returns null for null/non-object input", () => {
    expect(deserializeWorkspaceMulti(null, rowByName)).toBeNull();
    expect(deserializeWorkspaceMulti("bad", rowByName)).toBeNull();
  });

  it("defaults to full mode for invalid valueMode", () => {
    const parsed = { version: 2, valueMode: "invalid", activeSide: 0, sides: [] };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.valueMode).toBe("full");
  });

  it("clamps activeSide to valid range", () => {
    const parsed = {
      version: 2,
      valueMode: "full",
      activeSide: 99,
      sides: [
        { label: "A", assets: [] },
        { label: "B", assets: [] },
      ],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.activeSide).toBe(1); // clamped to sides.length - 1
  });

  it("restores 3+ sides in version 2 format", () => {
    const parsed = {
      version: 2,
      valueMode: "full",
      activeSide: 2,
      sides: [
        { label: "A", assets: ["Josh Allen"] },
        { label: "B", assets: ["Ja'Marr Chase"] },
        { label: "C", assets: ["Micah Parsons"] },
      ],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.sides.length).toBe(3);
    expect(result.sides[2].assets[0].name).toBe("Micah Parsons");
    expect(result.activeSide).toBe(2);
  });
});

// ── Multi-team total calculations ──────────────────────────────────────

describe("multi-team total calculations", () => {
  it("powerWeightedTotal works for any side array", () => {
    const sideAssets = [ALLEN, CHASE, PARSONS];
    const total = powerWeightedTotal(sideAssets, "full");
    expect(total).toBeGreaterThan(0);
    expect(total).toBeLessThan(9000 + 8500 + 5000); // less than linear
  });

  it("sideTotal works for 3+ sides independently", () => {
    const totals = [
      sideTotal([ALLEN], "full"),
      sideTotal([CHASE], "full"),
      sideTotal([PARSONS], "full"),
    ];
    expect(totals).toEqual([9000, 8500, 5000]);
  });
});
