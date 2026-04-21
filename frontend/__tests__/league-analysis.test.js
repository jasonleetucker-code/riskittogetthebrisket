/**
 * Tests for lib/league-analysis.js — trade-history aggregation across
 * renamed teams and orphan-roster takeovers.
 */
import { describe, expect, it } from "vitest";
import {
  analyzeSleeperTradeHistory,
  analyzeTradeTendencies,
  buildSleeperIdentityMaps,
} from "@/lib/league-analysis";

// Fake dynasty rows — just enough to resolve a single player value so
// the weighted totals are finite and comparable.
const rows = [
  {
    name: "Test Star",
    pos: "QB",
    values: { full: 5000, raw: 5000 },
  },
  {
    name: "Test Mid",
    pos: "RB",
    values: { full: 2000, raw: 2000 },
  },
];

function mkTrade({ week = 1, offsetDaysAgo = 1, sides }) {
  return {
    week,
    timestamp: Date.now() - offsetDaysAgo * 24 * 60 * 60 * 1000,
    sides,
  };
}

describe("buildSleeperIdentityMaps", () => {
  it("indexes teams by ownerId and roster_id", () => {
    const maps = buildSleeperIdentityMaps([
      { name: "Current Alpha", roster_id: 1, ownerId: "user-a" },
      { name: "Current Beta", roster_id: 2, ownerId: "user-b" },
    ]);
    expect(maps.byOwner.get("user-a")).toBe("Current Alpha");
    expect(maps.byOwner.get("user-b")).toBe("Current Beta");
    expect(maps.byRoster.get("1")).toBe("Current Alpha");
    expect(maps.byRoster.get("2")).toBe("Current Beta");
  });

  it("tolerates missing ownerId fields", () => {
    const maps = buildSleeperIdentityMaps([{ name: "Legacy", roster_id: 3 }]);
    expect(maps.byOwner.size).toBe(0);
    expect(maps.byRoster.get("3")).toBe("Legacy");
  });
});

describe("analyzeSleeperTradeHistory — ownerId aggregation", () => {
  it("unifies trades from a renamed team under the current name", () => {
    const rawData = {
      sleeper: {
        teams: [
          { name: "Current Alpha", roster_id: 1, ownerId: "user-a" },
          { name: "Current Beta", roster_id: 2, ownerId: "user-b" },
        ],
        trades: [
          // Historical trade: team name was "Old Alpha" at the time
          mkTrade({
            offsetDaysAgo: 60,
            sides: [
              { team: "Old Alpha", rosterId: 1, ownerId: "user-a", got: ["Test Star"], gave: [] },
              { team: "Current Beta", rosterId: 2, ownerId: "user-b", got: ["Test Mid"], gave: [] },
            ],
          }),
          // Recent trade: same owner, current team name
          mkTrade({
            offsetDaysAgo: 2,
            sides: [
              { team: "Current Alpha", rosterId: 1, ownerId: "user-a", got: ["Test Mid"], gave: [] },
              { team: "Current Beta", rosterId: 2, ownerId: "user-b", got: ["Test Star"], gave: [] },
            ],
          }),
        ],
      },
    };

    const { teamScores } = analyzeSleeperTradeHistory(rawData, rows);
    const buckets = Object.values(teamScores);
    // Two unique humans, two unique buckets — NOT three.
    expect(buckets).toHaveLength(2);
    const alpha = buckets.find((b) => b.displayName === "Current Alpha");
    const beta = buckets.find((b) => b.displayName === "Current Beta");
    expect(alpha).toBeDefined();
    expect(beta).toBeDefined();
    expect(alpha.trades).toBe(2);
    expect(beta.trades).toBe(2);
  });

  it("splits trades when the same rosterId is held by different owners (orphan takeover)", () => {
    // rosterId 5 was "user-prev" last season and got handed off to
    // "user-new" this season.  Current team is labeled under
    // user-new's display name.  Aggregation must stay split.
    const rawData = {
      sleeper: {
        teams: [
          { name: "New Manager", roster_id: 5, ownerId: "user-new" },
          { name: "Opponent", roster_id: 6, ownerId: "user-opponent" },
        ],
        trades: [
          mkTrade({
            offsetDaysAgo: 90,
            sides: [
              { team: "Previous Manager", rosterId: 5, ownerId: "user-prev", got: ["Test Star"], gave: [] },
              { team: "Opponent", rosterId: 6, ownerId: "user-opponent", got: ["Test Mid"], gave: [] },
            ],
          }),
          mkTrade({
            offsetDaysAgo: 5,
            sides: [
              { team: "New Manager", rosterId: 5, ownerId: "user-new", got: ["Test Mid"], gave: [] },
              { team: "Opponent", rosterId: 6, ownerId: "user-opponent", got: ["Test Star"], gave: [] },
            ],
          }),
        ],
      },
    };

    const { teamScores } = analyzeSleeperTradeHistory(rawData, rows);
    const buckets = Object.values(teamScores);
    // 3 buckets: previous manager, new manager, opponent
    expect(buckets).toHaveLength(3);
    const prev = buckets.find((b) => b.ownerId === "user-prev");
    const next = buckets.find((b) => b.ownerId === "user-new");
    expect(prev).toBeDefined();
    expect(next).toBeDefined();
    expect(prev.trades).toBe(1);
    expect(next.trades).toBe(1);
    // Previous manager keeps its historical name since we don't
    // have a current team registered under user-prev.
    expect(prev.displayName).toBe("Previous Manager");
    expect(next.displayName).toBe("New Manager");
  });

  it("falls back to rosterId when ownerId is absent (legacy data)", () => {
    // Older scraper output did not record ownerId — rosterId
    // grouping is the best-available aggregation in that case.
    const rawData = {
      sleeper: {
        teams: [
          { name: "Current Alpha", roster_id: 1 },
          { name: "Current Beta", roster_id: 2 },
        ],
        trades: [
          mkTrade({
            offsetDaysAgo: 60,
            sides: [
              { team: "Old Alpha", rosterId: 1, got: ["Test Star"], gave: [] },
              { team: "Current Beta", rosterId: 2, got: ["Test Mid"], gave: [] },
            ],
          }),
          mkTrade({
            offsetDaysAgo: 2,
            sides: [
              { team: "Current Alpha", rosterId: 1, got: ["Test Mid"], gave: [] },
              { team: "Current Beta", rosterId: 2, got: ["Test Star"], gave: [] },
            ],
          }),
        ],
      },
    };

    const { teamScores } = analyzeSleeperTradeHistory(rawData, rows);
    const buckets = Object.values(teamScores);
    expect(buckets).toHaveLength(2);
    const alpha = buckets.find((b) => b.displayName === "Current Alpha");
    expect(alpha).toBeDefined();
    expect(alpha.trades).toBe(2);
  });
});

