import { describe, it, expect } from "vitest";
import {
  valueSideAtTime,
  gradeRetro,
  REASON_NO_PRIOR,
  REASON_PICK_HISTORY,
  REASON_UNDATED,
} from "@/lib/trade-retro-value";
import { valueFromRank } from "@/lib/value-history";

function makeLookup(map) {
  return (name) => map[String(name).toLowerCase()] || [];
}

describe("valueSideAtTime — as-of evidence only", () => {
  it("prefers the server-stamped val over re-deriving from rank", () => {
    // The backend stamps ``val`` (canonical pipeline value) on every history
    // point so retro grading lines up with the live ``/api/data`` scale
    // rather than a frozen client-side Hill curve.
    const lookup = makeLookup({
      "player a": [
        { date: "2025-01-01", rank: 30, val: 4321 },
        { date: "2025-06-01", rank: 10, val: 7777 },
      ],
    });
    const out = valueSideAtTime(
      [{ name: "Player A", val: 9999, isPick: false }],
      lookup,
      Date.parse("2025-03-01"),
    );
    expect(out.total).toBe(4321);
    expect(out.items[0].source).toBe("rankHistory");
    expect(out.complete).toBe(true);
  });

  it("derives from the rank when the point carries no val", () => {
    // Still an AS-OF observation — an approximation of the curve, not a
    // substitution of another date's evidence.
    const lookup = makeLookup({
      "player a": [
        { date: "2025-01-01", rank: 30 },
        { date: "2025-06-01", rank: 10 },
      ],
    });
    const out = valueSideAtTime(
      [{ name: "Player A", val: 9999, isPick: false }],
      lookup,
      Date.parse("2025-03-01"),
    );
    expect(out.total).toBe(valueFromRank(30));
    expect(out.items[0].source).toBe("rankHistory");
  });

  it("NEVER answers with a future observation", () => {
    // The retired behaviour: when the trade predated coverage, the EARLIEST
    // sample was used as a proxy and stamped ``rankHistory`` — a future
    // snapshot presented as contemporaneous truth, with no distance cap and
    // no direction constraint, so a 2024 trade priced at 2026 numbers.
    const lookup = makeLookup({
      "rookie x": [{ date: "2025-08-01", rank: 50, val: 3000 }],
    });
    const out = valueSideAtTime(
      [{ name: "Rookie X", val: 9999, isPick: false }],
      lookup,
      Date.parse("2025-04-01"), // before history starts
    );
    expect(out.items[0].source).toBe("unavailable");
    expect(out.items[0].val).toBeNull();
    expect(out.items[0].reason).toBe(REASON_NO_PRIOR);
    expect(out.total).toBe(0);
    expect(out.complete).toBe(false);
  });

  it("does not substitute the CURRENT value when there is no history", () => {
    const out = valueSideAtTime(
      [{ name: "Unknown Player", val: 1234 }],
      makeLookup({}),
      Date.parse("2025-04-01"),
    );
    expect(out.items[0].source).toBe("unavailable");
    expect(out.items[0].reason).toBe(REASON_NO_PRIOR);
    // 1234 is today's number.  It is not this player's value on the trade
    // date, and it must not be counted as though it were.
    expect(out.total).toBe(0);
  });

  it("reports picks as unavailable rather than pricing them at today", () => {
    const out = valueSideAtTime(
      [{ name: "2026 1st (mid)", val: 5000, isPick: true }],
      makeLookup({}),
      Date.parse("2025-04-01"),
    );
    expect(out.items[0].source).toBe("unavailable");
    expect(out.items[0].reason).toBe(REASON_PICK_HISTORY);
    expect(out.total).toBe(0);
  });

  it("refuses everything when the trade has no usable date", () => {
    const lookup = makeLookup({
      "player a": [{ date: "2025-01-01", rank: 30, val: 4321 }],
    });
    const out = valueSideAtTime([{ name: "Player A", val: 9999 }], lookup, NaN);
    expect(out.items[0].reason).toBe(REASON_UNDATED);
    expect(out.complete).toBe(false);
  });

  it("returns an empty, complete side for empty input", () => {
    for (const empty of [[], null]) {
      expect(valueSideAtTime(empty, () => [], Date.now())).toEqual({
        total: 0,
        items: [],
        covered: 0,
        uncovered: 0,
        complete: true,
      });
    }
  });

  it("counts coverage per item, not per side", () => {
    const lookup = makeLookup({
      "known": [{ date: "2025-01-01", rank: 30, val: 4000 }],
    });
    const out = valueSideAtTime(
      [
        { name: "Known", val: 9999 },
        { name: "Unknown", val: 8888 },
        { name: "2027 1st", val: 5000, isPick: true },
      ],
      lookup,
      Date.parse("2025-03-01"),
    );
    expect(out.covered).toBe(1);
    expect(out.uncovered).toBe(2);
    expect(out.total).toBe(4000);
  });
});

