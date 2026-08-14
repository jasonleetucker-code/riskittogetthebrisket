/**
 * "Consensus asset" follows the backend's bucket, not a client recompute.
 *
 * WHY THIS EXISTS
 * ===============
 * `actionLabel` asked the agreement question twice. First it read
 * `row.confidenceBucket` — the backend's answer. Then it re-applied
 * `sourceRankSpread <= CONFIDENCE_SPREAD_HIGH`, a frontend copy of
 * `_CONFIDENCE_SPREAD_HIGH = 30`.
 *
 * That constant mirrored a rule the backend had already RETIRED, and the
 * backend has since retired the replacement too. Confidence is now
 * decided by `src/api/confidence.py` — five axes over provider families
 * (independence, coverage, freshness, applicability, agreement),
 * combined by bottleneck, with agreement measured in VALUE space (B11).
 * No spread of any kind decides it, so a client-side ordinal cap is now
 * two generations behind the rule it claims to mirror.
 *
 * The property this file pins is what survives every one of those
 * changes: the client renders the backend's verdict and computes none of
 * its own. The specific numbers below are from the 2026-07-30 measurement
 * that motivated the fix; they are history, not the current board.
 *
 * Measured on the pinned 2026-07-30 contract:
 *
 *   rows the backend calls high-confidence, multi-source,
 *   with no disagreement stamp .................................. 111
 *   ...on which the client's extra check suppressed the label .... 54
 *
 *   sourceRankSpread across those 111 rows:
 *     min 0 · p25 14 · median 28 · p75 113 · max 486
 *
 * Nearly half the rows the board is most confident about never showed
 * the one positive signal the Signal column has. And the max says why
 * an ordinal cap of 30 cannot be the right instrument: 486 is a real
 * spread on a row the backend is confident about.
 *
 * WHAT COULD DISAGREE WITH IT, BEFORE
 * ===================================
 * Nothing — worse than nothing. Two tests in `thresholds.test.js`
 * ("CONFIDENCE_SPREAD_HIGH matches actionLabel consensus threshold"
 * and "spread above CONFIDENCE_SPREAD_HIGH loses consensus label")
 * asserted the recompute, so the suite was green *because* the bug was
 * present. Both are removed; this file replaces them.
 *
 * This is the codebase's "no frontend ranking engine, period" rule
 * applied to a label rather than a value: `buildRows` trusts backend
 * stamps verbatim, and so must this.
 */
import { describe, it, expect } from "vitest";
import { actionLabel } from "@/lib/edge-helpers";
import * as thresholds from "@/lib/thresholds";

const row = (o = {}) => ({
  name: "Test Player",
  pos: "WR",
  rank: 10,
  confidenceBucket: "high",
  sourceCount: 2,
  sourceRankSpread: 15,
  hasSourceDisagreement: false,
  quarantined: false,
  anomalyFlags: [],
  marketGapDirection: "none",
  ...o,
});

describe("Consensus asset follows the backend bucket", () => {
  it("labels a high-confidence row whose ordinal spread is wide", () => {
    // 486 is the observed maximum on the live contract, not a round
    // number. Under the old recompute this row — which the backend is
    // confident about — showed nothing.
    expect(actionLabel(row({ sourceRankSpread: 486 }))?.label).toBe("Consensus asset");
  });

  it("labels a high-confidence row with no spread field at all", () => {
    expect(actionLabel(row({ sourceRankSpread: null }))?.label).toBe("Consensus asset");
  });

  it("withholds the label when the backend bucket is not high", () => {
    // The asymmetry is the point: this is not a blanket "always label".
    // A tight ordinal spread must NOT buy the label back if the backend
    // — which sees the percentile signal — declined it.
    for (const bucket of ["medium", "low", "none"]) {
      expect(
        actionLabel(row({ confidenceBucket: bucket, sourceRankSpread: 0 })),
        `bucket=${bucket} with spread 0 should still not be labelled consensus`,
      ).toBeNull();
    }
  });

  it("withholds the label on a single-source row", () => {
    expect(actionLabel(row({ sourceCount: 1 }))).toBeNull();
  });

  it("withholds the label when the backend stamps disagreement", () => {
    // Keeps "Consensus asset" and "Caution: wide disagreement" from
    // rendering together. Also a backend stamp, also off the percentile
    // signal — this check is kept for that reason, not as a second
    // recompute.
    expect(actionLabel(row({ hasSourceDisagreement: true }))).toBeNull();
  });

  it("withholds the label on a quarantined row", () => {
    expect(actionLabel(row({ quarantined: true }))).toBeNull();
  });

  it("the retired mirrors are gone, so they cannot drift back", () => {
    expect(thresholds).not.toHaveProperty("CONFIDENCE_SPREAD_HIGH");
    expect(thresholds).not.toHaveProperty("CONFIDENCE_SPREAD_MEDIUM");
  });

  it("the label is decided by the bucket alone across the observed spread range", () => {
    // Non-vacuity, phrased as the property rather than a case list: if
    // any ordinal spread the live board actually produces changed the
    // outcome, an ordinal rule would still be in force somewhere.
    const observed = [0, 14, 28, 30, 31, 113, 200, 486];
    const labels = observed.map((s) => actionLabel(row({ sourceRankSpread: s }))?.label);
    expect(new Set(labels)).toEqual(new Set(["Consensus asset"]));
  });
});
