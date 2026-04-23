import { describe, it, expect } from "vitest";
import {
  WEIGHT_PRESETS,
  presetToWeights,
  detectActivePreset,
} from "@/lib/weight-presets";
import { RANKING_SOURCES } from "@/lib/dynasty-data";

describe("weight-presets", () => {
  it("exposes three named presets + labels", () => {
    expect(Object.keys(WEIGHT_PRESETS).sort()).toEqual(["balanced", "expert", "market"]);
    for (const p of Object.values(WEIGHT_PRESETS)) {
      expect(p.label).toBeTruthy();
      expect(p.description).toBeTruthy();
    }
  });

  it("balanced preset produces empty siteWeights", () => {
    expect(presetToWeights("balanced")).toEqual({});
  });

  it("market preset weights retail 2.0, experts 0.5", () => {
    const w = presetToWeights("market");
    // At least one retail source exists in the registry.
    const retail = RANKING_SOURCES.filter((s) => s.isRetail);
    expect(retail.length).toBeGreaterThan(0);
    for (const r of retail) {
      expect(w[r.key].weight).toBe(2.0);
    }
    // Experts should be 0.5.
    const experts = RANKING_SOURCES.filter((s) => !s.isRetail);
    expect(experts.length).toBeGreaterThan(0);
    for (const e of experts) {
      expect(w[e.key].weight).toBe(0.5);
    }
  });

  it("expert preset weights experts 1.5, retail 0.5", () => {
    const w = presetToWeights("expert");
    const retail = RANKING_SOURCES.filter((s) => s.isRetail);
    for (const r of retail) {
      expect(w[r.key].weight).toBe(0.5);
    }
    const experts = RANKING_SOURCES.filter((s) => !s.isRetail);
    for (const e of experts) {
      expect(w[e.key].weight).toBe(1.5);
    }
  });

  it("every preset entry has include: true", () => {
    for (const key of ["market", "expert"]) {
      const w = presetToWeights(key);
      for (const v of Object.values(w)) {
        expect(v.include).toBe(true);
      }
    }
  });

  it("detectActivePreset returns 'balanced' for empty weights", () => {
    expect(detectActivePreset({})).toBe("balanced");
    expect(detectActivePreset(null)).toBe("balanced");
    expect(detectActivePreset(undefined)).toBe("balanced");
  });

  it("detectActivePreset identifies default-equal dict as balanced", () => {
    const allEqual = Object.fromEntries(
      RANKING_SOURCES.map((s) => [s.key, { include: true, weight: 1.0 }]),
    );
    expect(detectActivePreset(allEqual)).toBe("balanced");
  });

  it("detectActivePreset identifies round-trip of market preset", () => {
    const weights = presetToWeights("market");
    expect(detectActivePreset(weights)).toBe("market");
  });

  it("detectActivePreset identifies round-trip of expert preset", () => {
    const weights = presetToWeights("expert");
    expect(detectActivePreset(weights)).toBe("expert");
  });

  it("detectActivePreset returns 'custom' for unusual weights", () => {
    const custom = { ktc: { include: true, weight: 3.0 } };
    expect(detectActivePreset(custom)).toBe("custom");
  });

  it("detectActivePreset tolerates tiny float drift", () => {
    const market = presetToWeights("market");
    // Nudge one weight by 0.001 — still matches.
    const firstKey = Object.keys(market)[0];
    market[firstKey].weight = market[firstKey].weight + 0.001;
    expect(detectActivePreset(market)).toBe("market");
  });

  it("detectActivePreset returns 'custom' when include flags differ", () => {
    const market = presetToWeights("market");
    const firstKey = Object.keys(market)[0];
    market[firstKey].include = false;
    expect(detectActivePreset(market)).toBe("custom");
  });
});
