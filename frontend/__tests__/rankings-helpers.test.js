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
  // The backend `canonicalTierId` field is per-universe (offense vs
  // IDP), and on a unified offense + IDP board it does not align with
  // the displayed sort order — that misalignment was the root cause
  // of the off-by-one tier headers (a "STARTER" boundary appearing
  // *after* a player instead of before the full tier).  The label is
  // now derived strictly from `row.rank`, which the backend
  // (`resort_unified_board_by_value`) and the frontend (`buildRows`)
  // both keep monotonic in displayed value.
  it("derives label from row.rank, ignoring per-universe canonicalTierId", () => {
    // Even with a stale canonicalTierId the rank wins.
    expect(tierLabel({ canonicalTierId: 1, rank: 150 })).toBe("Starter");
    expect(tierLabel({ canonicalTierId: 12, rank: 5 })).toBe("Elite");
    expect(tierLabel({ canonicalTierId: null, rank: 50 })).toBe("Premium Starter");
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
  // Always derives from row.rank for the same reason tierLabel does
  // — per-universe canonicalTierId from the canonical engine
  // disagrees with the unified offense + IDP sort and produces
  // off-by-one section headers when used directly.
  it("derives the tier id from row.rank, ignoring stale canonicalTierId", () => {
    expect(effectiveTierId({ canonicalTierId: 3, rank: 1 })).toBe(1);
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

  it("never returns a label that overlaps with a tier label", () => {
    // The bug: Starter (tier 5) and Depth (former value-band) both
    // displayed as "Starter"/"Depth" on the same row, leading to
    // "STARTER section header above DEPTH-labeled rows".  The new
    // labels are short symbols that cannot collide.
    const tierLabels = new Set([
      "Elite", "Blue-Chip", "Premium Starter", "Solid Starter",
      "Starter", "Flex / Depth", "Bench Depth", "Deep Stash",
      "Roster Fringe", "Waiver Wire",
    ]);
    for (const v of [9000, 7000, 5000, 3000, 1000]) {
      expect(tierLabels.has(valueBand(v).label)).toBe(false);
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
