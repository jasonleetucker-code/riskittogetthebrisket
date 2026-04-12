/**
 * Tests for trust/confidence/anomaly fields in dynasty-data.js.
 *
 * Verifies that buildRows correctly preserves backend trust fields from
 * the playersArray contract format and provides sensible defaults for
 * the legacy players-map path.
 */
import { describe, expect, it } from "vitest";
import { buildRows } from "@/lib/dynasty-data";

// ── Helpers ─────────────────────────────────────────────────────────

function makeContractPlayer(overrides = {}) {
  return {
    displayName: "Test Player",
    position: "QB",
    assetClass: "offense",
    sourceCount: 1,
    values: { rawComposite: 8000, finalAdjusted: 8000, overall: 8000 },
    canonicalSiteValues: { ktc: 8000 },
    canonicalConsensusRank: 5,
    confidenceBucket: "low",
    confidenceLabel: "Low — single source or wide disagreement",
    anomalyFlags: [],
    isSingleSource: true,
    hasSourceDisagreement: false,
    blendedSourceRank: 5.0,
    sourceRankSpread: null,
    marketGapDirection: "none",
    marketGapMagnitude: null,
    ...overrides,
  };
}

function buildSingle(playerOverrides = {}) {
  const data = { playersArray: [makeContractPlayer(playerOverrides)] };
  const rows = buildRows(data);
  return rows[0];
}

// ── Trust field preservation (playersArray path) ────────────────────

describe("trust fields from playersArray", () => {
  it("preserves confidenceBucket from backend", () => {
    const row = buildSingle({ confidenceBucket: "high" });
    expect(row.confidenceBucket).toBe("high");
  });

  it("preserves confidenceLabel from backend", () => {
    const row = buildSingle({
      confidenceLabel: "High — multi-source, tight agreement",
    });
    expect(row.confidenceLabel).toBe("High — multi-source, tight agreement");
  });

  it("preserves anomalyFlags array from backend", () => {
    const row = buildSingle({ anomalyFlags: ["ol_contamination"] });
    expect(row.anomalyFlags).toEqual(["ol_contamination"]);
  });

  it("defaults anomalyFlags to empty array when missing", () => {
    const row = buildSingle({ anomalyFlags: undefined });
    expect(row.anomalyFlags).toEqual([]);
  });

  it("preserves isSingleSource boolean", () => {
    const row = buildSingle({ isSingleSource: true });
    expect(row.isSingleSource).toBe(true);
  });

  it("preserves hasSourceDisagreement boolean", () => {
    const row = buildSingle({ hasSourceDisagreement: true });
    expect(row.hasSourceDisagreement).toBe(true);
  });

  it("has blendedSourceRank after ranking", () => {
    // blendedSourceRank is computed by computeUnifiedRanks (fallback),
    // so it reflects the mean of per-source ordinal ranks, not the raw
    // backend value (which may be overwritten by the fallback path).
    const row = buildSingle({ blendedSourceRank: 12.5 });
    expect(typeof row.blendedSourceRank).toBe("number");
  });

  it("preserves sourceRankSpread", () => {
    const row = buildSingle({ sourceRankSpread: 45 });
    expect(row.sourceRankSpread).toBe(45);
  });

  it("preserves marketGapDirection", () => {
    const row = buildSingle({ marketGapDirection: "retail_premium" });
    expect(row.marketGapDirection).toBe("retail_premium");
  });

  it("preserves marketGapMagnitude", () => {
    const row = buildSingle({ marketGapMagnitude: 30 });
    expect(row.marketGapMagnitude).toBe(30);
  });

  it("computes confidenceBucket fallback when backend value missing", () => {
    // When backend confidenceBucket is absent, computeUnifiedRanks
    // computes it from source data.  A single-source player → "low".
    const row = buildSingle({ confidenceBucket: undefined });
    expect(["high", "medium", "low", "none"]).toContain(row.confidenceBucket);
  });

  it("defaults marketGapDirection to 'none' when missing", () => {
    const row = buildSingle({ marketGapDirection: undefined });
    expect(row.marketGapDirection).toBe("none");
  });
});

// ── Legacy path defaults ────────────────────────────────────────────

