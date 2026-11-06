/**
 * W10-F001 re-test — no surfaced bid ever exceeds the team's remaining budget.
 *
 * Audit finding: with $4 left the /draft board said "Win at $69 / Max bid $80".
 * Owners: lib/draft-logic.js (computeDraftStats / bidStatus) and
 * lib/perfect-draft.js (computeMaxBid / evaluateBid).
 */
import { describe, expect, it } from "vitest";
import {
  bidStatus,
  computeDraftStats,
  createDefaultWorkspace,
  recordPick,
} from "@/lib/draft-logic";
import { computeMaxBid, evaluateBid } from "@/lib/perfect-draft";
import {
  draftCapitalBudgetRows,
  draftCapitalBudgetsUnavailableReason,
} from "@/lib/draft-capital-budgets";

function wsWithMyBudget(remaining) {
  let ws = createDefaultWorkspace();
  const idx = ws.settings.myTeamIdx ?? 0;
  ws = {
    ...ws,
    teams: ws.teams.map((t, i) => (i === idx ? { ...t, initialBudget: remaining } : t)),
  };
  return { ws, idx };
}

const surfaced = (p) => [p.myMaxBid, p.myWinningBid, p.bayesianWinningBid, p.enforceUpTo];

describe("draft-logic bids respect my remaining budget", () => {
  for (const remaining of [4, 1, 25, 120]) {
    it(`no surfaced bid exceeds $${remaining} remaining`, () => {
      const { ws } = wsWithMyBudget(remaining);
      const stats = computeDraftStats(ws);
      expect(stats.myRemaining).toBe(remaining);
      for (const p of stats.enrichedPlayers) {
        for (const v of surfaced(p)) expect(v).toBeLessThanOrEqual(remaining);
        expect(p.theoreticalMaxBid).toBeGreaterThanOrEqual(p.myMaxBid);
      }
    });
  }

  it("a $0 team gets no positive bid and the verdict is Pass", () => {
    const { ws } = wsWithMyBudget(0);
    const stats = computeDraftStats(ws);
    for (const p of stats.enrichedPlayers) {
      for (const v of surfaced(p)) expect(v).toBe(0);
      expect(bidStatus(p, 1).level).toBe("pass");
    }
  });

  it("recorded picks reduce the ceiling", () => {
    const { ws, idx } = wsWithMyBudget(100);
    const after = recordPick(ws, { playerId: ws.players[0].id, teamIdx: idx, amount: 97 });
    const stats = computeDraftStats(after);
    expect(stats.myRemaining).toBe(3);
    for (const p of stats.enrichedPlayers) {
      for (const v of surfaced(p)) expect(v).toBeLessThanOrEqual(3);
    }
  });

  it("an unaffordable bid is never 'Push up'", () => {
    const { ws } = wsWithMyBudget(4);
    const stats = computeDraftStats(ws);
    const p = stats.enrichedPlayers.find((x) => x.theoreticalMaxBid > 24);
    expect(bidStatus(p, 24).level).toBe("pass");
  });
});

describe("perfect-draft bids respect the budget", () => {
  const rookie = (id, boardValue, price) => ({ id, name: id, pos: "WR", boardValue, price });
  const input = (budget) => ({
    budget,
    openRosterSpots: 5,
    cutLadder: [],
    waiverValues: { WR: 100 },
    rookies: [rookie("a", 5000, 10), rookie("b", 4000, 6), rookie("c", 3000, 3)],
  });

  for (const budget of [0, 1, 4, 12]) {
    it(`planMaxBid and verdict stay within $${budget}`, () => {
      for (const id of ["a", "b", "c"]) {
        const { planMaxBid } = computeMaxBid(input(budget), id);
        expect(planMaxBid).toBeLessThanOrEqual(budget);
        const v = evaluateBid(input(budget), id, budget + 50);
        expect(v.planMaxBid).toBeLessThanOrEqual(budget);
        expect(v.verdict).toBe("stop");
      }
    });
  }

  it("$0 and missing budgets never produce a positive bid or a go verdict", () => {
    for (const budget of [0, undefined, null, NaN]) {
      const { planMaxBid } = computeMaxBid(input(budget), "c");
      expect(planMaxBid).toBe(0);
      expect(evaluateBid(input(budget), "c", 1).verdict).toBe("stop");
    }
  });
});

describe("missing auction budgets are unavailable, not $0", () => {
  it("an unavailable payload refuses to yield rows", () => {
    const data = {
      teamTotalsState: "unavailable",
      teamTotalsReason: "upcoming_class_unpriced",
      teamTotals: [{ team: "A", auctionDollars: null }],
    };
    expect(draftCapitalBudgetsUnavailableReason(data)).toBe("upcoming_class_unpriced");
    expect(() => draftCapitalBudgetRows(data)).toThrow(/unavailable/i);
  });

  it("rows with no numeric budget are unavailable", () => {
    const data = { teamTotals: [{ team: "A", auctionDollars: null }] };
    expect(draftCapitalBudgetsUnavailableReason(data)).toBe("no_team_budgets");
    expect(() => draftCapitalBudgetRows(data)).toThrow();
  });
});
