/**
 * OD-F6 option A (owner, 2026-10-21): the history grade is RELABELLED, never
 * re-graded.  JS twin of tests/public_league/test_history_grade_relabel_no_change.py
 * — read that docstring for the full rationale.
 *
 * tests/fixtures/history_grade_relabel_reference.json holds the PRE-change
 * outputs (written at main ce22d5de7, before the relabel).  Recomputing with
 * today's code must reproduce every letter, colour, pctGap and net exactly;
 * the one permitted difference is the tier-0 word "Fair trade", which now
 * reads HISTORY_EVEN_LABEL.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import {
  gradeTradeHistorySide,
  gradeTradeSide,
  gradeTradeSides,
} from "@/lib/league-analysis";
import {
  HISTORY_EVEN_LABEL,
  HISTORY_EVEN_PCT,
  historyGradeBasisText,
} from "@/lib/trade-history-grade-policy";

const REPO_ROOT = path.resolve(__dirname, "../..");
const REF = JSON.parse(
  fs.readFileSync(
    path.join(REPO_ROOT, "tests", "fixtures", "history_grade_relabel_reference.json"),
    "utf8",
  ),
);

function relabel(obj) {
  if (Array.isArray(obj)) return obj.map(relabel);
  if (obj && typeof obj === "object") {
    return Object.fromEntries(Object.entries(obj).map(([k, v]) => [k, relabel(v)]));
  }
  return obj === REF.preChangeLabel ? HISTORY_EVEN_LABEL : obj;
}

const EXPECTED = relabel(REF);

function scanRuns(isWinner) {
  const runs = [];
  for (let milli = 0; milli <= 60000; milli += 1) {
    const pct = milli / 1000;
    const g = gradeTradeHistorySide(pct, isWinner);
    const last = runs[runs.length - 1];
    if (!last || last[1] !== g.grade || last[2] !== g.color || last[3] !== g.label) {
      runs.push([pct, g.grade, g.color, g.label]);
    }
  }
  return runs;
}

describe("history grade relabel changes no grade (OD-F6 option A)", () => {
  it("the reference is the pre-change evidence", () => {
    expect(REF.preChangeLabel).toBe("Fair trade");
    expect(REF.sideCases.length).toBeGreaterThanOrEqual(600);
    expect(REF.tradeCases.length).toBeGreaterThanOrEqual(200);
  });

  it("the criterion is the reference's tier-0 cut", () => {
    expect(HISTORY_EVEN_PCT).toBe(REF.cuts[0]);
  });

  it("band table: identical runs over 0..60% except the tier-0 word", () => {
    expect(scanRuns(true)).toEqual(EXPECTED.bandRuns.winner);
    expect(scanRuns(false)).toEqual(EXPECTED.bandRuns.loser);
  });

  it("edge probes either side of every cut point are identical", () => {
    for (const [pct, isWinner, grade, color, label] of EXPECTED.edgeProbes) {
      expect(gradeTradeHistorySide(pct, isWinner)).toEqual({ grade, color, label });
    }
  });

  it("every side's numbers and grade are identical", () => {
    REF.sideCases.forEach((c, i) => {
      expect(gradeTradeSide(c.got, c.gave, c.vaNet)).toEqual(EXPECTED.sideCases[i].out);
    });
  });

  it("every trade's letters and labels are identical (VA from the active model)", () => {
    // The VA engine is pinned across languages by the parity suite with a
    // tolerance; here the grade itself must match exactly.
    REF.tradeCases.forEach((c, i) => {
      const got = gradeTradeSides(c.sides).map((s) => s.grade);
      expect(got).toEqual(EXPECTED.tradeCases[i].out.map((s) => s.grade));
    });
  });

  it("the new word is not the market-fairness phrase", () => {
    expect(HISTORY_EVEN_LABEL).toBe("Evenly valued");
    expect(HISTORY_EVEN_LABEL.toLowerCase()).not.toContain("fair");
    expect(gradeTradeHistorySide(0, true).label).toBe(HISTORY_EVEN_LABEL);
  });

  it("the basis text names values, the threshold and that it is not the FAIR verdict", () => {
    const t = historyGradeBasisText();
    expect(t).toContain(`${HISTORY_EVEN_PCT}%`);
    expect(t).toMatch(/value/i);
    expect(t).toMatch(/not .*perform/i);
    expect(t).toMatch(/FAIR/);
  });
});
