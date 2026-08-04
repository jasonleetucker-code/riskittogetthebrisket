/**
 * Portfolio pick join — pins a join that resolved 0 of 288 picks.
 *
 * Sleeper labels a pick "2026 1.02 (own)"; the contract row is named
 * "2026 Pick 1.02". The lookup already lowercased, so the case was
 * never the defect — the FORMAT was. Every one of the 12 teams
 * therefore rendered a permanent "N unresolved" badge, `pickCount`
 * stayed 0 so the "Picks $X · N" legend never drew, and the comment
 * above it promising picks appear in Total Value was false.
 *
 * The second describe block is the important one. This fix recovers
 * 216 of 288 and NOT 288 of 288, and that gap is correct rather than
 * residual: the board publishes 2026, 2027 and 2028 pick rows and
 * nothing for 2029. A future change that makes all 288 resolve has
 * either extended the board (fine — update the fixture) or invented
 * values for picks it cannot price, which is the exact failure the
 * hardcoded 7000/4000/2000/1200 table already caused elsewhere in this
 * codebase. The test fails either way, on purpose.
 */
import { describe, it, expect } from "vitest";
import { computePortfolio } from "@/lib/portfolio-insights";

/** Contract rows in the two shapes the board actually publishes. */
function boardRows() {
  const rows = [
    { name: "Josh Allen", pos: "QB", age: 30, rankDerivedValue: 9988 },
    { name: "Puka Nacua", pos: "WR", age: 25, rankDerivedValue: 8000 },
  ];
  // 2026 — numbered slots, "YYYY Pick R.SS".
  for (let round = 1; round <= 4; round += 1) {
    for (let slot = 1; slot <= 3; slot += 1) {
      rows.push({
        name: `2026 Pick ${round}.0${slot}`,
        pos: "PICK",
        rankDerivedValue: 5000 - round * 800 - slot * 10,
      });
    }
  }
  // 2027/2028 — tiered, "YYYY Early|Mid|Late Nth".
  for (const year of [2027, 2028]) {
    for (const tier of ["Early", "Mid", "Late"]) {
      rows.push({
        name: `${year} ${tier} 1st`,
        pos: "PICK",
        rankDerivedValue: 4000,
      });
    }
  }
  // Deliberately NO 2029 rows — matching the live board.
  return rows;
}

function portfolioFor(picks) {
  return computePortfolio({
    rows: boardRows(),
    selectedTeam: { players: ["Josh Allen", "Puka Nacua"], picks },
    rawData: {},
    history: {},
  });
}

describe("pick labels the board can price", () => {
  it("resolves the '(own)' annotation Sleeper appends", () => {
    const p = portfolioFor(["2026 1.02 (own)"]);
    expect(p.unresolved).toEqual([]);
  });

  it("resolves a pick traded in from another team", () => {
    const p = portfolioFor(["2026 2.03 (from Team X)"]);
    expect(p.unresolved).toEqual([]);
  });

  it("resolves the bare numbered form with no annotation", () => {
    expect(portfolioFor(["2026 3.01"]).unresolved).toEqual([]);
  });

  it("resolves the tiered future-year form", () => {
    expect(portfolioFor(["2027 Mid 1st (own)"]).unresolved).toEqual([]);
  });

  it("counts resolved picks toward total value, not just player value", () => {
    const withoutPicks = portfolioFor([]);
    const withPicks = portfolioFor(["2026 1.01 (own)", "2026 1.02 (own)"]);
    expect(withPicks.totalValue).toBeGreaterThan(withoutPicks.totalValue);
  });
});

describe("pick labels the board genuinely cannot price", () => {
  it("leaves 2029 picks unresolved rather than inventing a value", () => {
    // The board stops at 2028. A 2029 pick has no row, so there is no
    // number to show — reporting it as unresolved is the honest answer
    // and the reason this fix recovers 216 of 288 rather than all 288.
    const p = portfolioFor(["2029 Mid 1st (own)"]);
    expect(p.unresolved).toEqual(["2029 Mid 1st (own)"]);
  });

  it("resolves every priced year and no unpriced one, in one roster", () => {
    const picks = [
      "2026 1.02 (own)",
      "2027 Mid 1st (own)",
      "2028 Late 1st (own)",
      "2029 Mid 1st (own)",
      "2029 Early 1st (own)",
    ];
    const p = portfolioFor(picks);
    // Exactly the 2029 pair, and nothing else, is unresolved.
    expect(p.unresolved.slice().sort()).toEqual(
      ["2029 Early 1st (own)", "2029 Mid 1st (own)"].sort(),
    );
    expect(p.unresolved.every((label) => label.startsWith("2029"))).toBe(true);
  });
});

describe("the regression itself", () => {
  it("a bare lowercase lookup would resolve none of these", () => {
    // Guards the guard: if someone reverts to byName.get(label
    // .toLowerCase()), every label above stops matching, because no
    // contract row is literally named "2026 1.02 (own)". This asserts
    // the two vocabularies really are different, so the tests above
    // cannot pass by accident.
    const names = new Set(boardRows().map((r) => r.name.toLowerCase()));
    for (const label of ["2026 1.02 (own)", "2027 Mid 1st (own)", "2026 3.01"]) {
      expect(names.has(label.toLowerCase())).toBe(false);
    }
  });
});
