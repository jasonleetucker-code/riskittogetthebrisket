/**
 * TC-A — trade letter grades are monotone in the margin (JS twin of
 * tests/public_league/test_trade_grade_monotone.py).  The winner letters used
 * to run A, A, A-, B+, A+: a clearer win graded lower than a slight one.
 */
import { describe, it, expect } from "vitest";
import { gradeTradeHistorySide } from "../lib/league-analysis.js";

const RANK = { F: 0, D: 1, C: 2, B: 3, "B+": 4, "A-": 5, A: 6, "A+": 7 };
const SWEEP = Array.from({ length: 240 }, (_, i) => i / 4);
const rank = (pct, w) => RANK[gradeTradeHistorySide(pct, w).grade];

describe("gradeTradeHistorySide is monotone", () => {
  it("a bigger win never earns a lower letter", () => {
    const r = SWEEP.map((p) => rank(p, true));
    expect(r).toEqual([...r].sort((a, b) => a - b));
  });
  it("a bigger overpay never earns a higher letter", () => {
    const r = SWEEP.map((p) => rank(p, false));
    expect(r).toEqual([...r].sort((a, b) => b - a));
  });
  it("a winner never grades below the loser at the same margin", () => {
    for (const p of SWEEP) expect(rank(p, true)).toBeGreaterThanOrEqual(rank(p, false));
  });
});
