/**
 * Tests for frontend/lib/thresholds.js — shared threshold constants.
 * Verifies values match backend and internal consistency.
 */
import { describe, expect, it } from "vitest";
import * as thresholds from "@/lib/thresholds";
import {
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
} from "@/lib/thresholds";

describe("threshold constants exist and are sane", () => {
  it("does not re-export the retired confidence spread mirrors", () => {
    // CONFIDENCE_SPREAD_HIGH (30) / CONFIDENCE_SPREAD_MEDIUM (80) were
    // described here as mirroring the backend "exactly". They mirrored
    // a rule `_confidence_bucket` retired in favour of the percentile
    // spread, and their one consumer re-applied it on top of the
    // backend's own verdict — suppressing "Consensus asset" on 54 of
    // 111 rows. Same posture as OVERALL_RANK_LIMIT below: the constant
    // is gone so it cannot drift back.
    expect(thresholds).not.toHaveProperty("CONFIDENCE_SPREAD_HIGH");
    expect(thresholds).not.toHaveProperty("CONFIDENCE_SPREAD_MEDIUM");
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

  it("does not re-export OVERALL_RANK_LIMIT (backend-authoritative)", () => {
    // The overall cap lives exclusively on the backend so the
    // frontend cannot drift out of lockstep.  Any re-introduction
    // of this constant would be a parallel-ranking-engine regression.
    expect(thresholds).not.toHaveProperty("OVERALL_RANK_LIMIT");
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
  // The two tests that lived here — "CONFIDENCE_SPREAD_HIGH matches
  // actionLabel consensus threshold" and "spread above
  // CONFIDENCE_SPREAD_HIGH loses consensus label" — pinned a frontend
  // recompute of a retired backend rule, so they were green precisely
  // while the bug was present. Replaced by
  // __tests__/consensus-label-reads-backend-bucket.test.js, which
  // asserts the label follows `row.confidenceBucket` instead.

  // Note: "Market premium" is no longer an action label — the
  // Market/Edge column in the main table shows the retail-vs-consensus
  // gap directly ("KTC higher by N" / "Experts higher by N"), so
  // rendering it in the Signal column too was redundant.  The old
  // threshold MARKET_PREMIUM_SPREAD is kept for use in the Edge
  // Summary rail / /edge page but no longer gates actionLabel().

  it("MARKET_PREMIUM_SPREAD is still a valid threshold constant", () => {
    expect(Number.isFinite(MARKET_PREMIUM_SPREAD)).toBe(true);
    expect(MARKET_PREMIUM_SPREAD).toBeGreaterThan(0);
  });

  it("actionLabel never returns a Market premium label anymore", async () => {
    const { actionLabel } = await import("@/lib/edge-helpers");
    const row = {
      sourceRankSpread: MARKET_PREMIUM_SPREAD + 20,
      marketGapDirection: "retail_premium",
      quarantined: false,
    };
    const result = actionLabel(row);
    if (result) expect(result.label).not.toContain("Market premium");
  });
});
