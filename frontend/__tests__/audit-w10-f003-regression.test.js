/**
 * CW-40 / master-site-audit W10-F003 regression evidence (P1).
 *
 * Finding: "no perfect-draft optimizer; the only recommender is an unconstrained
 * per-player sort whose EV is zero for every contested player, so the panel is
 * EMPTY at budget advantage 1.0-3.0".
 *
 * Adjudication (docs/audits/remediation_2026-11-06/CW40_P1_OPEN_ADJUDICATION.md):
 * PARTIAL.
 *   - "no optimizer": CLOSED. `lib/perfect-draft.js::optimizeDraft` exists and
 *     `PerfectDraftPanel` is mounted on /draft.
 *   - "NBT panel empty at BA >= 1": STILL TRUE. `nextBestTargets` is unchanged in
 *     the EV model; the only repair is that a user-tagged target bypasses the
 *     `ev <= 0` filter and the empty state tells the user to tag one.
 *
 * Pure functions and source-shape reads only: no network, no rendering.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  TAG_TARGET,
  computeDraftStats,
  createDefaultWorkspace,
  nextBestTargets,
} from "../lib/draft-logic.js";
import { optimizeDraft } from "../lib/perfect-draft.js";

const HERE = dirname(fileURLToPath(import.meta.url));

function twoTeamWorkspace(myBudget, rivalBudget, tags = {}) {
  const ws = createDefaultWorkspace();
  return {
    ...ws,
    settings: { ...ws.settings, myTeamIdx: 0 },
    teams: [
      { name: "Me", initialBudget: myBudget, feedBudget: myBudget },
      { name: "Rival", initialBudget: rivalBudget, feedBudget: rivalBudget },
    ],
    players: [
      { id: "a", rank: 1, name: "A", preDraft: 60 },
      { id: "b", rank: 2, name: "B", preDraft: 35 },
      { id: "c", rank: 3, name: "C", preDraft: 30 },
    ],
    picks: [],
    tags,
    targetBoard: [],
    parSheet: [],
    nominations: [],
  };
}

describe("W10-F003 closed half: a budget-constrained optimizer exists and is mounted", () => {
  it("lib/perfect-draft.js exports optimizeDraft", () => {
    expect(typeof optimizeDraft).toBe("function");
  });

  it("/draft mounts PerfectDraftPanel", () => {
    const page = readFileSync(resolve(HERE, "../app/draft/page.jsx"), "utf-8");
    expect(page).toMatch(/<PerfectDraftPanel\b/);
  });
});

describe("W10-F003 residual half: Next Best Targets EV is zero for contested players", () => {
  it("is non-empty when the user is poorer than the field (the one populated regime)", () => {
    const stats = computeDraftStats(twoTeamWorkspace(100, 300));
    expect(stats.budgetAdvantage).toBeCloseTo(100 / 300, 2);
    expect(nextBestTargets(stats, { limit: 10 }).length).toBeGreaterThan(0);
  });

  it("a user-tagged target bypasses the ev<=0 filter (the shipped mitigation)", () => {
    const stats = computeDraftStats(twoTeamWorkspace(150, 100, { a: TAG_TARGET }));
    const top = nextBestTargets(stats, { limit: 10 });
    expect(top.map((t) => t.player.id)).toContain("a");
  });

  // Measured on current main: BA 1.0 / 1.1 / 1.5 / 3.0 -> 0 rows, and every
  // enriched player has myWinningBid = inflatedFair + 1 (surplus 0). It flips
  // (and this strict `it.fails` goes red) when the EV model gives an untagged
  // contested player a positive score.
  it.fails("W10-F003: untagged panel is non-empty at budget advantage 1.5", () => {
    const stats = computeDraftStats(twoTeamWorkspace(150, 100));
    expect(stats.budgetAdvantage).toBeCloseTo(1.5, 2);
    expect(nextBestTargets(stats, { limit: 10 }).length).toBeGreaterThan(0);
  });
});
