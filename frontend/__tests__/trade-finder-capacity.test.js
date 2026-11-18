// Roster capacity as words on the generated trade surfaces (/angle, Best
// Offers, Package Builder).  Every number is the backend's
// (src/trade/roster_capacity.py); these tests pin that a forced release is
// SHOWN with its value, an unpriced one reads "value unknown", an unknown
// requirement reads "may require a release", and a missing block never reads
// as "fits" or as zero.
import { describe, expect, it } from "vitest";
import { forcedReleaseSummary } from "@/lib/trade-finder-capacity";

const REQUIRES = {
  rosterLimit: 58,
  requiresDrops: true,
  certainty: "exact",
  forcedDropsAreUpperBound: false,
  forcedDrops: [
    { playerId: "123", name: "Bench WR", position: "WR", value: 812.4 },
    { playerId: "456", name: "Deep LB", position: "LB", value: 1440.6 },
  ],
  forcedDropValue: 2253.0,
  unpricedForcedDrops: 0,
  ladderExhausted: false,
};

describe("forcedReleaseSummary", () => {
  it("names every forced release with its value and the total released", () => {
    const s = forcedReleaseSummary(REQUIRES);
    expect(s.state).toBe("requires");
    expect(s.tone).toBe("warning");
    expect(s.headline).toBe(
      "Forces 2 releases to fit the 58-man limit — 2,253 value released.",
    );
    expect(s.drops.map((d) => `${d.label} — ${d.valueText}`)).toEqual([
      "Bench WR (WR) — 812 value",
      "Deep LB (LB) — 1,441 value",
    ]);
    expect(s.dropsLabel).toBe("Released");
  });

  it("an unpriced drop reads 'value unknown', never 0, and is not counted in the total", () => {
    const s = forcedReleaseSummary({
      ...REQUIRES,
      forcedDrops: [REQUIRES.forcedDrops[0], { playerId: "Unknown Guy", name: "Unknown Guy", position: "DL", value: null }],
      forcedDropValue: 812.4,
      unpricedForcedDrops: 1,
    });
    expect(s.drops[1].valueText).toBe("value unknown");
    expect(s.drops[1].priced).toBe(false);
    expect(s.drops[1].valueText).not.toMatch(/\b0\b/);
    expect(s.headline).toContain("812 value released");
    expect(s.headline).toContain("(plus 1 with value unknown, not counted)");
  });

  it("an unreported unpriced-drop count is unknown, never 'every release priced'", () => {
    for (const missing of [undefined, null, "2"]) {
      const s = forcedReleaseSummary({ ...REQUIRES, unpricedForcedDrops: missing });
      expect(s.headline).toContain("whether every release is priced is not reported");
      expect(s.headline).not.toContain("with value unknown, not counted");
    }
    const priced = forcedReleaseSummary(REQUIRES);
    expect(priced.headline).not.toContain("not reported");
  });

  it("an unknown released total reads 'released value unknown', never 0", () => {
    const s = forcedReleaseSummary({ ...REQUIRES, forcedDropValue: null });
    expect(s.headline).toContain("released value unknown");
    expect(s.headline).not.toMatch(/\b0 value/);
  });

  it("an upper-bound bracket says 'at most'", () => {
    const s = forcedReleaseSummary({
      ...REQUIRES,
      certainty: "partial",
      forcedDropsAreUpperBound: true,
    });
    expect(s.headline).toMatch(/^Forces at most 2 releases/);
    expect(s.headline).toContain("(taxi occupancy unknown)");
    expect(s.dropsLabel).toBe("Worst case");
  });

  it("requiresDrops === null reads 'may require a release' and shows the worst case", () => {
    const s = forcedReleaseSummary({
      ...REQUIRES,
      requiresDrops: null,
      certainty: "partial",
      forcedDropsAreUpperBound: true,
    });
    expect(s.state).toBe("maybe");
    expect(s.headline).toMatch(/may require a release/i);
    expect(s.drops).toHaveLength(2);
    expect(s.dropsLabel).toBe("Worst case");
  });

  it("an unknown roster limit is unknown, not unlimited", () => {
    const s = forcedReleaseSummary({ rosterLimit: null, requiresDrops: null, forcedDrops: [] });
    expect(s.state).toBe("unknown_limit");
    expect(s.headline).toBe("Roster limit unknown — this trade may require a release.");
  });

  it("a trade that fits says so", () => {
    const s = forcedReleaseSummary({ ...REQUIRES, requiresDrops: false, forcedDrops: [], forcedDropValue: 0 });
    expect(s.state).toBe("fits");
    expect(s.headline).toBe("Fits your roster — no release needed.");
    expect(s.drops).toEqual([]);
  });

  it("an unavailable block reads 'could not be checked', never 'fits'", () => {
    const s = forcedReleaseSummary({ unavailable: "assessment_failed", notes: ["x"] });
    expect(s.state).toBe("unavailable");
    expect(s.headline).toMatch(/could not be checked/);
    expect(s.headline).toMatch(/unknown, not zero/);
  });

  it("a missing block reads 'not checked', never 'fits'", () => {
    for (const missing of [undefined, null]) {
      const s = forcedReleaseSummary(missing);
      expect(s.state).toBe("not_checked");
      expect(s.headline).toMatch(/not checked/);
      expect(s.headline).not.toMatch(/fits|no release needed/i);
    }
  });

  it("no priced drop is 'released value unknown', never the backend's empty-sum 0", () => {
    // roster_capacity.py publishes forcedDropValue 0.0 when no drop is priced
    // (`float(sum(priced)) if priced else 0.0`): an empty sum, not a value.
    const unpricedDrops = [
      { playerId: "a", name: "Unknown A", position: "DL", value: null },
      { playerId: "b", name: "Unknown B", position: "DB", value: null },
    ];
    const all = forcedReleaseSummary({
      ...REQUIRES,
      forcedDrops: unpricedDrops,
      forcedDropValue: 0.0,
      unpricedForcedDrops: 2,
    });
    expect(all.headline).toBe(
      "Forces 2 releases to fit the 58-man limit — released value unknown (no release is priced).",
    );
    expect(all.headline).not.toMatch(/0 value/);

    // The backend's count alone says so, even if a listed drop looked priced.
    const byCount = forcedReleaseSummary({
      ...REQUIRES,
      forcedDrops: [REQUIRES.forcedDrops[0]],
      forcedDropValue: 0.0,
      unpricedForcedDrops: 1,
    });
    expect(byCount.headline).toContain("released value unknown (the release is not priced)");
    expect(byCount.headline).not.toMatch(/0 value released/);

    // Every listed drop unpriced, count not reported: still unknown.
    const byDrops = forcedReleaseSummary({
      ...REQUIRES,
      forcedDrops: unpricedDrops,
      forcedDropValue: 0.0,
      unpricedForcedDrops: undefined,
    });
    expect(byDrops.headline).toContain("released value unknown");
    expect(byDrops.headline).not.toMatch(/0 value released/);
  });

  it("a required release with no named drop and a 0.0 total is unknown, not 0 released", () => {
    const s = forcedReleaseSummary({
      ...REQUIRES,
      forcedDrops: [],
      forcedDropValue: 0.0,
      unpricedForcedDrops: 0,
      ladderExhausted: true,
    });
    expect(s.headline).toBe(
      "Forces a release to fit the 58-man limit — released value unknown — no fully legal cleanup found — who goes is not determined.",
    );
  });

  it("an overage owed before the trade is not blamed on the trade", () => {
    const s = forcedReleaseSummary({
      ...REQUIRES,
      forcedDrops: [
        ...REQUIRES.forcedDrops,
        { playerId: "789", name: "Spare TE", position: "TE", value: 300 },
      ],
      forcedDropValue: 2553.0,
      overLimitBefore: 2,
      overLimitAfter: 3,
    });
    expect(s.headline).toMatch(/^Needs 3 releases to fit the 58-man limit/);
    expect(s.headline).not.toMatch(/^Forces/);
    // Both counts are the backend's own fields, never a browser subtraction.
    expect(s.context).toBe(
      "Your roster is already 2 over the 58-man limit before this trade — 2 releases owed with or without it; after it, 3 over.",
    );
  });

  it("an overage under unknown taxi occupancy is stated as a bound", () => {
    const s = forcedReleaseSummary({
      ...REQUIRES,
      certainty: "partial",
      forcedDropsAreUpperBound: true,
      overLimitBefore: 1,
      overLimitAfter: null,
      overLimitAfterMin: 0,
      overLimitAfterMax: 2,
    });
    expect(s.headline).toMatch(/^Needs at most 2 releases/);
    expect(s.context).toBe(
      "Your roster may already be up to 1 over the 58-man limit before this trade (taxi occupancy unknown) — up to 1 release owed with or without it; after it, up to 2 over.",
    );
  });

  it("no overage before the trade adds no context and keeps 'Forces'", () => {
    for (const before of [0, null, undefined]) {
      const s = forcedReleaseSummary({ ...REQUIRES, overLimitBefore: before });
      expect(s.context).toBeNull();
      expect(s.headline).toMatch(/^Forces 2 releases/);
    }
  });

  it("words a counterparty's roster as theirs", () => {
    const fits = forcedReleaseSummary(
      { ...REQUIRES, requiresDrops: false, forcedDrops: [], forcedDropValue: 0 },
      { team: "Other Team" },
    );
    expect(fits.headline).toBe("Fits Other Team's roster — no release needed.");
    const over = forcedReleaseSummary(
      { ...REQUIRES, overLimitBefore: 1, overLimitAfter: 2 },
      { team: "Other Team" },
    );
    expect(over.context).toMatch(/^Other Team's roster is already 1 over/);
  });

  it("a required release with no named drop says who goes is undetermined", () => {
    const s = forcedReleaseSummary({ ...REQUIRES, forcedDrops: [], forcedDropValue: null, ladderExhausted: true });
    expect(s.headline).toBe(
      "Forces a release to fit the 58-man limit — released value unknown — no fully legal cleanup found — who goes is not determined.",
    );
  });
});
