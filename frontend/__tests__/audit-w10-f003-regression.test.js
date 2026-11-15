/**
 * W10-F003 (owner decision 2026-11-07): the legacy per-player "Next Best
 * Targets" recommender is RETIRED; Perfect Draft (`lib/perfect-draft.js` +
 * `PerfectDraftPanel`, flag `perfect_draft`) is the single recommendation
 * experience on /draft.
 *
 * Invariants pinned here:
 *   - one recommender: no legacy panel/function remains, Perfect Draft is mounted;
 *   - flag off shows a notice (PerfectDraftPanel.test.jsx), never an empty
 *     "no recommendations" claim;
 *   - Perfect Draft plans respect budget, availability and roster capacity
 *     across realistic scenarios (further coverage: perfect-draft.test.js
 *     "plan invariants", "live draft updates", "live draft progress").
 *
 * Pure functions and source-shape reads only: no network, no rendering.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import * as draftLogic from "../lib/draft-logic.js";
import { optimizeDraft } from "../lib/perfect-draft.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const page = readFileSync(resolve(HERE, "../app/draft/page.jsx"), "utf-8");

describe("W10-F003: Perfect Draft is the single recommender", () => {
  it("the legacy Next Best Targets function is gone", () => {
    expect(draftLogic.nextBestTargets).toBeUndefined();
  });

  it("/draft no longer renders or imports the legacy panel", () => {
    expect(page).not.toMatch(/NextBestTargets|nextBestTargets/);
    expect(page).not.toMatch(/Next Best Targets<\/h3>/);
  });

  it("/draft mounts PerfectDraftPanel", () => {
    expect(page).toMatch(/<PerfectDraftPanel\b/);
    expect(typeof optimizeDraft).toBe("function");
  });
});

const cut = (i, cost) => ({
  playerId: `cut-${i}`,
  name: `Cut ${i}`,
  position: "WR",
  effectiveCutCost: cost,
  valueBasis: "board",
});

function pool(drafted = []) {
  return Array.from({ length: 16 }, (_, i) => ({
    id: `r${i}`,
    name: `Rookie ${i}`,
    pos: i % 2 ? "WR" : "RB",
    boardValue: 4000 - i * 150,
    price: 3 + i * 3,
    drafted: drafted.includes(`r${i}`),
  }));
}

describe("W10-F003: Perfect Draft plans respect budget, availability and capacity", () => {
  const scenarios = [];
  for (const budget of [0, 25, 60, 150]) {
    for (const openRosterSpots of [0, 2, 5]) {
      scenarios.push({ budget, openRosterSpots });
    }
  }

  for (const { budget, openRosterSpots } of scenarios) {
    it(`budget $${budget}, ${openRosterSpots} open spots`, () => {
      const cutLadder = [cut(0, 100), cut(1, 200), cut(2, 300)];
      const drafted = ["r0", "r1"];
      const out = optimizeDraft({
        budget,
        openRosterSpots,
        cutLadder,
        waiverValues: {},
        rookies: pool(drafted),
      });
      const ids = out.plan.players.map((p) => p.id);
      for (const d of drafted) expect(ids).not.toContain(d);
      expect(out.plan.spend).toBeLessThanOrEqual(budget);
      expect(out.plan.k).toBeLessThanOrEqual(openRosterSpots + cutLadder.length);
      expect(new Set(ids).size).toBe(ids.length);
    });
  }
});
