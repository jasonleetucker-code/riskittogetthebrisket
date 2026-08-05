import { describe, expect, it } from "vitest";
import {
  actionLabel,
  cautionLabels,
  LENSES,
  getLens,
  applyLens,
  SCREENS,
  isScreen,
  getLens,
  topRetailPremium,
  topConsensusPremium,
  topFlaggedCautions,
  topConsensusAssets,
  computeEdgeSummary,
  isTopRankedForEdgePremium,
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

  // "Market premium: X" was previously an action label in the Signal
  // column.  It's been removed because the Market/Edge column already
  // renders the same information as "KTC higher by N" / "Experts
  // higher by N", and rendering both was noisy duplication.  The
  // Signal column is now strictly: Consensus asset + caution labels.

  // These two assert the ABSENCE of a market-premium label, which is
  // what their names say.  They previously asserted `toBeNull()` and
  // passed for the wrong reason: `makeRow` defaults to a
  // high-confidence multi-source row, so the only thing suppressing a
  // label was the retired `sourceRankSpread <= 30` recompute.  Once
  // that came out they returned "Consensus asset" — correctly, since
  // the backend calls these rows high-confidence.  Narrowed to the
  // claim they were written to make.
  it("returns no market-premium label for a retail-premium row (Market column handles it)", () => {
    const label = actionLabel(makeRow({
      marketGapDirection: "retail_premium",
      sourceRankSpread: 45,
    }));
    expect(label?.label ?? "").not.toMatch(/premium/i);
  });

  it("returns no market-premium label for a consensus-premium row (Market column handles it)", () => {
    const label = actionLabel(makeRow({
      marketGapDirection: "consensus_premium",
      sourceRankSpread: 50,
    }));
    expect(label?.label ?? "").not.toMatch(/premium/i);
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

  it("suppresses consensus asset when hasSourceDisagreement is true", () => {
    // Fixes the old contradiction where a row could show both
    // "Consensus asset" and "Caution: wide disagreement" at the same
    // time because the two checks used different spread metrics.
    const label = actionLabel(makeRow({
      confidenceBucket: "high",
      sourceCount: 2,
      sourceRankSpread: 20,
      hasSourceDisagreement: true,
    }));
    expect(label).toBeNull();
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

  it("still returns consensus for a wide ordinal spread the backend calls high-confidence", () => {
    // This test previously asserted the OPPOSITE, pinning a frontend
    // copy of `_CONFIDENCE_SPREAD_HIGH` (30) that the backend retired:
    // `_confidence_bucket` decides off the PERCENTILE spread and only
    // falls back to the absolute ordinal for callers with nothing else.
    // Re-imposing the ordinal cap suppressed "Consensus asset" on 54 of
    // the 111 rows the backend calls high-confidence on the pinned
    // 2026-07-30 contract, with spreads up to 486.
    //
    // 486 is that observed maximum, not a round number — a row the
    // backend is confident about despite a very wide raw ordinal
    // spread is exactly the case the percentile signal exists for.
    const label = actionLabel(makeRow({
      confidenceBucket: "high",
      sourceCount: 2,
      sourceRankSpread: 486,
      marketGapDirection: "none",
    }));
    expect(label?.label).toBe("Consensus asset");
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

// ── SCREENS ──────────────────────────────────────────────────────────
// The five saved filters that used to be the /finder page. They are
// carried over VERBATIM: their thresholds differ from the lenses above
// (WR Gaps cuts at spread > 15 and rank <= 250, Disagreements at a
// different number), so mapping them onto existing lenses would have
// silently changed what each preset returned. These tests pin the
// thresholds, not just the presence of the keys.

describe("SCREENS", () => {
  it("exposes the five workflows the standalone page had", () => {
    expect(SCREENS.map((s) => s.key)).toEqual([
      "wr-gaps",
      "stable-idp",
      "single-risk",
      "rookie-spread",
    ]);
  });

  it("isScreen distinguishes screens from lenses", () => {
    expect(isScreen("wr-gaps")).toBe(true);
    expect(isScreen("disagreements")).toBe(false);
    expect(isScreen("nonsense")).toBe(false);
  });

  it("getLens resolves screens as well as lenses", () => {
    expect(getLens("stable-idp").key).toBe("stable-idp");
    expect(getLens("consensus").key).toBe("consensus");
    // Unknown keys still fall back to the default board.
    expect(getLens("nope").key).toBe("consensus");
  });

  it("WR Gaps keeps its own thresholds: WR, spread > 15, rank <= 250", () => {
    const rows = [
      makeRow({ name: "wr-wide", pos: "WR", sourceRankSpread: 40, rank: 100 }),
      makeRow({ name: "wr-tight", pos: "WR", sourceRankSpread: 10, rank: 100 }),
      makeRow({ name: "wr-deep", pos: "WR", sourceRankSpread: 40, rank: 400 }),
      makeRow({ name: "rb-wide", pos: "RB", sourceRankSpread: 40, rank: 100 }),
    ];
    expect(applyLens(rows, "wr-gaps").map((r) => r.name)).toEqual(["wr-wide"]);
  });

  it("1-Source Risk is single-source only, not the broader Fragile lens", () => {
    const rows = [
      makeRow({ name: "single", isSingleSource: true, rank: 50 }),
      makeRow({ name: "single-deep", isSingleSource: true, rank: 900 }),
      // Fragile would include this; 1-Source Risk must not.
      makeRow({ name: "lowconf", confidenceBucket: "low", rank: 50 }),
    ];
    expect(applyLens(rows, "single-risk").map((r) => r.name)).toEqual(["single"]);
  });

  it("Rookie Spread cuts at spread > 10 and rank <= 400", () => {
    const rows = [
      makeRow({ name: "hit", rookie: true, sourceRankSpread: 20, rank: 200 }),
      makeRow({ name: "tight", rookie: true, sourceRankSpread: 5, rank: 200 }),
      makeRow({ name: "veteran", rookie: false, sourceRankSpread: 20, rank: 200 }),
    ];
    expect(applyLens(rows, "rookie-spread").map((r) => r.name)).toEqual(["hit"]);
  });

  it("Stable IDP wants high confidence and 2+ sources", () => {
    const rows = [
      makeRow({
        name: "solid",
        assetClass: "idp",
        confidenceBucket: "high",
        sourceCount: 3,
      }),
      makeRow({
        name: "thin",
        assetClass: "idp",
        confidenceBucket: "high",
        sourceCount: 1,
      }),
      makeRow({
        name: "offense",
        assetClass: "offense",
        confidenceBucket: "high",
        sourceCount: 3,
      }),
    ];
    expect(applyLens(rows, "stable-idp").map((r) => r.name)).toEqual(["solid"]);
  });
});

// ── Edge summary functions ───────────────────────────────────────────

describe("topRetailPremium", () => {
  // REVERSAL RECORDED IN PLACE (audit S-3/C09, batch C4). These rows
  // used to be gated, sorted AND labelled on `sourceRankSpread` — how
  // much the SOURCES disagree with each other — while the panel
  // displays the retail-vs-consensus direction. The rendered
  // "Sell +80 ranks" showed the user a disagreement width and called it
  // the gap. All three now come from `marketGapMagnitude`, which is the
  // magnitude of the direction being filtered on.
  it("returns rows sorted by market-gap magnitude where retail ranks higher", () => {
    const rows = [
      makeRow({ name: "A", marketGapDirection: "retail_premium", marketGapValueRatio: 0.20, rank: 10 }),
      makeRow({ name: "B", marketGapDirection: "retail_premium", marketGapValueRatio: 0.30, rank: 20 }),
      makeRow({ name: "C", marketGapDirection: "consensus_premium", marketGapValueRatio: 0.32, rank: 5 }),
      makeRow({ name: "D", marketGapDirection: "retail_premium", marketGapValueRatio: 0.02, rank: 30 }), // below threshold
    ];
    const result = topRetailPremium(rows, 3);
    expect(result).toHaveLength(2); // A and B (D is below threshold)
    expect(result[0].name).toBe("B"); // 0.30 > 0.20
    expect(result[0].detail).toBe("Sell — retail by 30% higher");
  });

  it("ignores source disagreement entirely", () => {
    // The guard on S-3: a huge spread with no market gap is not a sell
    // signal, and a clean gap on a player every source agrees about is.
    const rows = [
      makeRow({ name: "NoisyButAligned", marketGapDirection: "retail_premium", marketGapValueRatio: 0.02, sourceRankSpread: 300 }),
      makeRow({ name: "QuietButMispriced", marketGapDirection: "retail_premium", marketGapValueRatio: 0.30, sourceRankSpread: 1 }),
    ];
    const result = topRetailPremium(rows, 5);
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("QuietButMispriced");
  });

  it("excludes quarantined rows", () => {
    const rows = [
      makeRow({ name: "Q", marketGapDirection: "retail_premium", marketGapValueRatio: 0.20, quarantined: true }),
    ];
    expect(topRetailPremium(rows)).toHaveLength(0);
  });
});

describe("topConsensusPremium", () => {
  it("returns rows where consensus ranks higher than KTC", () => {
    const rows = [
      makeRow({ name: "X", marketGapDirection: "consensus_premium", marketGapValueRatio: 0.25, rank: 15 }),
    ];
    const result = topConsensusPremium(rows);
    expect(result).toHaveLength(1);
    expect(result[0].detail).toBe("Buy — experts by 25% higher");
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
    expect(summary).toHaveProperty("retailPremium");
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

// ── isTopRankedForEdgePremium ────────────────────────────────────────
//
// The Edge page's Sell Signals / Buy Signals sections are pinned to
// the top 150 by OUR consensus rank only — the previous OR-on-KTC
// path was dropped (users reported it surfaced deep players KTC
// priced high but our blend ranked outside the top 200, defeating
// the "only trade-relevant" intent).  This block pins the new,
// stricter gate.

describe("isTopRankedForEdgePremium", () => {
  it("returns false for null / undefined / missing row", () => {
    expect(isTopRankedForEdgePremium(null)).toBe(false);
    expect(isTopRankedForEdgePremium(undefined)).toBe(false);
  });

  it("admits rows whose consensus rank is inside the top 250", () => {
    // Cap bumped 150 → 250 (2026-04-29) so mid-board WR / RB
    // disagreements (Elijah Moore class) surface in the Edge rail.
    expect(isTopRankedForEdgePremium({ rank: 1 })).toBe(true);
    expect(isTopRankedForEdgePremium({ rank: 50 })).toBe(true);
    expect(isTopRankedForEdgePremium({ rank: 150 })).toBe(true);
    expect(isTopRankedForEdgePremium({ rank: 249 })).toBe(true);
    expect(isTopRankedForEdgePremium({ rank: 250 })).toBe(true);
  });

  it("rejects rows past the top 250", () => {
    expect(isTopRankedForEdgePremium({ rank: 251 })).toBe(false);
    expect(isTopRankedForEdgePremium({ rank: 400 })).toBe(false);
    expect(isTopRankedForEdgePremium({ rank: 700 })).toBe(false);
  });

  it("ignores KTC rank — consensus rank is the sole gate", () => {
    // Previously admitted on ``ktc <= 200`` even when consensus was
    // past 200; that escape hatch is gone.  A player KTC prices top-10
    // but OUR blend ranks #500 now DOES NOT surface in Sell/Buy.
    expect(
      isTopRankedForEdgePremium({ rank: 500, sourceRanks: { ktc: 50 } }),
    ).toBe(false);
    expect(
      isTopRankedForEdgePremium({ rank: 400, sourceRanks: { ktc: 10 } }),
    ).toBe(false);
    // And a player inside top-150 consensus is admitted regardless
    // of KTC rank.
    expect(
      isTopRankedForEdgePremium({ rank: 100, sourceRanks: { ktc: 800 } }),
    ).toBe(true);
  });

  it("returns false when consensus rank is missing / invalid", () => {
    expect(isTopRankedForEdgePremium({})).toBe(false);
    expect(isTopRankedForEdgePremium({ rank: null })).toBe(false);
    expect(isTopRankedForEdgePremium({ rank: 0 })).toBe(false);
    expect(isTopRankedForEdgePremium({ rank: -5 })).toBe(false);
    expect(
      isTopRankedForEdgePremium({ rank: "garbage", sourceRanks: { ktc: 10 } }),
    ).toBe(false);
  });
});
