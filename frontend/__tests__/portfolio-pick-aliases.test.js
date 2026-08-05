/**
 * Portfolio pick value must agree with the rest of the tree.
 *
 * `portfolio-insights.js` was the only pick join in the codebase that ignored
 * `contract.pickAliases`. It expanded candidates and landed on the GENERIC
 * row ("2026 Mid 1st"), which is correct for future years and wrong for the
 * current one:
 *
 *   2026 Early 1st   rankDerivedValue = null    <- current year: unpriced
 *   2027 Early 1st   rankDerivedValue = 7049    <- future year: priced
 *   2026 Pick 1.02   rankDerivedValue = 6160    <- current year lives HERE
 *
 * The current-year board is priced on the SLOT rows, and the contract ships
 * `pickAliases` ("2026 Early 1st" -> "2026 Pick 1.02") for exactly this
 * redirect. Without it every one of a team's six 2026 picks priced at zero —
 * a shortfall of precisely 15,626 for all twelve teams, 187,512 league-wide,
 * 39% of all pick capital, while `league-analysis.js` (which does use
 * `resolvePickRow`) reported the correct number on the same page.
 *
 * Audit finding W20-F005.
 */
import { describe, expect, it } from "vitest";
import { computePortfolio } from "@/lib/portfolio-insights";

/** The live contract's pick shape, reduced to the rows that matter. */
function contractFixture() {
  return {
    pickAliases: {
      "2026 Early 1st": "2026 Pick 1.02",
      "2026 Mid 1st": "2026 Pick 1.06",
      "2027 Early 1st": "2027 Early 1st",
    },
    sleeper: { rosterPositions: ["QB", "RB", "WR", "TE", "BN", "BN"] },
  };
}

/** Board rows in the shape `buildRows` emits. */
function boardRows() {
  return [
    // Current year: generics unpriced, slots priced.
    { name: "2026 Early 1st", position: "PICK", rankDerivedValue: null },
    { name: "2026 Mid 1st", position: "PICK", rankDerivedValue: null },
    { name: "2026 Pick 1.02", position: "PICK", rankDerivedValue: 6160 },
    { name: "2026 Pick 1.06", position: "PICK", rankDerivedValue: 4200 },
    // Future year: the generic row IS the priced row.
    { name: "2027 Early 1st", position: "PICK", rankDerivedValue: 7049 },
  ];
}

function portfolioFor(picks) {
  return computePortfolio({
    rows: boardRows(),
    selectedTeam: { name: "T", players: [], picks },
    rawData: contractFixture(),
    history: {},
    rosterSettings: { rosterPositions: contractFixture().sleeper.rosterPositions },
  });
}

describe("portfolio pick valuation honours pickAliases", () => {
  it("prices a current-year pick from its slot row, not the null generic", () => {
    const out = portfolioFor(["2026 Early 1st"]);
    expect(out.pickValue).toBe(6160);
  });

  it("does not price current-year picks at zero", () => {
    // The defect's signature: resolves, but to a row with no value.
    const out = portfolioFor(["2026 Early 1st", "2026 Mid 1st"]);
    expect(out.pickValue).toBe(6160 + 4200);
    expect(out.pickValue).toBeGreaterThan(0);
  });

  it("still prices a future-year pick from its generic row", () => {
    // The alias map must not break the case that already worked.
    const out = portfolioFor(["2027 Early 1st"]);
    expect(out.pickValue).toBe(7049);
  });

  it("counts every resolved pick", () => {
    const out = portfolioFor(["2026 Early 1st", "2026 Mid 1st", "2027 Early 1st"]);
    expect(out.pickCount).toBe(3);
    expect(out.pickValue).toBe(6160 + 4200 + 7049);
  });

  it("leaves a pick with no board row unresolved rather than inventing a value", () => {
    // 2029 picks are genuinely unpriced — the board publishes nothing for
    // them. Inventing a number here is the failure this codebase already had
    // with the flat 7000/4000/2000/1200 table.
    const out = portfolioFor(["2029 Early 1st"]);
    expect(out.pickValue).toBe(0);
    expect(out.unresolved).toContain("2029 Early 1st");
  });

  it("handles the Sleeper '(own)' suffix the raw team payload carries", () => {
    const out = portfolioFor(["2026 Early 1st (own)"]);
    expect(out.pickValue).toBe(6160);
  });
});