describe("analyzeSleeperTradeHistory — unique keys across orphan takeovers", () => {
  it("keeps teamScores keys unique when two owners share a rosterId", () => {
    // Reproduces the React key collision case: same rosterId (5)
    // held by two different humans across seasons.  The aggregation
    // keys must be distinct so the Winners/Losers card can safely
    // use `Object.entries(teamScores)[i][0]` as the React key.
    const rawData = {
      sleeper: {
        teams: [
          { name: "New Manager", roster_id: 5, ownerId: "user-new" },
          { name: "Opponent", roster_id: 6, ownerId: "user-opponent" },
        ],
        trades: [
          mkTrade({
            offsetDaysAgo: 90,
            sides: [
              { team: "Previous Manager", rosterId: 5, ownerId: "user-prev", got: ["Test Star"], gave: [] },
              { team: "Opponent", rosterId: 6, ownerId: "user-opponent", got: ["Test Mid"], gave: [] },
            ],
          }),
          mkTrade({
            offsetDaysAgo: 5,
            sides: [
              { team: "New Manager", rosterId: 5, ownerId: "user-new", got: ["Test Mid"], gave: [] },
              { team: "Opponent", rosterId: 6, ownerId: "user-opponent", got: ["Test Star"], gave: [] },
            ],
          }),
        ],
      },
    };

    const { teamScores } = analyzeSleeperTradeHistory(rawData, rows);
    const keys = Object.keys(teamScores);
    expect(new Set(keys).size).toBe(keys.length); // no dupes
    expect(keys).toContain("oid:user-prev");
    expect(keys).toContain("oid:user-new");
    expect(keys).toContain("oid:user-opponent");
  });
});