describe("gradeRetro — aging is measured, or it is refused", () => {
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
    const out = gradeRetro({ side, currentNet: 500, asOfMs: asOf, historyLookup: lookup });
    expect(out.atTradeNet).toBe(1500 - 8800);
    expect(out.insufficientEvidence).toBe(false);
    expect(out.verdictDelta).toBeGreaterThan(200);
    expect(out.verdict).toBe("aged_well");
  });

  it("flags 'aged_poorly' when current net is much worse", () => {
    const side = {
      got: [{ name: "Got Player", val: 1200, isPick: false }],
      gave: [{ name: "Gave Player", val: 9500, isPick: false }],
    };
    const out = gradeRetro({ side, currentNet: -8300, asOfMs: asOf, historyLookup: lookup });
    expect(out.verdictDelta).toBeLessThan(-200);
    expect(out.verdict).toBe("aged_poorly");
  });

  it("flags 'stable' when delta is small AND the evidence is complete", () => {
    const lookup2 = makeLookup({
      got: [{ date: "2025-01-01", rank: 30, val: 4000 }],
      gave: [{ date: "2025-01-01", rank: 30, val: 4000 }],
    });
    const side = {
      got: [{ name: "Got", val: 4050, isPick: false }],
      gave: [{ name: "Gave", val: 4000, isPick: false }],
    };
    const out = gradeRetro({ side, currentNet: 50, asOfMs: asOf, historyLookup: lookup2 });
    expect(out.atTradeComplete).toBe(true);
    expect(out.verdict).toBe("stable");
  });

  it("refuses rather than reporting 'stable' when a player is uncovered", () => {
    // This is the failure the whole unit exists for.  Uncovered items used to
    // be priced at today's value, which drags atTradeNet toward currentNet,
    // which drags verdictDelta toward 0, which renders "Stable" — the badge
    // for "nothing changed" shown because nothing was measured.
    const side = {
      got: [{ name: "Got Player", val: 5000, isPick: false }],
      gave: [{ name: "Nobody Has History For Him", val: 4500, isPick: false }],
    };
    const out = gradeRetro({ side, currentNet: 500, asOfMs: asOf, historyLookup: lookup });
    expect(out.verdict).toBe("unknown");
    expect(out.insufficientEvidence).toBe(true);
    expect(out.verdictDelta).toBeNull();
    expect(out.missing).toEqual([
      { name: "Nobody Has History For Him", reason: REASON_NO_PRIOR },
    ]);
  });

  it("refuses a picks-only trade instead of grading it 0 by construction", () => {
    // Both sides priced at today's numbers meant atTradeNet === currentNet
    // exactly, so verdictDelta was 0 for EVERY picks-only trade ever traded.
    const side = {
      got: [{ name: "2027 1st", val: 6000, isPick: true }],
      gave: [{ name: "2027 2nd", val: 2500, isPick: true }],
    };
    const out = gradeRetro({ side, currentNet: 3500, asOfMs: asOf, historyLookup: lookup });
    expect(out.verdict).toBe("unknown");
    expect(out.missing.map((m) => m.reason)).toEqual([
      REASON_PICK_HISTORY,
      REASON_PICK_HISTORY,
    ]);
  });

  it("refuses an undated trade instead of grading it as of now", () => {
    const side = {
      got: [{ name: "Got Player", val: 5000 }],
      gave: [{ name: "Gave Player", val: 4500 }],
    };
    const out = gradeRetro({ side, currentNet: 500, asOfMs: NaN, historyLookup: lookup });
    expect(out.verdict).toBe("unknown");
    expect(out.missing.every((m) => m.reason === REASON_UNDATED)).toBe(true);
  });

  it("returns 'unknown' when currentNet is non-finite", () => {
    const out = gradeRetro({ side: { got: [], gave: [] }, currentNet: NaN, asOfMs: asOf, historyLookup: lookup });
    expect(out.verdict).toBe("unknown");
  });

  it("keeps the covered part inspectable while refusing the comparison", () => {
    // Refusing the VERDICT is not the same as discarding the evidence: the
    // covered half is still shown, flagged as incomplete.
    const side = {
      got: [{ name: "Got Player", val: 5000 }],
      gave: [{ name: "2027 1st", val: 4500, isPick: true }],
    };
    const out = gradeRetro({ side, currentNet: 500, asOfMs: asOf, historyLookup: lookup });
    expect(out.atTradeGot.total).toBe(1500);
    expect(out.atTradeGot.complete).toBe(true);
    expect(out.atTradeGave.complete).toBe(false);
    expect(out.atTradeComplete).toBe(false);
    expect(out.verdict).toBe("unknown");
  });
});

describe("no-hindsight structural guard (lane brief §12)", () => {
  it("a dated question can never be answered by a later observation", () => {
    // Property, not an example: for any as-of instant, the value returned
    // must equal the value of the newest sample at or before it — and must
    // be null when there is none.  A regression that reintroduced a
    // "nearest either way" or "earliest available" fallback fails here
    // whatever shape it took.
    const points = [
      { date: "2025-01-01", rank: 10, val: 1000 },
      { date: "2025-03-01", rank: 10, val: 3000 },
      { date: "2025-06-01", rank: 10, val: 6000 },
    ];
    const lookup = makeLookup({ p: points });
    const cases = [
      ["2024-12-31", null],
      ["2025-01-01", 1000],
      ["2025-02-28", 1000],
      ["2025-03-01", 3000],
      ["2025-05-31", 3000],
      ["2025-06-01", 6000],
      ["2026-01-01", 6000],
    ];
    for (const [when, expected] of cases) {
      const out = valueSideAtTime([{ name: "P", val: 9999 }], lookup, Date.parse(when));
      const got = out.items[0].val;
      expect([when, got]).toEqual([when, expected]);
    }
  });
});
