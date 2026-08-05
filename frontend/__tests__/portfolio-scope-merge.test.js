/**
 * The portfolio panel must not add up two different asset scopes.
 *
 * Audit finding W20-F004. `PortfolioSummary` took `totalValue` and
 * `byPosition` from the SERVER (`/api/terminal`, which excludes picks —
 * documented in `src/api/terminal.py`) and left `starterValue` /
 * `benchValue` / `pickValue` on the LOCAL object (which includes them).
 * For one real team it rendered:
 *
 *   Total Value 171,495
 *   Starters 97,497 · Bench 73,998 · Picks 143,067   → 314,562
 *
 * a legend 1.83x its own stated total, with the PICK row of the
 * positional stack skipped because the server reports count 0.
 *
 * The server's total is exactly the lineup-eligible scope — on the live
 * league serverTotal == starterValue + benchValue to the unit — so the
 * repair composes the two scopes instead of overriding one with the
 * other.
 */
import { describe, expect, it } from "vitest";
import { composePortfolio } from "@/lib/portfolio-insights";

/** The measured live numbers for the team in the finding. */
const SERVER = {
  totalValue: 171495,
  byPosition: {
    QB: { count: 3, value: 50000, pct: 29.2 },
    WR: { count: 8, value: 121495, pct: 70.8 },
    PICK: { count: 0, value: 0, pct: 0 },
  },
  byAge: {
    young: { count: 6, value: 100000, pct: 58.3 },
    prime: { count: 5, value: 71495, pct: 41.7 },
    unknown: { count: 0, value: 0, pct: 0 },
  },
  volExposure: {
    low: { count: 11, value: 171495, pct: 100 },
    unknown: { count: 0, value: 0, pct: 0 },
  },
  medianAge: 24,
};

const LOCAL = {
  totalValue: 314562,
  starterValue: 97497,
  benchValue: 73998,
  starterCount: 9,
  benchCount: 2,
  pickValue: 143067,
  pickCount: 24,
  byPosition: { QB: { count: 3, value: 50000, pct: 15.9 } },
  byAge: { unknown: { count: 24, value: 143067, pct: 45.5 } },
  volExposure: { unknown: { count: 24, value: 143067, pct: 45.5 } },
  medianAge: 24,
};

describe("portfolio scope composition", () => {
  it("Total Value equals Starters + Bench + Picks", () => {
    const p = composePortfolio(SERVER, LOCAL);
    expect(p.totalValue).toBe(p.starterValue + p.benchValue + p.pickValue);
    expect(p.totalValue).toBe(314562);
  });

  it("does not render the player-only total beside a picks-inclusive legend", () => {
    const p = composePortfolio(SERVER, LOCAL);
    expect(p.totalValue).not.toBe(SERVER.totalValue);
  });

  it("draws the PICK row of the positional stack", () => {
    const p = composePortfolio(SERVER, LOCAL);
    expect(p.byPosition.PICK.count).toBe(24);
    expect(p.byPosition.PICK.value).toBe(143067);
    expect(p.byPosition.PICK.pct).toBeGreaterThan(0);
  });

  it("renormalises every percentage against the composed total", () => {
    const p = composePortfolio(SERVER, LOCAL);
    const sum = Object.values(p.byPosition).reduce((a, b) => a + b.pct, 0);
    expect(sum).toBeGreaterThan(99);
    expect(sum).toBeLessThan(101);
  });

  it("keeps the server's PLAYER numbers verbatim", () => {
    const p = composePortfolio(SERVER, LOCAL);
    expect(p.byPosition.QB.value).toBe(50000);
    expect(p.byPosition.WR.value).toBe(121495);
    expect(p.medianAge).toBe(24);
  });

  it("puts picks in the age and volatility buckets that mean 'unknown'", () => {
    // A pick has no age and no volatility history; anything else would
    // be a made-up measurement.
    const p = composePortfolio(SERVER, LOCAL);
    expect(p.byAge.unknown.value).toBe(143067);
    expect(p.volExposure.unknown.value).toBe(143067);
  });

  it("is a no-op when the server payload is absent", () => {
    expect(composePortfolio(null, LOCAL)).toBe(LOCAL);
  });

  it("falls back to local when the server sent no usable total", () => {
    expect(composePortfolio({ totalValue: null }, LOCAL)).toBe(LOCAL);
  });

  it("returns null without a local portfolio", () => {
    expect(composePortfolio(SERVER, null)).toBe(null);
  });

  it("does not mutate the server payload", () => {
    composePortfolio(SERVER, LOCAL);
    expect(SERVER.byPosition.PICK.count).toBe(0);
    expect(SERVER.totalValue).toBe(171495);
  });

  it("a team with no picks reads exactly as the server computed it", () => {
    const local = { ...LOCAL, pickValue: 0, pickCount: 0, starterValue: 97497, benchValue: 73998 };
    const p = composePortfolio(SERVER, local);
    expect(p.totalValue).toBe(171495);
    expect(p.byPosition.PICK.count).toBe(0);
  });
});