describe("analyzeSleeperTradeHistory — side shape (gave + got + net)", () => {
  it("stamps got, gave, gotValue, gaveValue, netValue, pctGap, grade per side", () => {
    const rawData = {
      sleeper: {
        teams: [
          { name: "Team A", roster_id: 1, ownerId: "user-a" },
          { name: "Team B", roster_id: 2, ownerId: "user-b" },
        ],
        trades: [
          mkTrade({
            offsetDaysAgo: 1,
            sides: [
              { team: "Team A", rosterId: 1, ownerId: "user-a", got: ["Test Star"], gave: ["Test Mid"] },
              { team: "Team B", rosterId: 2, ownerId: "user-b", got: ["Test Mid"], gave: ["Test Star"] },
            ],
          }),
        ],
      },
    };

    const { analyzed } = analyzeSleeperTradeHistory(rawData, rows);
    expect(analyzed).toHaveLength(1);
    const [a, b] = analyzed[0].sides;

    // Team A got Test Star (5000) for Test Mid (2000) — net positive.
    expect(a.team).toBe("Team A");
    expect(a.got.map((i) => i.name)).toEqual(["Test Star"]);
    expect(a.gave.map((i) => i.name)).toEqual(["Test Mid"]);
    expect(a.gotValue).toBe(5000);
    expect(a.gaveValue).toBe(2000);
    expect(a.netValue).toBe(3000);
    expect(a.pctGap).toBeGreaterThan(0);
    expect(a.grade).toBeDefined();
    expect(a.grade.grade).toMatch(/^A/); // A / A+ / A- for winners

    // Team B is the mirror: got Test Mid, gave Test Star.
    expect(b.netValue).toBe(-3000);
    expect(b.pctGap).toBeLessThan(0);
    // Loser's pctGap magnitude equals winner's — symmetric 2-team trade.
    expect(Math.abs(a.pctGap)).toBeCloseTo(Math.abs(b.pctGap), 5);
  });

  it("grades each side on its own net, not on absolute received total (3-team trade)", () => {
    // Scenario mirroring the screenshot on PR #190:
    //   - Big-pile team gives 3 players worth (2000+2000+5000=9000), gets
    //     one star worth 5000.  Net = −4000, they overpaid.
    //   - Small-pile team gives one star (5000), gets 3 pieces (9000).
    //     Net = +4000, they made out.
    //   - Third team swaps 5000 for 5000.  Net = 0, fair.
    // Old grading (by absolute received) would flag whoever received
    // the fewest pieces as "F Fleeced" even when their outgoing stack
    // was smaller.  New grading should call the small-pile team the
    // winner and the big-pile team the loser.
    const rawData = {
      sleeper: {
        teams: [
          { name: "Big Pile Gave", roster_id: 1, ownerId: "user-a" },
          { name: "Small Pile Got", roster_id: 2, ownerId: "user-b" },
          { name: "Even Swap", roster_id: 3, ownerId: "user-c" },
        ],
        trades: [
          mkTrade({
            offsetDaysAgo: 1,
            sides: [
              {
                team: "Big Pile Gave",
                rosterId: 1,
                ownerId: "user-a",
                // gave 3 pieces (2000+2000+5000 = 9000), got 1 star
                got: ["Test Star"],
                gave: ["Test Mid", "Test Mid", "Test Star"],
              },
              {
                team: "Small Pile Got",
                rosterId: 2,
                ownerId: "user-b",
                // gave 1 star (5000), got 3 pieces (9000)
                got: ["Test Mid", "Test Mid", "Test Star"],
                gave: ["Test Star"],
              },
              {
                team: "Even Swap",
                rosterId: 3,
                ownerId: "user-c",
                got: ["Test Star"],
                gave: ["Test Star"],
              },
            ],
          }),
        ],
      },
    };

    const { analyzed } = analyzeSleeperTradeHistory(rawData, rows);
    expect(analyzed).toHaveLength(1);
    const [bigPile, smallPile, evenSwap] = analyzed[0].sides;

    // Big-pile team OVERPAID despite receiving a high-value piece.
    expect(bigPile.netValue).toBeLessThan(0);
    expect(bigPile.pctGap).toBeLessThan(-3);

    // Small-pile team WON despite receiving cheaper pieces than the
    // old absolute-received math would have scored highest.
    expect(smallPile.netValue).toBeGreaterThan(0);
    expect(smallPile.pctGap).toBeGreaterThan(3);

    // Even-swap team grades as fair.
    expect(evenSwap.netValue).toBe(0);
    expect(Math.abs(evenSwap.pctGap)).toBeLessThan(3);

    // Overall headline winner should be the small-pile team.
    expect(analyzed[0].winner.team).toBe("Small Pile Got");
    expect(analyzed[0].loser.team).toBe("Big Pile Gave");
  });

  it("anchors the headline to the biggest-magnitude side, not the winner", () => {
    // 3-team trade where the positive net is split across two small
    // winners (<3% each) but one side takes a big loss.  The headline
    // must surface the loser's 'overpaid by N%' rather than rounding
    // to 'Fair trade', so the card stays consistent with per-side
    // grades and W/L credit.
    const rawData = {
      sleeper: {
        teams: [
          { name: "Small Winner A", roster_id: 1, ownerId: "user-a" },
          { name: "Small Winner B", roster_id: 2, ownerId: "user-b" },
          { name: "Big Loser", roster_id: 3, ownerId: "user-c" },
        ],
        trades: [
          mkTrade({
            offsetDaysAgo: 1,
            sides: [
              // Two teams each swap star-for-star with a tiny top-up,
              // coming out slightly ahead.
              { team: "Small Winner A", rosterId: 1, ownerId: "user-a", got: ["Test Star", "Test Mid"], gave: ["Test Star"] },
              { team: "Small Winner B", rosterId: 2, ownerId: "user-b", got: ["Test Star", "Test Mid"], gave: ["Test Star"] },
              // Third team sends two stars, gets nothing back.
              { team: "Big Loser", rosterId: 3, ownerId: "user-c", got: [], gave: ["Test Star", "Test Star"] },
            ],
          }),
        ],
      },
    };

    const { analyzed } = analyzeSleeperTradeHistory(rawData, rows);
    expect(analyzed).toHaveLength(1);
    const a = analyzed[0];

    // The big loser takes a 100% pctGap on the magnitude side (−100%).
    const bigLoser = a.sides.find((s) => s.team === "Big Loser");
    expect(bigLoser).toBeDefined();
    expect(bigLoser.pctGap).toBeLessThan(-3);

    // Headline should name the biggest-magnitude side (the loser),
    // with the "overpaid" direction and their magnitude.
    expect(a.headlineSide?.team).toBe("Big Loser");
    expect(a.headlineDirection).toBe("overpaid");
    expect(a.pctGap).toBeGreaterThanOrEqual(3);
  });

  it("labels a balanced trade as Fair on both sides and skips W/L credit", () => {
    const rawData = {
      sleeper: {
        teams: [
          { name: "Team A", roster_id: 1, ownerId: "user-a" },
          { name: "Team B", roster_id: 2, ownerId: "user-b" },
        ],
        trades: [
          mkTrade({
            offsetDaysAgo: 1,
            sides: [
              { team: "Team A", rosterId: 1, ownerId: "user-a", got: ["Test Star"], gave: ["Test Star"] },
              { team: "Team B", rosterId: 2, ownerId: "user-b", got: ["Test Star"], gave: ["Test Star"] },
            ],
          }),
        ],
      },
    };

    const { analyzed, teamScores } = analyzeSleeperTradeHistory(rawData, rows);
    expect(analyzed[0].sides.every((s) => s.pctGap === 0)).toBe(true);
    expect(analyzed[0].sides.every((s) => s.grade.grade === "A")).toBe(true);
    // No one wins or loses a fair trade.
    for (const bucket of Object.values(teamScores)) {
      expect(bucket.won).toBe(0);
      expect(bucket.lost).toBe(0);
    }
  });
});

