/**
 * MISSING IS NEVER ZERO, on the trade-history value path.
 *
 * C1-U6 follow-up 4.  Every unresolvable branch of `resolveTradeItemValue`
 * returned `value: 0`, and the aggregator then folded that into a side's
 * total as an asset worth nothing — silently understating whichever side
 * of a historical trade happened to contain it, and rendering as a
 * measured zero.  Worse, the alpha-weighted sum added
 * `Math.pow(Math.max(0, 1), alpha)` = 1 per unresolvable asset, so the
 * assets we knew least about each contributed a fabricated unit of value.
 *
 * The repair returns `null` + `unresolved: true` and excludes those assets
 * from both sums, counting them instead.  These tests pin the distinction
 * that matters: an asset priced at a real value and an asset the board
 * cannot price must not produce the same arithmetic.
 */
import { describe, it, expect } from "vitest";
import {
  analyzeSleeperTradeHistory,
  buildRowLookup,
  resolveTradeItemValue,
} from "@/lib/league-analysis";

const row = (name, full, pos = "WR") => ({ name, pos, values: { full }, raw: {} });

describe("resolveTradeItemValue — unresolvable assets", () => {
  const lookup = buildRowLookup([
    row("Ja'Marr Chase", 9200),
    row("2027 Pick 1.01", 7000, "PICK"),
    // A row the board explicitly declines to price.
    row("Unpriced Guy", null),
  ]);

  it("returns null, not 0, for a name with no board row", () => {
    const out = resolveTradeItemValue("Nobody At All", lookup, {}, {});
    expect(out.value).toBeNull();
    expect(out.unresolved).toBe(true);
  });

  it("returns null, not 0, for a pick with no board row", () => {
    const out = resolveTradeItemValue("2099 1.01", lookup, {}, {});
    expect(out.isPick).toBe(true);
    expect(out.value).toBeNull();
    expect(out.unresolved).toBe(true);
  });

  it("returns null for a row the board leaves unpriced", () => {
    const out = resolveTradeItemValue("Unpriced Guy", lookup, {}, {});
    expect(out.value).toBeNull();
    expect(out.unresolved).toBe(true);
  });

  it("still prices what the board does price", () => {
    const out = resolveTradeItemValue("Ja'Marr Chase", lookup, {}, {});
    expect(out.value).toBe(9200);
    expect(out.unresolved).toBe(false);
  });
});

describe("trade aggregation excludes unpriced assets instead of zeroing them", () => {
  const rows = [
    { name: "Ja'Marr Chase", pos: "WR", values: { full: 9200, raw: 9200 } },
    { name: "Puka Nacua", pos: "WR", values: { full: 8000, raw: 8000 } },
  ];

  function analyze(got, gave) {
    const rawData = {
      sleeper: {
        teams: [
          { name: "Alpha", roster_id: 1, ownerId: "u1" },
          { name: "Beta", roster_id: 2, ownerId: "u2" },
        ],
        trades: [
          {
            week: 1,
            timestamp: Date.now() - 24 * 60 * 60 * 1000,
            sides: [
              { team: "Alpha", rosterId: 1, ownerId: "u1", got, gave },
              { team: "Beta", rosterId: 2, ownerId: "u2", got: gave, gave: got },
            ],
          },
        ],
      },
    };
    return analyzeSleeperTradeHistory(rawData, rows);
  }

  it("an unpriced asset changes neither side's totals", () => {
    const withGhost = analyze(["Ja'Marr Chase", "Totally Unknown Asset"], ["Puka Nacua"]);
    const without = analyze(["Ja'Marr Chase"], ["Puka Nacua"]);
    const a = withGhost.analyzed[0].sides[0];
    const b = without.analyzed[0].sides[0];
    // Identical REAL assets on both runs.  Before the repair the ghost
    // added 1 to `gotWeighted` and the two runs disagreed.
    expect(a.gotValue).toBe(b.gotValue);
    expect(a.gotWeighted).toBeCloseTo(b.gotWeighted, 9);
    expect(a.pctGap).toBeCloseTo(b.pctGap, 9);
  });

  it("counts the unpriced asset so the omission is visible, not silent", () => {
    const withGhost = analyze(["Ja'Marr Chase", "Totally Unknown Asset"], ["Puka Nacua"]);
    const side = withGhost.analyzed[0].sides[0];
    expect(side.gotUnresolved).toBe(1);
    expect(side.unresolvedAssets).toBe(1);
    // …and the item itself renders as unpriced, never as 0.
    const ghost = side.got.find((i) => i.name === "Totally Unknown Asset");
    expect(ghost.val).toBeNull();
    expect(ghost.unresolved).toBe(true);
  });

  it("a fully priced trade reports nothing unresolved", () => {
    const clean = analyze(["Ja'Marr Chase"], ["Puka Nacua"]);
    expect(clean.analyzed[0].sides[0].unresolvedAssets).toBe(0);
  });
});
