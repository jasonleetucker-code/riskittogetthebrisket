/**
 * Owner decision 4 (2026-10-18) — a Second Opinions source calls a trade EVEN
 * when its adjusted gap is within 1% of the larger adjusted side (initial,
 * subject to validation).  The historical rule was "< 1 point", so the tally
 * called any non-zero gap a win (engine audit V6: "Side A 6 · Side B 0" on a
 * trade every lens calls even).  Independent (full-source) and modeled
 * (hybrid / fallback) tallies stay separate; a fallback never votes as
 * independent evidence.
 */
import { describe, expect, it } from "vitest";
import {
  OPINION_EVEN_TOLERANCE_PCT,
  OPINION_ORIGIN,
  OPINION_STATE,
  evaluateOpinion,
  tallyOpinions,
} from "@/lib/second-opinions";

const noAdjust = (sides) => sides.map(() => 0);
const src = (value) => ({ origin: OPINION_ORIGIN.SOURCE, value });
const fallback = (value) => ({ origin: OPINION_ORIGIN.CHASE_UPSIDE_FALLBACK, value });

describe("Second Opinions EVEN band (1% of the larger adjusted side)", () => {
  it("is the owner's initial 1%", () => {
    expect(OPINION_EVEN_TOLERANCE_PCT).toBe(1);
  });

  it("a 0.5% gap is even, not a win", () => {
    const o = evaluateOpinion([[src(10000)], [src(9950)]], noAdjust);
    expect(o.leaderIdx).toBeNull();
    expect(o.marginPct).toBe(0);
  });

  it("exactly 1% is even; just past 1% is a win", () => {
    expect(evaluateOpinion([[src(10000)], [src(9900)]], noAdjust).leaderIdx).toBeNull();
    const o = evaluateOpinion([[src(10000)], [src(9899)]], noAdjust);
    expect(o.leaderIdx).toBe(0);
    expect(o.marginPct).toBeCloseTo(1.01, 2);
  });

  it("measures on ADJUSTED totals (the band reads the larger adjusted side)", () => {
    // Raw 10000 vs 9500 (5% -> A), adjustment +450 to B -> 10000 vs 9950 (0.5%).
    const o = evaluateOpinion([[src(10000)], [src(9500)]], () => [0, 450]);
    expect(o.rawLeaderIdx).toBe(0);
    expect(o.leaderIdx).toBeNull();
  });

  it("the tally counts within-band rows as even, and fallbacks never vote independently", () => {
    const even = evaluateOpinion([[src(10000)], [src(9960)]], noAdjust);
    const win = evaluateOpinion([[src(10000)], [src(9000)]], noAdjust);
    const hybrid = evaluateOpinion([[src(10000)], [fallback(8000)]], noAdjust);
    expect(hybrid.state).toBe(OPINION_STATE.HYBRID_ESTIMATE);
    const t = tallyOpinions(
      [
        { family: "f1", key: "a", opinion: even },
        { family: "f2", key: "b", opinion: win },
        { family: "f3", key: "c", opinion: hybrid },
      ],
      2,
    );
    expect(t.independent.even).toBe(1);
    expect(t.independent.wins).toEqual([1, 0]);
    expect(t.modeled.wins).toEqual([1, 0]);
    expect(t.independent.families).toBe(2);
  });
});
