import { describe, expect, it } from "vitest";
import {
  tierLabel,
  rankBasedTierLabel,
  rankBasedTierId,
  effectiveTierId,
  valueBand,
  rowChips,
  DEFAULT_ROW_LIMIT,
} from "../lib/rankings-helpers.js";

// ── tierLabel ────────────────────────────────────────────────────────

describe("tierLabel", () => {
  it("uses backend canonicalTierId when present", () => {
    expect(tierLabel({ canonicalTierId: 1, rank: 5 })).toBe("Tier 1");
    expect(tierLabel({ canonicalTierId: 2, rank: 20 })).toBe("Tier 2");
    expect(tierLabel({ canonicalTierId: 5, rank: 150 })).toBe("Tier 5");
    expect(tierLabel({ canonicalTierId: 12, rank: 700 })).toBe("Tier 12");
  });

  it("falls back to rank-based when canonicalTierId is null", () => {
    expect(tierLabel({ canonicalTierId: null, rank: 1 })).toBe("Tier 1");
    expect(tierLabel({ rank: 50 })).toBe("Tier 3");
    expect(tierLabel({ rank: 400 })).toBe("Tier 7");
  });

  it("returns Unranked for null/0 rank and no tierId", () => {
    expect(tierLabel({ rank: null })).toBe("Unranked");
    expect(tierLabel({ rank: 0 })).toBe("Unranked");
    expect(tierLabel({})).toBe("Unranked");
  });
});

// ── rankBasedTierLabel ───────────────────────────────────────────────

describe("rankBasedTierLabel", () => {
  it("returns the numeric tier label mirroring rankBasedTierId", () => {
    expect(rankBasedTierLabel(1)).toBe("Tier 1");
    expect(rankBasedTierLabel(12)).toBe("Tier 1");
    expect(rankBasedTierLabel(13)).toBe("Tier 2");
    expect(rankBasedTierLabel(36)).toBe("Tier 2");
    expect(rankBasedTierLabel(37)).toBe("Tier 3");
    expect(rankBasedTierLabel(120)).toBe("Tier 4");
    expect(rankBasedTierLabel(200)).toBe("Tier 5");
    expect(rankBasedTierLabel(350)).toBe("Tier 6");
    expect(rankBasedTierLabel(500)).toBe("Tier 7");
    expect(rankBasedTierLabel(650)).toBe("Tier 8");
    expect(rankBasedTierLabel(800)).toBe("Tier 9");
    expect(rankBasedTierLabel(801)).toBe("Tier 10");
  });

  it("handles edge cases", () => {
    expect(rankBasedTierLabel(null)).toBe("Unranked");
    expect(rankBasedTierLabel(0)).toBe("Unranked");
    expect(rankBasedTierLabel(-5)).toBe("Unranked");
  });
});

// ── rankBasedTierId ──────────────────────────────────────────────────

describe("rankBasedTierId", () => {
  it("returns correct tier IDs", () => {
    expect(rankBasedTierId(1)).toBe(1);
    expect(rankBasedTierId(20)).toBe(2);
    expect(rankBasedTierId(50)).toBe(3);
    expect(rankBasedTierId(100)).toBe(4);
    expect(rankBasedTierId(150)).toBe(5);
    expect(rankBasedTierId(300)).toBe(6);
    expect(rankBasedTierId(400)).toBe(7);
    expect(rankBasedTierId(600)).toBe(8);
    expect(rankBasedTierId(700)).toBe(9);
    expect(rankBasedTierId(900)).toBe(10);
  });

  it("returns null for invalid ranks", () => {
    expect(rankBasedTierId(null)).toBe(null);
    expect(rankBasedTierId(0)).toBe(null);
  });
});

// ── effectiveTierId ──────────────────────────────────────────────────

describe("effectiveTierId", () => {
  it("prefers backend canonicalTierId", () => {
    expect(effectiveTierId({ canonicalTierId: 3, rank: 1 })).toBe(3);
  });

  it("falls back to rank-based", () => {
    expect(effectiveTierId({ canonicalTierId: null, rank: 50 })).toBe(3);
    expect(effectiveTierId({ rank: 200 })).toBe(5);
  });
});

// ── valueBand ────────────────────────────────────────────────────────

