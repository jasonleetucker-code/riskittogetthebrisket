import { describe, expect, it } from "vitest";
import {
  actionLabel,
  cautionLabels,
  LENSES,
  getLens,
  applyLens,
  topKtcPremium,
  topConsensusPremium,
  topFlaggedCautions,
  topConsensusAssets,
  computeEdgeSummary,
} from "../lib/edge-helpers.js";

// ── Helpers ──────────────────────────────────────────────────────────

function makeRow(overrides = {}) {
  return {
    name: "Test Player",
    pos: "QB",
    rank: 10,
    confidenceBucket: "high",
    sourceCount: 2,
    sourceRankSpread: 15,
    isSingleSource: false,
    hasSourceDisagreement: false,
    marketGapDirection: "none",
    anomalyFlags: [],
    quarantined: false,
    ...overrides,
  };
}

// ── actionLabel ──────────────────────────────────────────────────────

describe("actionLabel", () => {
  it("returns null for quarantined rows", () => {
    expect(actionLabel(makeRow({ quarantined: true }))).toBeNull();
  });

  it("returns market premium when KTC ranks higher with large spread", () => {
    const label = actionLabel(makeRow({
      marketGapDirection: "ktc_premium",
      sourceRankSpread: 45,
    }));
    expect(label).not.toBeNull();
    expect(label.label).toBe("Market premium: KTC");
    expect(label.css).toBe("action-premium");
  });

  it("returns market premium for consensus direction", () => {
    const label = actionLabel(makeRow({
      marketGapDirection: "consensus_premium",
      sourceRankSpread: 50,
    }));
    expect(label.label).toBe("Market premium: Consensus");
  });

  it("returns consensus asset for high-confidence tight agreement", () => {
    const label = actionLabel(makeRow({
      confidenceBucket: "high",
      sourceCount: 2,
      sourceRankSpread: 20,
      marketGapDirection: "none",
    }));
    expect(label).not.toBeNull();
    expect(label.label).toBe("Consensus asset");
    expect(label.css).toBe("action-consensus");
  });

  it("prioritizes market premium over consensus", () => {
    const label = actionLabel(makeRow({
      confidenceBucket: "high",
      sourceCount: 2,
      sourceRankSpread: 40,
      marketGapDirection: "ktc_premium",
    }));
    expect(label.label).toBe("Market premium: KTC");
  });

  it("returns null for ordinary rows", () => {
    const label = actionLabel(makeRow({
      confidenceBucket: "low",
      sourceCount: 1,
      sourceRankSpread: null,
      marketGapDirection: "none",
    }));
    expect(label).toBeNull();
  });

  it("does not return consensus for spread > 30", () => {
    const label = actionLabel(makeRow({
      confidenceBucket: "high",
      sourceCount: 2,
      sourceRankSpread: 31,
      marketGapDirection: "none",
    }));
    // spread 31 is above the consensus threshold of 30 but below the
    // market premium threshold (no direction set), so no label
    expect(label).toBeNull();
  });
});

// ── cautionLabels ────────────────────────────────────────────────────

describe("cautionLabels", () => {
  it("returns empty array for clean row", () => {
    expect(cautionLabels(makeRow())).toEqual([]);
  });

  it("flags single source", () => {
    const labels = cautionLabels(makeRow({ isSingleSource: true }));
    expect(labels).toHaveLength(1);
    expect(labels[0].label).toBe("Caution: single source");
  });

  it("flags anomaly", () => {
    const labels = cautionLabels(makeRow({ anomalyFlags: ["offense_as_idp"] }));
    expect(labels).toHaveLength(1);
    expect(labels[0].label).toBe("Caution: flagged");
  });

  it("does not flag anomaly when quarantined", () => {
    const labels = cautionLabels(makeRow({
      anomalyFlags: ["offense_as_idp"],
      quarantined: true,
    }));
    expect(labels).toHaveLength(0);
  });

  it("flags wide disagreement", () => {
    const labels = cautionLabels(makeRow({ hasSourceDisagreement: true }));
    expect(labels).toHaveLength(1);
    expect(labels[0].label).toBe("Caution: wide disagreement");
  });

  it("can stack multiple cautions", () => {
    const labels = cautionLabels(makeRow({
      isSingleSource: true,
      anomalyFlags: ["suspicious"],
      hasSourceDisagreement: true,
    }));
    expect(labels).toHaveLength(3);
  });
});

// ── LENSES ───────────────────────────────────────────────────────────

describe("LENSES", () => {
  it("has 5 lenses defined", () => {
    expect(LENSES).toHaveLength(5);
  });

  it("consensus lens accepts all rows", () => {
    const lens = getLens("consensus");
    expect(lens.filter(makeRow())).toBe(true);
    expect(lens.sort).toBeNull();
  });

  it("disagreements lens filters by spread > 40", () => {
    const lens = getLens("disagreements");
    expect(lens.filter(makeRow({ sourceRankSpread: 50 }))).toBe(true);
    expect(lens.filter(makeRow({ sourceRankSpread: 30 }))).toBe(false);
    expect(lens.filter(makeRow({ sourceRankSpread: null }))).toBe(false);
  });

  it("inefficiencies lens requires rank <= 200 and spread > 30", () => {
    const lens = getLens("inefficiencies");
    expect(lens.filter(makeRow({ rank: 50, sourceRankSpread: 40 }))).toBe(true);
    expect(lens.filter(makeRow({ rank: 250, sourceRankSpread: 40 }))).toBe(false);
    expect(lens.filter(makeRow({ rank: 50, sourceRankSpread: 20 }))).toBe(false);
  });

  it("safest lens requires high confidence + multi-source", () => {
    const lens = getLens("safest");
    expect(lens.filter(makeRow({ confidenceBucket: "high", sourceCount: 2 }))).toBe(true);
    expect(lens.filter(makeRow({ confidenceBucket: "low", sourceCount: 2 }))).toBe(false);
    expect(lens.filter(makeRow({ confidenceBucket: "high", sourceCount: 1 }))).toBe(false);
  });

  it("fragile lens catches single-source, low-confidence, or flagged", () => {
    const lens = getLens("fragile");
    expect(lens.filter(makeRow({ isSingleSource: true }))).toBe(true);
    expect(lens.filter(makeRow({ confidenceBucket: "low" }))).toBe(true);
    expect(lens.filter(makeRow({ anomalyFlags: ["x"] }))).toBe(true);
    expect(lens.filter(makeRow())).toBe(false);
  });
});