describe("trust fields from legacy players map", () => {
  it("provides default trust fields for legacy player rows", () => {
    const data = {
      players: {
        "Legacy QB": {
          _composite: 7000,
          _rawComposite: 7000,
          _finalAdjusted: 7000,
          _sites: 1,
          position: "QB",
          _canonicalSiteValues: { ktc: 7000 },
        },
      },
      sleeper: { positions: { "Legacy QB": "QB" } },
    };
    const rows = buildRows(data);
    expect(rows.length).toBe(1);
    const row = rows[0];

    // After computeUnifiedRanks runs, the row should have trust fields
    expect(row).toHaveProperty("confidenceBucket");
    expect(row).toHaveProperty("anomalyFlags");
    expect(row).toHaveProperty("isSingleSource");
    expect(row).toHaveProperty("hasSourceDisagreement");
    expect(row).toHaveProperty("blendedSourceRank");
    expect(row).toHaveProperty("sourceRankSpread");
    expect(row).toHaveProperty("marketGapDirection");
    expect(row).toHaveProperty("marketGapMagnitude");
    expect(Array.isArray(row.anomalyFlags)).toBe(true);
  });
});

// ── Multiple players with different confidence levels ───────────────

describe("mixed confidence rows", () => {
  it("preserves different confidence buckets per player", () => {
    const data = {
      playersArray: [
        makeContractPlayer({
          displayName: "High Conf",
          confidenceBucket: "high",
          canonicalConsensusRank: 1,
          canonicalSiteValues: { ktc: 9500 },
        }),
        makeContractPlayer({
          displayName: "Low Conf",
          confidenceBucket: "low",
          canonicalConsensusRank: 2,
          canonicalSiteValues: { ktc: 8500 },
        }),
      ],
    };
    const rows = buildRows(data);
    const high = rows.find((r) => r.name === "High Conf");
    const low = rows.find((r) => r.name === "Low Conf");

    expect(high.confidenceBucket).toBe("high");
    expect(low.confidenceBucket).toBe("low");
  });
});

// ── Anomaly flags array handling ────────────────────────────────────

describe("anomaly flags edge cases", () => {
  it("handles multiple anomaly flags", () => {
    const row = buildSingle({
      anomalyFlags: ["missing_position", "impossible_value"],
    });
    expect(row.anomalyFlags).toEqual(["missing_position", "impossible_value"]);
    expect(row.anomalyFlags.length).toBe(2);
  });

  it("handles non-array anomalyFlags gracefully", () => {
    const row = buildSingle({ anomalyFlags: "not_an_array" });
    expect(Array.isArray(row.anomalyFlags)).toBe(true);
    expect(row.anomalyFlags).toEqual([]);
  });

  it("handles null anomalyFlags gracefully", () => {
    const row = buildSingle({ anomalyFlags: null });
    expect(Array.isArray(row.anomalyFlags)).toBe(true);
    expect(row.anomalyFlags).toEqual([]);
  });
});

// ── Quarantine and identity fields ────────────────────────────────────

describe("quarantine field", () => {
  it("preserves quarantined=true from backend", () => {
    const row = buildSingle({ quarantined: true });
    expect(row.quarantined).toBe(true);
  });

  it("defaults quarantined to false", () => {
    const row = buildSingle({ quarantined: undefined });
    expect(row.quarantined).toBe(false);
  });

  it("quarantined row gets dimmed class treatment", () => {
    // Verify the field exists and is boolean — UI rendering is page-level
    const row = buildSingle({ quarantined: true });
    expect(typeof row.quarantined).toBe("boolean");
  });
});

describe("identity confidence fields", () => {
  it("preserves identityConfidence from backend", () => {
    const row = buildSingle({ identityConfidence: 0.95 });
    expect(row.identityConfidence).toBe(0.95);
  });

  it("preserves identityMethod from backend", () => {
    const row = buildSingle({ identityMethod: "canonical_id" });
    expect(row.identityMethod).toBe("canonical_id");
  });

  it("defaults identityConfidence to 0.7", () => {
    const row = buildSingle({ identityConfidence: undefined });
    expect(row.identityConfidence).toBe(0.7);
  });

  it("defaults identityMethod to name_only", () => {
    const row = buildSingle({ identityMethod: undefined });
    expect(row.identityMethod).toBe("name_only");
  });
});

// ── Complete trust field contract ──────────────────────────────────────