describe("valueBand", () => {
  // Value-band labels are short symbols (S+ / S / D+ / D / F)
  // intentionally distinct from the tier labels above so the row
  // tier badge and the value-band column can never visually collide.
  // The CSS class names are still vb-elite / vb-bluechip / etc. so
  // any styling pinned to those classes still works.
  it("classifies values into correct bands", () => {
    expect(valueBand(9999).label).toBe("S+");
    expect(valueBand(8000).label).toBe("S+");
    expect(valueBand(7999).label).toBe("S");
    expect(valueBand(6000).label).toBe("S");
    expect(valueBand(5999).label).toBe("D+");
    expect(valueBand(4000).label).toBe("D+");
    expect(valueBand(3999).label).toBe("D");
    expect(valueBand(2000).label).toBe("D");
    expect(valueBand(1999).label).toBe("F");
    expect(valueBand(1).label).toBe("F");
  });

  it("returns dash for zero/null", () => {
    expect(valueBand(0).label).toBe("\u2014");
    expect(valueBand(null).label).toBe("\u2014");
  });

  it("includes css class names", () => {
    expect(valueBand(9000).css).toBe("vb-elite");
    expect(valueBand(6500).css).toBe("vb-bluechip");
    expect(valueBand(4500).css).toBe("vb-starter");
    expect(valueBand(2500).css).toBe("vb-depth");
    expect(valueBand(500).css).toBe("vb-fringe");
  });

  it("never returns a label that looks like a tier label", () => {
    // Tier row headers render as "Tier N".  Value-band labels are
    // short alpha symbols (S+/S/D+/D/F) so they cannot visually
    // collide with the tier header on the same row.
    for (const v of [9000, 7000, 5000, 3000, 1000]) {
      expect(valueBand(v).label).not.toMatch(/^Tier\s/);
    }
  });
});

// ── rowChips ─────────────────────────────────────────────────────────

describe("rowChips", () => {
  it("returns empty for clean row", () => {
    const chips = rowChips({
      rookie: false,
      isSingleSource: false,
      anomalyFlags: [],
      hasSourceDisagreement: false,
    });
    expect(chips).toEqual([]);
  });

  it("returns R chip for rookies", () => {
    const chips = rowChips({ rookie: true, anomalyFlags: [] });
    expect(chips).toHaveLength(1);
    expect(chips[0].label).toBe("R");
    expect(chips[0].css).toBe("badge-green");
  });

  it("returns 1-src chip for semantic single-source players", () => {
    const chips = rowChips({
      isSingleSource: true,
      anomalyFlags: [],
      sourceAudit: { reason: "matching_failure_other_sources_eligible" },
    });
    expect(chips).toHaveLength(1);
    expect(chips[0].label).toBe("1-src");
    expect(chips[0].title).toContain("matching_failure");
  });

  it("returns solo (not 1-src) chip for structurally single-source players", () => {
    const chips = rowChips({
      isSingleSource: false,
      isStructurallySingleSource: true,
      anomalyFlags: [],
    });
    expect(chips).toHaveLength(1);
    expect(chips[0].label).toBe("solo");
    expect(chips[0].css).toBe("badge-blue");
  });

  it("returns ! chip for flagged players", () => {
    const chips = rowChips({ anomalyFlags: ["position_source_contradiction"] });
    expect(chips).toHaveLength(1);
    expect(chips[0].label).toBe("!");
    expect(chips[0].css).toBe("badge-red");
  });

  it("returns ~ chip for source disagreement", () => {
    const chips = rowChips({ hasSourceDisagreement: true, anomalyFlags: [] });
    expect(chips).toHaveLength(1);
    expect(chips[0].label).toBe("~");
  });

  it("can return multiple chips", () => {
    const chips = rowChips({
      rookie: true,
      isSingleSource: true,
      anomalyFlags: ["offense_as_idp"],
      hasSourceDisagreement: true,
    });
    expect(chips.length).toBe(4);
  });
});

// ── DEFAULT_ROW_LIMIT ────────────────────────────────────────────────

describe("DEFAULT_ROW_LIMIT", () => {
  it("is a reasonable number for initial display", () => {
    expect(DEFAULT_ROW_LIMIT).toBeGreaterThanOrEqual(100);
    expect(DEFAULT_ROW_LIMIT).toBeLessThanOrEqual(400);
  });
});