// ── applyLens ────────────────────────────────────────────────────────

describe("applyLens", () => {
  const rows = [
    makeRow({ name: "A", sourceRankSpread: 60, rank: 10 }),
    makeRow({ name: "B", sourceRankSpread: 20, rank: 20 }),
    makeRow({ name: "C", sourceRankSpread: 80, rank: 30 }),
  ];

  it("consensus returns all rows", () => {
    const result = applyLens(rows, "consensus");
    expect(result).toHaveLength(3);
  });

  it("disagreements filters and sorts by spread desc", () => {
    const result = applyLens(rows, "disagreements");
    expect(result).toHaveLength(2); // A (60) and C (80)
    expect(result[0].name).toBe("C"); // 80 > 60
    expect(result[1].name).toBe("A");
  });
});

// ── Edge summary functions ───────────────────────────────────────────

describe("topKtcPremium", () => {
  it("returns rows sorted by spread where KTC ranks higher", () => {
    const rows = [
      makeRow({ name: "A", marketGapDirection: "ktc_premium", sourceRankSpread: 50, rank: 10 }),
      makeRow({ name: "B", marketGapDirection: "ktc_premium", sourceRankSpread: 80, rank: 20 }),
      makeRow({ name: "C", marketGapDirection: "consensus_premium", sourceRankSpread: 90, rank: 5 }),
      makeRow({ name: "D", marketGapDirection: "ktc_premium", sourceRankSpread: 10, rank: 30 }), // below 20 threshold
    ];
    const result = topKtcPremium(rows, 3);
    expect(result).toHaveLength(2); // A and B (D is below threshold)
    expect(result[0].name).toBe("B"); // 80 > 50
    expect(result[0].detail).toBe("KTC +80 ranks");
  });

  it("excludes quarantined rows", () => {
    const rows = [
      makeRow({ name: "Q", marketGapDirection: "ktc_premium", sourceRankSpread: 60, quarantined: true }),
    ];
    expect(topKtcPremium(rows)).toHaveLength(0);
  });
});

describe("topConsensusPremium", () => {
  it("returns rows where consensus ranks higher than KTC", () => {
    const rows = [
      makeRow({ name: "X", marketGapDirection: "consensus_premium", sourceRankSpread: 40, rank: 15 }),
    ];
    const result = topConsensusPremium(rows);
    expect(result).toHaveLength(1);
    expect(result[0].detail).toBe("Consensus +40 ranks");
  });
});

describe("topFlaggedCautions", () => {
  it("returns flagged players within top 300 by rank", () => {
    const rows = [
      makeRow({ name: "F1", anomalyFlags: ["offense_as_idp"], rank: 50 }),
      makeRow({ name: "F2", anomalyFlags: ["suspicious"], rank: 400 }), // outside top 300
      makeRow({ name: "F3", anomalyFlags: ["missing_position"], rank: 10 }),
    ];
    const result = topFlaggedCautions(rows);
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe("F3"); // rank 10 < 50
  });
});

describe("topConsensusAssets", () => {
  it("returns high-confidence multi-source non-quarantined by rank", () => {
    const rows = [
      makeRow({ name: "C1", confidenceBucket: "high", sourceCount: 2, rank: 5 }),
      makeRow({ name: "C2", confidenceBucket: "high", sourceCount: 2, rank: 1 }),
      makeRow({ name: "C3", confidenceBucket: "low", sourceCount: 2, rank: 3 }),
      makeRow({ name: "C4", confidenceBucket: "high", sourceCount: 1, rank: 2 }),
    ];
    const result = topConsensusAssets(rows);
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe("C2"); // rank 1
    expect(result[1].name).toBe("C1"); // rank 5
  });
});

describe("computeEdgeSummary", () => {
  it("returns all four sections", () => {
    const rows = [
      makeRow({ name: "P1", pos: "QB", rank: 1, confidenceBucket: "high", sourceCount: 2 }),
    ];
    const summary = computeEdgeSummary(rows);
    expect(summary).toHaveProperty("ktcPremium");
    expect(summary).toHaveProperty("consensusPremium");
    expect(summary).toHaveProperty("flaggedCautions");
    expect(summary).toHaveProperty("consensusAssets");
  });

  it("excludes picks", () => {
    const rows = [
      makeRow({ name: "Pick", pos: "PICK", rank: 1 }),
    ];
    const summary = computeEdgeSummary(rows);
    expect(summary.consensusAssets).toHaveLength(0);
  });
});

// ── getLens ───────────────────────────────────────────────────────────

describe("getLens", () => {
  it("returns consensus for unknown key", () => {
    expect(getLens("nonexistent").key).toBe("consensus");
  });

  it("returns correct lens by key", () => {
    expect(getLens("safest").key).toBe("safest");
    expect(getLens("fragile").key).toBe("fragile");
  });
});
