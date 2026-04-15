/**
 * Tests for the per-user source override plumbing in
 * `buildRows` / `computeUnifiedRanks`.
 *
 * The override map lets the settings page toggle sources off or push
 * a non-1.0 weight onto a source.  When any override diverges from
 * the canonical `RANKING_SOURCES` defaults, `buildRows` flips into
 * "bypass" mode: the frontend-computed ranks replace any backend
 * stamps so the user's configuration actually affects the displayed
 * board.  These tests pin the contract:
 *
 *   1. An empty override map is non-customized and backend stamps win.
 *   2. `include: false` excludes the source from the blend entirely.
 *   3. A non-default `weight` is treated as customized and the
 *      frontend blend overrides the backend rank for that row.
 *   4. The customized detector ignores overrides that match defaults.
 */
import { describe, expect, it } from "vitest";
import { buildRows, siteOverridesAreCustomized } from "@/lib/dynasty-data";

// A minimal fixture with two offense players that share KTC + IDPTC
// coverage and one expert source so we can toggle the expert off and
// watch the blend shift.  Backend stamps (canonicalConsensusRank +
// rankDerivedValue) exist so the default path should preserve them;
// the Hill-curve values that would be computed by the frontend blend
// on these same canonicalSiteValues are DIFFERENT from the backend
// stamps, letting the tests distinguish "backend path" from "bypass".
function fixture({ backendRank = { A: 1, B: 2 }, backendValue = { A: 9800, B: 9400 } } = {}) {
  return {
    playersArray: [
      {
        canonicalName: "Player A",
        displayName: "Player A",
        position: "QB",
        team: "AAA",
        age: 25,
        rookie: false,
        assetClass: "offense",
        values: { displayValue: backendValue.A, finalAdjusted: backendValue.A, rawComposite: backendValue.A },
        canonicalSiteValues: { ktc: 9999, idpTradeCalc: 9999, dlfSf: 9999 },
        canonicalConsensusRank: backendRank.A,
        rankDerivedValue: backendValue.A,
        canonicalTierId: 1,
        sourceRanks: { ktc: backendRank.A, idpTradeCalc: backendRank.A, dlfSf: backendRank.A },
        sourceOriginalRanks: { dlfSf: backendRank.A },
        confidenceBucket: "high",
        anomalyFlags: [],
      },
      {
        canonicalName: "Player B",
        displayName: "Player B",
        position: "RB",
        team: "BBB",
        age: 24,
        rookie: false,
        assetClass: "offense",
        values: { displayValue: backendValue.B, finalAdjusted: backendValue.B, rawComposite: backendValue.B },
        // Player B is missing the expert source.  With equal-weight
        // default, Player B should rank below Player A.  If we
        // disable the expert source via override, Player A loses one
        // signal and the gap shrinks.
        canonicalSiteValues: { ktc: 9500, idpTradeCalc: 9500 },
        canonicalConsensusRank: backendRank.B,
        rankDerivedValue: backendValue.B,
        canonicalTierId: 1,
        sourceRanks: { ktc: backendRank.B, idpTradeCalc: backendRank.B },
        sourceOriginalRanks: {},
        confidenceBucket: "high",
        anomalyFlags: [],
      },
    ],
  };
}

describe("siteOverridesAreCustomized", () => {
  it("returns false for null / undefined / empty", () => {
    expect(siteOverridesAreCustomized(null)).toBe(false);
    expect(siteOverridesAreCustomized(undefined)).toBe(false);
    expect(siteOverridesAreCustomized({})).toBe(false);
  });

  it("returns false when every override matches the default weight", () => {
    // weight: 1.0 matches the canonical registry → not customized
    expect(siteOverridesAreCustomized({ ktc: { weight: 1.0 } })).toBe(false);
    expect(siteOverridesAreCustomized({ dlfSf: { weight: 1.0 }, ktc: { weight: 1.0 } })).toBe(false);
  });

  it("returns true when a source is excluded", () => {
    expect(siteOverridesAreCustomized({ ktc: { include: false } })).toBe(true);
    expect(siteOverridesAreCustomized({ dlfSf: { include: false, weight: 1.0 } })).toBe(true);
  });

  it("returns true when a source has a non-default weight", () => {
    expect(siteOverridesAreCustomized({ ktc: { weight: 2.0 } })).toBe(true);
    expect(siteOverridesAreCustomized({ dlfSf: { weight: 0 } })).toBe(true);
    expect(siteOverridesAreCustomized({ ktc: { weight: 0.5 } })).toBe(true);
  });

  it("ignores fields that are not include or weight", () => {
    expect(siteOverridesAreCustomized({ ktc: { label: "foo" } })).toBe(false);
  });
});

