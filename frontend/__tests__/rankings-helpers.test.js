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
    expect(tierLabel({ canonicalTierId: 1, rank: 5 })).toBe("Elite");
    expect(tierLabel({ canonicalTierId: 2, rank: 20 })).toBe("Blue-Chip");
    expect(tierLabel({ canonicalTierId: 5, rank: 150 })).toBe("Starter");
  });

  it("falls back to generic label for tier IDs > 10", () => {
    expect(tierLabel({ canonicalTierId: 12, rank: 700 })).toBe("Tier 12");
  });

  it("falls back to rank-based when canonicalTierId is null", () => {
    expect(tierLabel({ canonicalTierId: null, rank: 1 })).toBe("Elite");
    expect(tierLabel({ rank: 50 })).toBe("Premium Starter");
    expect(tierLabel({ rank: 400 })).toBe("Bench Depth");
  });

  it("returns Unranked for null/0 rank and no tierId", () => {
    expect(tierLabel({ rank: null })).toBe("Unranked");
    expect(tierLabel({ rank: 0 })).toBe("Unranked");
    expect(tierLabel({})).toBe("Unranked");
  });
});

// ── rankBasedTierLabel ───────────────────────────────────────────────

describe("rankBasedTierLabel", () => {
  it("maps rank boundaries correctly", () => {
    expect(rankBasedTierLabel(1)).toBe("Elite");
    expect(rankBasedTierLabel(12)).toBe("Elite");
    expect(rankBasedTierLabel(13)).toBe("Blue-Chip");
    expect(rankBasedTierLabel(36)).toBe("Blue-Chip");
    expect(rankBasedTierLabel(37)).toBe("Premium Starter");
    expect(rankBasedTierLabel(72)).toBe("Premium Starter");
    expect(rankBasedTierLabel(73)).toBe("Solid Starter");
    expect(rankBasedTierLabel(120)).toBe("Solid Starter");
    expect(rankBasedTierLabel(121)).toBe("Starter");
    expect(rankBasedTierLabel(200)).toBe("Starter");
    expect(rankBasedTierLabel(201)).toBe("Flex / Depth");
    expect(rankBasedTierLabel(350)).toBe("Flex / Depth");
    expect(rankBasedTierLabel(351)).toBe("Bench Depth");
    expect(rankBasedTierLabel(500)).toBe("Bench Depth");
    expect(rankBasedTierLabel(501)).toBe("Deep Stash");
    expect(rankBasedTierLabel(650)).toBe("Deep Stash");
    expect(rankBasedTierLabel(651)).toBe("Roster Fringe");
    expect(rankBasedTierLabel(800)).toBe("Roster Fringe");
    expect(rankBasedTierLabel(801)).toBe("Waiver Wire");
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
  it("classifies values into correct bands", () => {
    expect(valueBand(9999).label).toBe("Elite");
    expect(valueBand(8000).label).toBe("Elite");
    expect(valueBand(7999).label).toBe("Blue-Chip");
    expect(valueBand(6000).label).toBe("Blue-Chip");
    expect(valueBand(5999).label).toBe("Starter");
    expect(valueBand(4000).label).toBe("Starter");
    expect(valueBand(3999).label).toBe("Depth");
    expect(valueBand(2000).label).toBe("Depth");
    expect(valueBand(1999).label).toBe("Fringe");
    expect(valueBand(1).label).toBe("Fringe");
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

  it("returns 1-src chip for single-source players", () => {
    const chips = rowChips({ isSingleSource: true, anomalyFlags: [] });
    expect(chips).toHaveLength(1);
    expect(chips[0].label).toBe("1-src");
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
