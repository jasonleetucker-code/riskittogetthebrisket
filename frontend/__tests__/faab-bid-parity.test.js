/**
 * Frontend half of the FAAB baseline-bid parity test (audit finding H4).
 *
 * Twin of `tests/trade/test_faab_bid_parity.py`. Both halves assert
 * against ONE fixture, `tests/fixtures/faab_bid_parity_cases.json` — see
 * that Python file's module docstring for the full rationale. The short
 * version:
 *
 *   - `computeFaabHint` is the number the /waivers table SHOWS.
 *   - `src/trade/waiver.py::_compute_faab_bid` is the number the API
 *     RECOMMENDS.
 *
 * Same formula, two languages, and their default rounding differs
 * (`Math.round` is half-up, Python's `round` is half-to-even), so the
 * page and the API disagreed by $1 at every .5 boundary. Both sides now
 * implement half-up explicitly and scale the unrounded aggressive bid.
 *
 * NEITHER half may hardcode expectations of its own — the fixture is
 * the single source of truth.
 *
 * Note the one deliberate naming asymmetry: the fixture's `budget` is
 * "the pool this bid is sized against", which the client passes as
 * `leagueBudget` (a nominal $100 baseline) and the server passes as the
 * manager's remaining balance. Same arithmetic either way.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import { computeFaabHint } from "@/lib/waiver-logic";

const REPO_ROOT = path.resolve(__dirname, "../..");
const FIXTURE_PATH = path.join(
  REPO_ROOT,
  "tests",
  "fixtures",
  "faab_bid_parity_cases.json",
);

const FIXTURE = JSON.parse(fs.readFileSync(FIXTURE_PATH, "utf8"));

describe("computeFaabHint — shared FAAB parity fixture", () => {
  it("loads a non-trivial fixture", () => {
    expect(Array.isArray(FIXTURE.cases)).toBe(true);
    expect(FIXTURE.cases.length).toBeGreaterThanOrEqual(8);
    expect(FIXTURE.rounding.convention).toBe("half-up");
  });

  for (const c of FIXTURE.cases) {
    it(`${c.id} — ${c.why}`, () => {
      const got = computeFaabHint(c.candidateValue, {
        leagueBudget: c.budget,
        topValueInPool: c.topValueInPool,
      });
      expect(got).toEqual(c.expected);
    });
  }
});

describe("computeFaabHint — rounding rule", () => {
  it("rounds ties UP rather than to the nearest even dollar", () => {
    // 30% of $100 = $30; its 35% tier is exactly $10.50. Half-to-even
    // (what the server used to do) answers $10.
    expect(computeFaabHint(5000, { leagueBudget: 100, topValueInPool: 5000 }).lowball).toBe(11);
    // 30% of $50 = $15; its 70% tier is exactly $10.50.
    expect(computeFaabHint(5000, { leagueBudget: 50, topValueInPool: 5000 }).reasonable).toBe(11);
  });

  it("scales the unrounded aggressive bid, not the rounded one", () => {
    // share 0.5 -> 17.5% of $100 = $17.50 -> $18 aggressive, but the
    // 70% tier is 70% of 17.50 = $12.25 -> $12 (not 70% of $18 = $13).
    const hint = computeFaabHint(2500, { leagueBudget: 100, topValueInPool: 5000 });
    expect(hint.aggressive).toBe(18);
    expect(hint.reasonable).toBe(12);
  });
});
