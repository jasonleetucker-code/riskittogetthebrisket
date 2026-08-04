/**
 * Frontend half of the trade-grading parity test (math audit finding C3).
 *
 * Twin of `tests/public_league/test_trade_grade_parity.py`. Both halves
 * assert against ONE fixture,
 * `tests/fixtures/trade_grade_parity_cases.json` — see that Python
 * file's module docstring for the full rationale. The short version:
 *
 *   - `frontend/lib/league-analysis.js` grades the private /trades page.
 *   - `src/public_league/trade_grading.py` grades the public /league
 *     activity timeline, server-side, and cannot import this file.
 *
 * Until 2026-08-04 the public half raised each asset to 1.65 and
 * compared side totals while this half took a linear net plus the KTC
 * value adjustment — and both fed the same 3/8/15/25/40 band table, so
 * one trade could be a "Good win (A-)" on one page and a "Clear win
 * (B+)" on the other. Nothing checked that they agreed until this pair
 * of files.
 *
 * NEITHER half may hardcode expectations of its own. The fixture is the
 * single source of truth; if the implementations disagree, exactly one
 * suite goes red against a shared, human-authored statement of intent.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import {
  computeTradeVANet,
  gradeTradeHistorySide,
  gradeTradeSide,
  gradeTradeSides,
  sanitizeSideValues,
} from "@/lib/league-analysis";

const REPO_ROOT = path.resolve(__dirname, "../..");
const FIXTURE_PATH = path.join(
  REPO_ROOT,
  "tests",
  "fixtures",
  "trade_grade_parity_cases.json",
);
const FIXTURE = JSON.parse(fs.readFileSync(FIXTURE_PATH, "utf8"));

// How far below a cut point we probe for "the band below owns this".
const EPSILON = 1e-9;

describe("trade-grade parity fixture integrity", () => {
  it("loads a non-trivial shared fixture", () => {
    expect(FIXTURE.bandCases.length).toBeGreaterThanOrEqual(20);
    expect(FIXTURE.tradeCases.length).toBeGreaterThanOrEqual(5);
    expect(FIXTURE.vaEngineCases.cases.length).toBeGreaterThanOrEqual(8);
  });

  it("has unique case ids", () => {
    const ids = [
      ...FIXTURE.bandCases.map((c) => c.id),
      ...FIXTURE.tradeCases.map((c) => c.id),
      ...FIXTURE.vaEngineCases.cases.map((c) => c.id),
    ];
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("band table matches the shared fixture", () => {
  for (const [role, isWinner] of [
    ["winner", true],
    ["loser", false],
  ]) {
    it(`${role} ladder, at each cut point and just below it`, () => {
      const bands = FIXTURE.bands[role];
      bands.forEach((band, i) => {
        const at = gradeTradeHistorySide(band.atLeast, isWinner);
        expect([at.grade, at.label], `${role} band at ${band.atLeast}%`).toEqual([
          band.grade,
          band.label,
        ]);
        if (i === 0) return;
        const below = gradeTradeHistorySide(band.atLeast - EPSILON, isWinner);
        const prev = bands[i - 1];
        expect(
          [below.grade, below.label],
          `${role} band just below ${band.atLeast}%`,
        ).toEqual([prev.grade, prev.label]);
      });
    });
  }
});

describe("gradeTradeSide — ratio arithmetic with the VA supplied", () => {
  for (const c of FIXTURE.bandCases) {
    it(`${c.id}: ${c.why}`, () => {
      const result = gradeTradeSide(
        sanitizeSideValues(c.got),
        sanitizeSideValues(c.gave),
        c.vaNet,
      );
      expect(result.pctGap).toBeCloseTo(c.pctGap, 9);
      expect(result.grade.grade).toBe(c.grade);
      expect(result.grade.label).toBe(c.label);
    });
  }
});

describe("gradeTradeSides — whole trade, VA computed", () => {
  for (const c of FIXTURE.tradeCases) {
    it(`${c.id}: ${c.why}`, () => {
      const graded = gradeTradeSides(c.sides);
      expect(graded).toHaveLength(c.expected.length);
      graded.forEach((result, i) => {
        const expected = c.expected[i];
        expect(result.vaNet, `side ${i} vaNet`).toBeCloseTo(expected.vaNet, 9);
        expect(result.pctGap, `side ${i} pctGap`).toBeCloseTo(expected.pctGap, 9);
        expect(result.grade.grade, `side ${i} grade`).toBe(expected.grade);
        expect(result.grade.label, `side ${i} label`).toBe(expected.label);
      });
    });
  }
});

describe("KTC value adjustment against keeptradecut.com captures", () => {
  const { tolerance, cases } = FIXTURE.vaEngineCases;
  for (const c of cases) {
    it(`${c.id}: ${c.why}`, () => {
      const got = computeTradeVANet(
        sanitizeSideValues(c.got),
        sanitizeSideValues(c.gave),
      );
      expect(Math.abs(got - c.vaNet)).toBeLessThanOrEqual(tolerance);
    });
  }

  it("is antisymmetric — swapping got and gave flips the sign", () => {
    // Otherwise a two-team trade could grade both sides as winners.
    for (const c of cases) {
      const forward = computeTradeVANet(
        sanitizeSideValues(c.got),
        sanitizeSideValues(c.gave),
      );
      const reverse = computeTradeVANet(
        sanitizeSideValues(c.gave),
        sanitizeSideValues(c.got),
      );
      expect(forward, c.id).toBeCloseTo(-reverse, 9);
    }
  });
});