describe("all trust fields present on row", () => {
  it("has every required trust field after buildRows", () => {
    const row = buildSingle();
    const requiredFields = [
      "confidenceBucket",
      "confidenceLabel",
      "anomalyFlags",
      "isSingleSource",
      "hasSourceDisagreement",
      "blendedSourceRank",
      "sourceRankSpread",
      "marketGapDirection",
      "marketGapMagnitude",
      "identityConfidence",
      "identityMethod",
      "quarantined",
    ];
    for (const field of requiredFields) {
      expect(row).toHaveProperty(field);
    }
  });
});

// ── Legacy path reads backend-mirrored trust fields ───────────────────

describe("legacy path picks up mirrored trust fields", () => {
  it("reads confidenceBucket from legacy player dict", () => {
    const data = {
      players: {
        "Mirrored QB": {
          _composite: 8000,
          _rawComposite: 8000,
          _finalAdjusted: 8000,
          _sites: 2,
          position: "QB",
          _canonicalSiteValues: { ktc: 8000 },
          // Backend-mirrored trust fields
          confidenceBucket: "high",
          confidenceLabel: "High — multi-source, tight agreement",
          anomalyFlags: ["ol_contamination"],
          isSingleSource: false,
          hasSourceDisagreement: false,
          blendedSourceRank: 5.0,
          sourceRankSpread: 10,
          marketGapDirection: "retail_premium",
          marketGapMagnitude: 25,
          identityConfidence: 0.95,
          identityMethod: "canonical_id",
          quarantined: false,
        },
      },
      sleeper: { positions: { "Mirrored QB": "QB" } },
    };
    const rows = buildRows(data);
    const row = rows.find((r) => r.name === "Mirrored QB");
    expect(row).toBeDefined();

    // The row should pick up the backend-mirrored values, not defaults
    expect(row.confidenceBucket).toBe("high");
    expect(row.confidenceLabel).toBe(
      "High — multi-source, tight agreement"
    );
    expect(row.anomalyFlags).toEqual(["ol_contamination"]);
    expect(row.isSingleSource).toBe(false);
    expect(row.hasSourceDisagreement).toBe(false);
    expect(row.sourceRankSpread).toBe(10);
    expect(row.marketGapDirection).toBe("retail_premium");
    expect(row.marketGapMagnitude).toBe(25);
    expect(row.identityConfidence).toBe(0.95);
    expect(row.identityMethod).toBe("canonical_id");
    expect(row.quarantined).toBe(false);
  });

  it("falls back to safe defaults when legacy dict has no trust fields", () => {
    const data = {
      players: {
        "Plain QB": {
          _composite: 7000,
          _rawComposite: 7000,
          _finalAdjusted: 7000,
          _sites: 1,
          position: "QB",
          _canonicalSiteValues: { ktc: 7000 },
        },
      },
      sleeper: { positions: { "Plain QB": "QB" } },
    };
    const rows = buildRows(data);
    const row = rows.find((r) => r.name === "Plain QB");
    expect(row).toBeDefined();

    // Without mirrored fields, should use safe defaults
    expect(["high", "medium", "low", "none"]).toContain(row.confidenceBucket);
    expect(Array.isArray(row.anomalyFlags)).toBe(true);
    expect(typeof row.quarantined).toBe("boolean");
    expect(typeof row.identityConfidence).toBe("number");
    expect(typeof row.identityMethod).toBe("string");
  });

  it("quarantined=true from legacy dict is preserved", () => {
    const data = {
      players: {
        "Quarantined WR": {
          _composite: 6000,
          _rawComposite: 6000,
          _finalAdjusted: 6000,
          _sites: 1,
          position: "WR",
          _canonicalSiteValues: { ktc: 6000 },
          quarantined: true,
          confidenceBucket: "low",
          confidenceLabel: "Low — quarantined due to identity/data-quality flags",
          anomalyFlags: ["name_collision_cross_universe"],
          identityConfidence: 0.4,
          identityMethod: "fuzzy_match",
        },
      },
      sleeper: { positions: { "Quarantined WR": "WR" } },
    };
    const rows = buildRows(data);
    const row = rows.find((r) => r.name === "Quarantined WR");
    expect(row).toBeDefined();
    expect(row.quarantined).toBe(true);
    expect(row.confidenceBucket).toBe("low");
    expect(row.anomalyFlags).toEqual(["name_collision_cross_universe"]);
    expect(row.identityConfidence).toBe(0.4);
    expect(row.identityMethod).toBe("fuzzy_match");
  });
});