describe("buildRows — default (no overrides) preserves backend stamps", () => {
  it("keeps backend canonicalConsensusRank and rankDerivedValue", () => {
    const rows = buildRows(fixture());
    const a = rows.find((r) => r.name === "Player A");
    const b = rows.find((r) => r.name === "Player B");
    expect(a).toBeDefined();
    expect(b).toBeDefined();
    // Backend stamps win when no overrides are set.
    expect(a.canonicalConsensusRank).toBe(1);
    expect(b.canonicalConsensusRank).toBe(2);
    expect(a.rankDerivedValue).toBe(9800);
    expect(b.rankDerivedValue).toBe(9400);
  });
});

describe("buildRows — customized overrides bypass backend stamps", () => {
  it("disabling a source recomputes the rank using only remaining sources", () => {
    // Disable KTC — Player A and Player B both lose the KTC signal,
    // but since they have equal IDPTC values (9999 vs 9500), the
    // order is preserved by raw IDPTC values.  The CRITICAL
    // behavior we're locking in is that `canonicalConsensusRank` is
    // now computed by the frontend (not the backend stamps) and
    // ``rankDerivedValue`` reflects the blend without KTC.
    const rows = buildRows(fixture(), {
      siteOverrides: { ktc: { include: false } },
    });
    const a = rows.find((r) => r.name === "Player A");
    const b = rows.find((r) => r.name === "Player B");
    // The frontend blend should NOT equal the backend-stamped value
    // (9800 / 9400).  The Hill curve + equal-weight blend over the
    // remaining sources gives different numbers.
    expect(a.rankDerivedValue).not.toBe(9800);
    expect(b.rankDerivedValue).not.toBe(9400);
    // sourceRanks should only contain the two remaining sources, not ktc
    expect(Object.keys(a.sourceRanks || {})).not.toContain("ktc");
    expect(Object.keys(b.sourceRanks || {})).not.toContain("ktc");
  });

  it("weight override recomputes the blend and shifts values", () => {
    // Zero weight on every source except KTC — the blend for both
    // players collapses to their KTC signal (rank 1 → Hill 9999).
    // Player A and Player B both have KTC rank 1 and 2 respectively,
    // so their frontend-computed values reflect the Hill curve
    // directly rather than the backend-stamped 9800/9400.
    const rows = buildRows(fixture(), {
      siteOverrides: {
        idpTradeCalc: { weight: 0 },
        dlfSf: { weight: 0 },
      },
    });
    const a = rows.find((r) => r.name === "Player A");
    const b = rows.find((r) => r.name === "Player B");
    // Frontend recompute should produce a rank ordering different
    // from the stamped one (even if the ORDERING happens to match,
    // the derived values must reflect the weight shift).
    expect(a.rankDerivedValue).not.toBe(9800);
    expect(b.rankDerivedValue).not.toBe(9400);
    // And frontend-assigned ranks are 1 and 2 (not the backend stamps).
    // Sort stability: Player A (KTC rank 1) beats Player B (KTC rank 2).
    expect(a.canonicalConsensusRank).toBe(1);
    expect(b.canonicalConsensusRank).toBe(2);
  });

  it("override matching the default is a no-op (keeps backend stamps)", () => {
    const rows = buildRows(fixture(), {
      siteOverrides: { ktc: { weight: 1.0 } }, // default, not customized
    });
    const a = rows.find((r) => r.name === "Player A");
    expect(a.rankDerivedValue).toBe(9800);
    expect(a.canonicalConsensusRank).toBe(1);
  });
});
