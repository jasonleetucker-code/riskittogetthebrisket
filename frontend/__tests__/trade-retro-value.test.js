import { describe, it, expect } from "vitest";
import { valueSideAtTime, gradeRetro } from "@/lib/trade-retro-value";
import { valueFromRank } from "@/lib/value-history";

function makeLookup(map) {
  return (name) => map[String(name).toLowerCase()] || [];
}

describe("valueSideAtTime", () => {
  it("prefers the server-stamped val over re-deriving from rank", () => {
    // The backend now stamps ``val`` (canonical pipeline value) on
    // every history point so retro grading lines up with the live
    // ``/api/data`` value scale rather than a frozen client-side
    // Hill curve.  When ``val`` is present, ``valueFromRank`` is
    // bypassed entirely.
    const lookup = makeLookup({
      "player a": [
        { date: "2025-01-01", rank: 30, val: 4321 },
        { date: "2025-06-01", rank: 10, val: 7777 },
      ],
    });
    const asOf = Date.parse("2025-03-01");
    const out = valueSideAtTime(
      [{ name: "Player A", val: 9999, isPick: false }],
      lookup,
      asOf,
    );
    expect(out.total).toBe(4321);
    expect(out.items[0].source).toBe("rankHistory");
  });

  it("falls back to the local Hill curve when val is missing on the point", () => {
    // Defensive path: if a snapshot ever ships without ``val`` (older
    // on-disk entry the backend forgot to back-fill), we still derive
    // a value rather than dropping the player.
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
  // Server-stamped val: 100 → small, 5 → large.  Numbers don't have
  // to match a specific curve any more — the backend pre-computes
  // them from the canonical pipeline.
  const lookup = makeLookup({
    "got player": [{ date: "2025-01-01", rank: 100, val: 1500 }],
    "gave player": [{ date: "2025-01-01", rank: 5, val: 8800 }],
  });
  const asOf = Date.parse("2025-02-01");

  it("flags 'aged_well' when current net beats at-trade net by >200", () => {
    const side = {
      got: [{ name: "Got Player", val: 5000, isPick: false }],
      gave: [{ name: "Gave Player", val: 4500, isPick: false }],
    };
    const currentNet = 5000 - 4500; // +500 today
    const out = gradeRetro({ side, currentNet, asOfMs: asOf, historyLookup: lookup });
    // At-trade net was 1500 - 8800 = -7300 (a brutal initial loss);
    // verdictDelta = 500 - (-7300) = 7800 → strongly aged_well.
    expect(out.atTradeNet).toBe(1500 - 8800);
    expect(out.verdictDelta).toBeGreaterThan(200);
    expect(out.verdict).toBe("aged_well");
  });

  it("flags 'aged_poorly' when current net is much worse", () => {
    const side = {
      got: [{ name: "Got Player", val: 1200, isPick: false }],
      gave: [{ name: "Gave Player", val: 9500, isPick: false }],
    };
    const currentNet = 1200 - 9500; // -8300 today
    const out = gradeRetro({ side, currentNet, asOfMs: asOf, historyLookup: lookup });
    // At-trade net was 1500 - 8800 = -7300; today is -8300 →
    // verdictDelta -1000 → aged_poorly.
    expect(out.verdictDelta).toBeLessThan(-200);
    expect(out.verdict).toBe("aged_poorly");
  });

  it("flags 'stable' when delta is small", () => {
    const lookup2 = makeLookup({
      "got": [{ date: "2025-01-01", rank: 30, val: 4000 }],
      "gave": [{ date: "2025-01-01", rank: 30, val: 4000 }],
    });
    const side = {
      got: [{ name: "Got", val: 4050, isPick: false }],
      gave: [{ name: "Gave", val: 4000, isPick: false }],
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
