/**
 * W20-F005 — the Terminal portfolio's pick join must follow the contract's
 * ``pickAliases`` like every other pick join (league-analysis, trade assets).
 * The current class is priced on slot rows ("2027 Pick 1.06"); its generic
 * tier rows are suppressed (null value) and redirected by ``pickAliases``.
 * A join that stops at the first candidate row lands on the suppressed row
 * and leaves a priced pick unresolved / unvalued.
 */
import { describe, it, expect } from "vitest";
import { computePortfolio } from "@/lib/portfolio-insights";
import { resolvePickRow } from "@/lib/trade-logic";

const rows = [
  { name: "Josh Allen", pos: "QB", age: 30, rankDerivedValue: 9988 },
  { name: "2027 Pick 1.06", pos: "PICK", assetClass: "pick", rankDerivedValue: 3059 },
  { name: "2027 Pick 1.01", pos: "PICK", assetClass: "pick", rankDerivedValue: 4987 },
  // suppressed generic tier row: no value, redirected by pickAliases
  {
    name: "2027 Mid 1st",
    pos: "PICK",
    assetClass: "pick",
    rankDerivedValue: null,
    pickGenericSuppressed: true,
  },
  { name: "2028 Mid 1st", pos: "PICK", assetClass: "pick", rankDerivedValue: 4000 },
];
const rawData = { pickAliases: { "2027 Mid 1st": "2027 Pick 1.06" } };

function run(picks, extra = {}) {
  return computePortfolio({
    rows,
    selectedTeam: { players: ["Josh Allen"], picks, ...extra },
    rawData,
    history: {},
  });
}

describe("W20-F005 portfolio pick join follows pickAliases", () => {
  it("prices a generic current-class pick on its aliased slot row", () => {
    const p = run(["2027 Mid 1st (own)"]);
    expect(p.unresolved).toEqual([]);
    expect(p.pickCount).toBe(1);
    expect(p.pickValue).toBe(3059);
  });

  it("agrees with the canonical resolver for every label", () => {
    const lookup = new Map(rows.map((r) => [r.name.toLowerCase(), r]));
    const labels = ["2027 Mid 1st (own)", "2027 1.01", "2028 Mid 1st"];
    const expected = labels.reduce(
      (s, l) => s + (resolvePickRow(l, lookup, rawData.pickAliases)?.rankDerivedValue || 0),
      0,
    );
    expect(run(labels).pickValue).toBe(expected);
  });

  it("still reports an unpriceable pick as unresolved, never 0 value", () => {
    const p = run(["2029 Mid 1st (own)"]);
    expect(p.unresolved).toEqual(["2029 Mid 1st (own)"]);
    expect(p.pickCount).toBe(0);
  });

  it("unavailable ownership stays unknown, not an empty portfolio", () => {
    const p = run(null, { pickOwnershipState: "unavailable", picks: null });
    expect(p.pickCount).toBeNull();
    expect(p.pickValue).toBeNull();
  });
});
