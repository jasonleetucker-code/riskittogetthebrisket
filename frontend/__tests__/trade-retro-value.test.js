import { describe, it, expect } from "vitest";
import { valueSideAtTime, gradeRetro } from "@/lib/trade-retro-value";
import { valueFromRank } from "@/lib/value-history";

function makeLookup(map) {
  return (name) => map[String(name).toLowerCase()] || [];
}

describe("valueSideAtTime", () => {
  it("uses rankHistory rank-at-time to compute value", () => {
    const lookup = makeLookup({
      "player a": [
        { date: "2025-01-01", rank: 30 },
        { date: "2025-06-01", rank: 10 },
      ],
    });
    const asOf = Date.parse("2025-03-01");
    const out = valueSideAtTime(
      [{ name: "Player A", val: 9999, isPick: false }],
      lookup,
      asOf,
    );
    expect(out.total).toBe(valueFromRank(30));
    expect(out.items[0].source).toBe("rankHistory");
  });

  it("falls back to current val when no history found", () => {
    const out = valueSideAtTime(
      [{ name: "Unknown Player", val: 1234 }],
      makeLookup({}),
      Date.now(),
    );
    expect(out.items[0].source).toBe("current_fallback");
    expect(out.total).toBe(1234);
  });

  it("uses current val for picks (no per-pick history yet)", () => {
    const out = valueSideAtTime(
      [{ name: "2026 1st (mid)", val: 5000, isPick: true }],
      makeLookup({}),
      Date.now(),
    );
    expect(out.items[0].source).toBe("current");
    expect(out.total).toBe(5000);
  });

  it("returns {total: 0, items: []} for empty input", () => {
    expect(valueSideAtTime([], () => [], Date.now())).toEqual({ total: 0, items: [] });
    expect(valueSideAtTime(null, () => [], Date.now())).toEqual({ total: 0, items: [] });
  });

  it("uses earliest available sample when asOf is before all points", () => {
    const lookup = makeLookup({
      "rookie x": [
        { date: "2025-08-01", rank: 50 },
      ],
    });
    const asOf = Date.parse("2025-04-01"); // before history starts
    const out = valueSideAtTime(
      [{ name: "Rookie X", val: 9999, isPick: false }],
      lookup,
      asOf,
    );
    // Earliest point used as proxy.
    expect(out.items[0].source).toBe("rankHistory");
    expect(out.total).toBe(valueFromRank(50));
  });
});

describe("gradeRetro", () => {
  const lookup = makeLookup({
    "got player": [{ date: "2025-01-01", rank: 100 }], // value-at-trade ≈ small
    "gave player": [{ date: "2025-01-01", rank: 5 }],  // value-at-trade ≈ large
  });
  const asOf = Date.parse("2025-02-01");

  it("flags 'aged_well' when current net beats at-trade net by >200", () => {
    const side = {
      got: [{ name: "Got Player", val: valueFromRank(20), isPick: false }],
      gave: [{ name: "Gave Player", val: valueFromRank(30), isPick: false }],
    };
    // currentNet ≈ value(20) - value(30) ≈ positive
    const currentNet = valueFromRank(20) - valueFromRank(30);
    const out = gradeRetro({ side, currentNet, asOfMs: asOf, historyLookup: lookup });
    expect(out.atTradeNet).toBe(valueFromRank(100) - valueFromRank(5));
    expect(out.verdictDelta).toBeGreaterThan(200);
    expect(out.verdict).toBe("aged_well");
  });

  it("flags 'aged_poorly' when current net is much worse", () => {
    const side = {
      got: [{ name: "Got Player", val: valueFromRank(200), isPick: false }],
      gave: [{ name: "Gave Player", val: valueFromRank(2), isPick: false }],
    };
    const currentNet = valueFromRank(200) - valueFromRank(2); // very negative
    const out = gradeRetro({ side, currentNet, asOfMs: asOf, historyLookup: lookup });
    expect(out.verdictDelta).toBeLessThan(-200);
    expect(out.verdict).toBe("aged_poorly");
  });

  it("flags 'stable' when delta is small", () => {
    const lookup2 = makeLookup({
      "got": [{ date: "2025-01-01", rank: 30 }],
      "gave": [{ date: "2025-01-01", rank: 30 }],
    });
    const side = {
      got: [{ name: "Got", val: valueFromRank(30) + 50, isPick: false }],
      gave: [{ name: "Gave", val: valueFromRank(30), isPick: false }],
    };
    const currentNet = 50;
    const out = gradeRetro({ side, currentNet, asOfMs: asOf, historyLookup: lookup2 });
    expect(out.verdict).toBe("stable");
  });

  it("returns 'unknown' when currentNet is non-finite", () => {
    const side = { got: [], gave: [] };
    const out = gradeRetro({ side, currentNet: NaN, asOfMs: asOf, historyLookup: lookup });
    expect(out.verdict).toBe("unknown");
  });
});
