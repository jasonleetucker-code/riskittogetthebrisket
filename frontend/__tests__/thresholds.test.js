/**
 * Tests for frontend/lib/thresholds.js — shared threshold constants.
 * Verifies values match backend and internal consistency.
 */
import { describe, expect, it } from "vitest";
import {
  CONFIDENCE_SPREAD_HIGH,
  CONFIDENCE_SPREAD_MEDIUM,
  MARKET_PREMIUM_SPREAD,
  PREMIUM_SUMMARY_SPREAD,
  LENS_DISAGREEMENT_SPREAD,
  LENS_INEFFICIENCY_SPREAD,
  LENS_INEFFICIENCY_RANK,
  MARKET_GAP_MIN_DIFF,
  EDGE_CAUTION_RANK_LIMIT,
  RANKINGS_DEFAULT_ROW_LIMIT,
  FINDER_ROW_LIMIT,
  EDGE_SECTION_LIMIT,
  EDGE_PREMIUM_LIMIT,
  OVERALL_RANK_LIMIT,
} from "@/lib/thresholds";

describe("threshold constants exist and are sane", () => {
  it("confidence spread thresholds are ordered correctly", () => {
    expect(CONFIDENCE_SPREAD_HIGH).toBeLessThan(CONFIDENCE_SPREAD_MEDIUM);
    expect(CONFIDENCE_SPREAD_HIGH).toBe(30);
    expect(CONFIDENCE_SPREAD_MEDIUM).toBe(80);
  });

  it("market premium requires higher spread than summary", () => {
    expect(MARKET_PREMIUM_SPREAD).toBeGreaterThanOrEqual(PREMIUM_SUMMARY_SPREAD);
  });

  it("lens disagreement threshold is positive", () => {
    expect(LENS_DISAGREEMENT_SPREAD).toBeGreaterThan(0);
  });

  it("lens inefficiency uses spread and rank together", () => {
    expect(LENS_INEFFICIENCY_SPREAD).toBeGreaterThan(0);
    expect(LENS_INEFFICIENCY_RANK).toBeGreaterThan(0);
  });

  it("display limits are positive", () => {
    expect(RANKINGS_DEFAULT_ROW_LIMIT).toBeGreaterThan(0);
    expect(FINDER_ROW_LIMIT).toBeGreaterThan(0);
    expect(EDGE_SECTION_LIMIT).toBeGreaterThan(0);
    expect(EDGE_PREMIUM_LIMIT).toBeGreaterThan(0);
  });

  it("overall rank limit matches backend", () => {
    expect(OVERALL_RANK_LIMIT).toBe(800);
  });

  it("market gap min diff is positive", () => {
    expect(MARKET_GAP_MIN_DIFF).toBeGreaterThan(0);
  });

  it("edge caution rank limit is positive", () => {
    expect(EDGE_CAUTION_RANK_LIMIT).toBeGreaterThan(0);
  });
});

// ── Cross-file consistency ──────────────────────────────────────────────

describe("threshold consistency with helpers", () => {
  it("CONFIDENCE_SPREAD_HIGH matches actionLabel consensus threshold", async () => {
    const { actionLabel } = await import("@/lib/edge-helpers");
    // A row with high confidence, 2 sources, and spread exactly at CONFIDENCE_SPREAD_HIGH
    // should get "Consensus asset"
    const row = {
      confidenceBucket: "high",
      sourceCount: 2,
      sourceRankSpread: CONFIDENCE_SPREAD_HIGH,
      quarantined: false,
      marketGapDirection: "none",
    };
    const result = actionLabel(row);
    expect(result).not.toBeNull();
    expect(result.label).toBe("Consensus asset");
  });

  it("spread above CONFIDENCE_SPREAD_HIGH loses consensus label", async () => {
    const { actionLabel } = await import("@/lib/edge-helpers");
    const row = {
      confidenceBucket: "high",
      sourceCount: 2,
      sourceRankSpread: CONFIDENCE_SPREAD_HIGH + 1,
      quarantined: false,
      marketGapDirection: "none",
    };
    const result = actionLabel(row);
    // Should NOT get consensus label (spread too wide)
    if (result) expect(result.label).not.toBe("Consensus asset");
  });

  it("MARKET_PREMIUM_SPREAD triggers market premium label", async () => {
    const { actionLabel } = await import("@/lib/edge-helpers");
    const row = {
      sourceRankSpread: MARKET_PREMIUM_SPREAD,
      marketGapDirection: "retail_premium",
      quarantined: false,
    };
    const result = actionLabel(row);
    expect(result).not.toBeNull();
    expect(result.label).toContain("Market premium");
  });

  it("spread below MARKET_PREMIUM_SPREAD does not trigger premium", async () => {
    const { actionLabel } = await import("@/lib/edge-helpers");
    const row = {
      sourceRankSpread: MARKET_PREMIUM_SPREAD - 1,
      marketGapDirection: "retail_premium",
      quarantined: false,
    };
    const result = actionLabel(row);
    // Should not get market premium (spread too small)
    if (result) expect(result.label).not.toContain("Market premium");
  });
});