describe("analyzeTradeTendencies — ownerId aggregation", () => {
  it("splits orphan takeovers by owner", () => {
    const rawData = {
      sleeper: {
        teams: [
          { name: "New Manager", roster_id: 5, ownerId: "user-new" },
          { name: "Opponent", roster_id: 6, ownerId: "user-opponent" },
        ],
        positions: { "Test Star": "QB", "Test Mid": "RB" },
        trades: [
          mkTrade({
            offsetDaysAgo: 90,
            sides: [
              { team: "Previous Manager", rosterId: 5, ownerId: "user-prev", got: ["Test Star"], gave: ["Test Mid"] },
              { team: "Opponent", rosterId: 6, ownerId: "user-opponent", got: ["Test Mid"], gave: ["Test Star"] },
            ],
          }),
          mkTrade({
            offsetDaysAgo: 5,
            sides: [
              { team: "New Manager", rosterId: 5, ownerId: "user-new", got: ["Test Mid"], gave: ["Test Star"] },
              { team: "Opponent", rosterId: 6, ownerId: "user-opponent", got: ["Test Star"], gave: ["Test Mid"] },
            ],
          }),
        ],
      },
    };

    const tendencies = analyzeTradeTendencies(rawData, rows);
    const managers = tendencies.map((t) => t.manager).sort();
    // 3 managers: user-prev under historical name, user-new under
    // current name, user-opponent under current name.
    expect(managers).toEqual(["New Manager", "Opponent", "Previous Manager"]);
  });
});
