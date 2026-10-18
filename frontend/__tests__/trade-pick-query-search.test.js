/**
 * TC-A / UX audit P1-8 — pick search understands slot, tier and generic forms.
 *
 * "2027 1st", "2027 Mid" and "2027 Round 1" returned "No matches": the
 * current class is priced on SLOT rows ("2027 Pick 1.05") and its tier rows
 * are suppressed aliases, so text matching could not connect the query to
 * the rows that price it.  The query is now parsed with the pick grammar
 * (`parsePickToken` / `tierForSlot`, held to the Python owner by
 * tests/identity/test_pick_grammar_frontend_parity.py) and matched against
 * each row's own grade.
 */
import { describe, it, expect } from "vitest";
import {
  parsePickQuery,
  pickRowMatchesQuery,
  searchCalculatorAssets,
  searchTradeAssets,
} from "../lib/trade-logic.js";

let rank = 1;
const pick = (name, extra = {}) => ({
  name,
  assetClass: "pick",
  pos: "PICK",
  values: { full: 5000 },
  rankDerivedValue: 5000,
  blendedSourceRank: rank++,
  ...extra,
});

const ROWS = [
  { name: "Justin Jefferson", assetClass: "offense", pos: "WR", blendedSourceRank: 0, values: { full: 8600 } },
  ...Array.from({ length: 12 }, (_, i) => pick(`2027 Pick 1.${String(i + 1).padStart(2, "0")}`)),
  ...Array.from({ length: 12 }, (_, i) => pick(`2027 Pick 2.${String(i + 1).padStart(2, "0")}`)),
  // Current-class tier rows are suppressed aliases of the slot rows.
  pick("2027 Early 1st", { pickGenericSuppressed: true, rankDerivedValue: null, values: { full: 0 } }),
  pick("2027 Mid 1st", { pickGenericSuppressed: true, rankDerivedValue: null, values: { full: 0 } }),
  pick("2028 Early 1st"),
  pick("2028 Mid 1st"),
  pick("2028 Late 1st"),
  pick("2028 Round 1"),
  pick("2028 Early 2nd"),
];

const names = (q, limit = 30) => searchTradeAssets(ROWS, q, limit).map((r) => r.name);

describe("structured pick queries", () => {
  it('"2027 1st" finds the 2027 first-round slot rows (was "No matches")', () => {
    const got = names("2027 1st");
    expect(got).toHaveLength(12);
    expect(got.every((n) => /^2027 Pick 1\.\d\d$/.test(n))).toBe(true);
    expect(got[0]).toBe("2027 Pick 1.01");
  });

  it('"2027 Round 1" finds the same rows', () => {
    expect(names("2027 Round 1")).toEqual(names("2027 1st"));
  });

  it('"2027 Mid 1st" finds the Mid slots, not the suppressed alias', () => {
    expect(names("2027 Mid 1st")).toEqual([
      "2027 Pick 1.05",
      "2027 Pick 1.06",
      "2027 Pick 1.07",
      "2027 Pick 1.08",
    ]);
  });

  it('"2027 Mid" finds every 2027 Mid slot', () => {
    const got = names("2027 Mid");
    expect(got).toHaveLength(8);
    expect(got).toContain("2027 Pick 2.05");
  });

  it('"1.01" finds the exact slot', () => {
    expect(names("1.01")).toEqual(["2027 Pick 1.01"]);
  });

  it('"2028 1st" finds the tier rows and the generic row', () => {
    expect(names("2028 1st").sort()).toEqual(
      ["2028 Early 1st", "2028 Late 1st", "2028 Mid 1st", "2028 Round 1"].sort(),
    );
  });

  it('"2028 1.01" finds the tier that slot belongs to', () => {
    expect(names("2028 1.01")).toEqual(["2028 Early 1st"]);
  });

  it("does not disturb player search or a bare word", () => {
    expect(names("Jefferson")).toEqual(["Justin Jefferson"]);
    expect(parsePickQuery("mid")).toBeNull();
    expect(parsePickQuery("Jefferson 1st")).toBeNull();
  });

  it("owned picks match structurally too", () => {
    const owned = [
      { ...pick("2027 Pick 1.03"), assetId: "pick:lk:2027:r1:o4", assetLabel: "2027 1.03 (own)" },
      { ...pick("2028 Mid 2nd"), assetId: "pick:lk:2028:r2:o4", assetLabel: "2028 2nd (own)" },
    ];
    const got = searchCalculatorAssets([], "2027 Round 1", owned);
    expect(got.map((e) => e.assetId)).toEqual(["pick:lk:2027:r1:o4"]);
  });

  it("parses the accepted forms", () => {
    expect(parsePickQuery("2027 1st")).toEqual({ year: "2027", round: "1st", tier: null, slot: null });
    expect(parsePickQuery("2027 round 1")).toMatchObject({ year: "2027", round: "1st" });
    expect(parsePickQuery("late 2nd 2029")).toMatchObject({ year: "2029", round: "2nd", tier: "late" });
    expect(parsePickQuery("pick 1.06")).toMatchObject({ round: "1st", slot: 6 });
    expect(pickRowMatchesQuery("2029 Round 1", parsePickQuery("2029 mid 1st"))).toBe(false);
  });
});
