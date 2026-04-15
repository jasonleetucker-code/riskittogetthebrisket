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
