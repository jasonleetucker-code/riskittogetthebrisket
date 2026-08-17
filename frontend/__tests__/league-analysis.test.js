/**
 * Tests for lib/league-analysis.js — trade-history aggregation across
 * renamed teams and orphan-roster takeovers.
 */
import { describe, expect, it } from "vitest";
import {
  analyzeSleeperTradeHistory,
  analyzeTradeTendencies,
  buildCombinedPairTrade,
  buildSleeperIdentityMaps,
  scoreTeamTiers,
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

  it("names ONE winner — winner/loser and the grades read the same board", () => {
    // Four 4000-value pieces for one 9000 stud.  The pile side is +7000
    // on raw sums, but KTC's value adjustment hands 8622 back to the
    // consolidating side, so the canonical net is −1622 and the pile
    // side's OWN grade is "Overpay" at −9.2%.
    //
    // The alpha-weighted net disagrees, and not marginally: 4 ×
    // 4000^1.65 beats 9000^1.65 by ~165,000.  Ranking sides on
    // ``netWeighted`` — which is what ``winner``/``loser`` did until
    // the 2026-08-04 math audit (finding C3) — therefore crowned the
    // pile team while every other field on the same card, including
    // ``winnerGrade``, called them the loser.  One trade, two notions
    // of who won.
    const bigRows = [
      { name: "Test Elite", pos: "WR", values: { full: 9000, raw: 9000 } },
      { name: "Test Piece", pos: "RB", values: { full: 4000, raw: 4000 } },
    ];
    const pile = ["Test Piece", "Test Piece", "Test Piece", "Test Piece"];
    const rawData = {
      sleeper: {
        teams: [
          { name: "Pile Getter", roster_id: 1, ownerId: "user-a" },
          { name: "Stud Getter", roster_id: 2, ownerId: "user-b" },
        ],
        trades: [
          mkTrade({
            offsetDaysAgo: 1,
            sides: [
              { team: "Pile Getter", rosterId: 1, ownerId: "user-a", got: pile, gave: ["Test Elite"] },
              { team: "Stud Getter", rosterId: 2, ownerId: "user-b", got: ["Test Elite"], gave: pile },
            ],
          }),
        ],
      },
    };

    const { analyzed } = analyzeSleeperTradeHistory(rawData, bigRows);
    const a = analyzed[0];
    const [pileSide, studSide] = a.sides;

    // Per-side grades: the VA outweighs the +7000 linear edge.
    expect(pileSide.pctGap).toBeLessThan(0);
    expect(pileSide.grade.label).toBe("Overpay");
    expect(studSide.pctGap).toBeGreaterThan(0);
    expect(studSide.grade.label).toBe("Good win");
    // ...and the alpha net really does point the other way, so this
    // case can only pass if winner/loser stopped reading it.
    expect(pileSide.netWeighted).toBeGreaterThan(studSide.netWeighted);

    // The card's winner must be a side its own grade calls a winner.
    expect(a.winner.team).toBe("Stud Getter");
    expect(a.loser.team).toBe("Pile Getter");
    expect(a.winner.pctGap).toBeGreaterThan(0);
    expect(a.loser.pctGap).toBeLessThan(0);
    expect(a.winnerGrade.label).toBe("Good win");
    expect(a.loserGrade.label).toBe("Overpay");
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

describe("buildCombinedPairTrade — two-team net history", () => {
  // Mirror the "Dak" example: an asset that goes A→B, back B→A, then
  // A→B again must net to a single A→B move (odd crossings collapse to
  // one); an asset that goes there-and-back exactly once cancels.
  const tradeAtoB = mkTrade({
    offsetDaysAgo: 9,
    sides: [
      { team: "Brent", got: ["Test Mid"], gave: ["Test Star"] },
      { team: "Roy", got: ["Test Star"], gave: ["Test Mid"] },
    ],
  });
  const tradeBtoA = mkTrade({
    offsetDaysAgo: 6,
    sides: [
      { team: "Brent", got: ["Test Star"], gave: ["Test Mid"] },
      { team: "Roy", got: ["Test Mid"], gave: ["Test Star"] },
    ],
  });

  it("collapses repeated back-and-forth into a single net move", () => {
    const rawData = {
      sleeper: { trades: [tradeAtoB, tradeBtoA, { ...tradeAtoB }] },
    };
    const analysis = analyzeSleeperTradeHistory(rawData, rows);
    const combined = buildCombinedPairTrade(
      analysis,
      "Brent",
      "Roy",
      rawData,
      rows,
    );
    expect(combined).toBeTruthy();
    expect(combined.combined).toBe(true);
    expect(combined.tradeCount).toBe(3);
    const brent = combined.sides.find((s) => s.team === "Brent");
    const roy = combined.sides.find((s) => s.team === "Roy");
    // Test Star: gave, got, gave → net A→B once.  Test Mid mirrors.
    expect(brent.gave.map((i) => i.name)).toEqual(["Test Star"]);
    expect(brent.got.map((i) => i.name)).toEqual(["Test Mid"]);
    // No asset is double-counted — exactly one of each survives.
    expect(brent.gave).toHaveLength(1);
    expect(brent.got).toHaveLength(1);
    // Roy is the exact mirror of Brent.
    expect(roy.got.map((i) => i.name)).toEqual(["Test Star"]);
    expect(roy.gave.map((i) => i.name)).toEqual(["Test Mid"]);
  });

  it("returns a wash when a single there-and-back fully cancels", () => {
    const rawData = { sleeper: { trades: [tradeAtoB, tradeBtoA] } };
    const analysis = analyzeSleeperTradeHistory(rawData, rows);
    const combined = buildCombinedPairTrade(
      analysis,
      "Brent",
      "Roy",
      rawData,
      rows,
    );
    expect(combined).toEqual({
      wash: true,
      teamA: "Brent",
      teamB: "Roy",
      tradeCount: 2,
    });
  });

  it("returns null when the two teams never traded head-to-head", () => {
    const rawData = { sleeper: { trades: [tradeAtoB] } };
    const analysis = analyzeSleeperTradeHistory(rawData, rows);
    expect(
      buildCombinedPairTrade(analysis, "Brent", "Ghost", rawData, rows),
    ).toBeNull();
    // Same team twice is a no-op.
    expect(
      buildCombinedPairTrade(analysis, "Brent", "Brent", rawData, rows),
    ).toBeNull();
  });

  it("skips 3+ team trades (ambiguous A↔B flow)", () => {
    const threeWay = mkTrade({
      offsetDaysAgo: 2,
      sides: [
        { team: "Brent", got: ["Test Star"], gave: ["Test Mid"] },
        { team: "Roy", got: ["Test Mid"], gave: [] },
        { team: "Carl", got: [], gave: ["Test Star"] },
      ],
    });
    const rawData = { sleeper: { trades: [threeWay] } };
    const analysis = analyzeSleeperTradeHistory(rawData, rows);
    expect(
      buildCombinedPairTrade(analysis, "Brent", "Roy", rawData, rows),
    ).toBeNull();
  });
});

// ── Contender / rebuilder tiers ────────────────────────────────────────
//
// Regression pins for the math audit's H5(a): pick capital used to be
// counted TWICE — once inside `depthValue` (which was
// `totalValue − starterValue`, and totalValue includes picks) at +0.2,
// and once in its own term at −0.1 — so every pick dollar was a NET
// +0.1 REWARD under a docstring that called it a penalty.
//
// Numbers below are hand-computed from
// `score = 0.7 × starterValue + 0.2 × depthValue − 0.1 × pickValue`.

const tierRosterPositions = ["QB", "WR", "LB", "BN", "BN"];

// Since C2-U1 the SERVER solves each lineup and stamps it on the team;
// `scoreTeamTiers` renders that stamp rather than filling slots itself.
// These stamps are what `src/ros/lineup.py` produces for a QB/WR/LB
// lineup over each roster below — hand-written here because recomputing
// them in JavaScript is the second implementation this unit deleted.
const tierLineups = {
  "Win Now": ["Star QB", "Star WR", "Star LB"],
  Balanced: ["Solid QB", "Solid WR", "Depth LB"],
  // Only the WR slot can be filled; QB and LB go unfilled.
  "Pick Hoard": ["Lone WR"],
};

function tierStamp(name, starters) {
  const slots = ["QB", "WR", "LB"];
  return {
    available: true,
    slotSource: "sleeper_roster_positions",
    slots,
    assignments: starters.map((player, i) => ({ slotIndex: i, slot: slots[i], player })),
    starters,
    bench: [],
    unpriced: [],
    unfilledSlots: slots.slice(starters.length),
  };
}

const tierPlayerMeta = {
  "star qb": { name: "Star QB", pos: "QB", group: "QB", meta: 5000 },
  "star wr": { name: "Star WR", pos: "WR", group: "WR", meta: 4000 },
  "star lb": { name: "Star LB", pos: "LB", group: "LB", meta: 3000 },
  "bench wr": { name: "Bench WR", pos: "WR", group: "WR", meta: 2000 },
  "solid qb": { name: "Solid QB", pos: "QB", group: "QB", meta: 3000 },
  "solid wr": { name: "Solid WR", pos: "WR", group: "WR", meta: 2000 },
  "depth lb": { name: "Depth LB", pos: "LB", group: "LB", meta: 1000 },
  "spare wr": { name: "Spare WR", pos: "WR", group: "WR", meta: 1500 },
  "lone wr": { name: "Lone WR", pos: "WR", group: "WR", meta: 1000 },
};

// Six premium firsts at 8000 apiece — the pick-hoarding rebuilder's
// entire portfolio.
const tierPickNames = [
  "2026 Early 1st",
  "2026 Mid 1st",
  "2026 Late 1st",
  "2027 Early 1st",
  "2027 Mid 1st",
  "2027 Late 1st",
];

const tierRows = tierPickNames.map((name) => ({
  name,
  pos: "PICK",
  values: { full: 8000, raw: 8000 },
}));

const tierTeams = [
  {
    name: "Win Now",
    players: ["Star QB", "Star WR", "Star LB", "Bench WR"],
    picks: [],
    optimalLineup: tierStamp("Win Now", tierLineups["Win Now"]),
  },
  {
    name: "Balanced",
    players: ["Solid QB", "Solid WR", "Depth LB", "Spare WR"],
    picks: [],
    optimalLineup: tierStamp("Balanced", tierLineups["Balanced"]),
  },
  {
    name: "Pick Hoard",
    players: ["Lone WR"],
    picks: tierPickNames,
    optimalLineup: tierStamp("Pick Hoard", tierLineups["Pick Hoard"]),
  },
];

function tiersByName() {
  const out = {};
  for (const t of scoreTeamTiers(
    tierTeams,
    tierPlayerMeta,
    tierRows,
    null,
    tierRosterPositions,
  )) {
    out[t.name] = t;
  }
  return out;
}

describe("scoreTeamTiers", () => {
  it("counts each roster dollar once — picks are NOT also depth", () => {
    const hoard = tiersByName()["Pick Hoard"];
    // 1000 (Lone WR) + 6 × 8000 picks.
    expect(hoard.totalValue).toBe(49000);
    expect(hoard.pickValue).toBe(48000);
    // Lone WR fills the WR slot; QB and LB slots go unfilled.
    expect(hoard.starterValue).toBe(1000);
    // Everything else this team owns IS the picks, so nothing is left
    // over as depth.  This read 48000 while picks lived inside depth.
    expect(hoard.depthValue).toBe(0);
    // 0.7 × 1000 − 0.1 × 48000 = 700 − 4800.
    expect(hoard.score).toBe(-4100);
  });

  it("still counts non-starting PLAYERS as depth", () => {
    const winNow = tiersByName()["Win Now"];
    // Star QB/WR/LB start (12000); Bench WR is the only depth piece.
    expect(winNow.starterValue).toBe(12000);
    expect(winNow.depthValue).toBe(2000);
    // 0.7 × 12000 + 0.2 × 2000 = 8400 + 400.
    expect(winNow.score).toBe(8800);
  });

  it("tiers a pick-hoarding team as a rebuilder, not a mid-tier team", () => {
    const tiers = tiersByName();
    // Balanced: starters 3000+2000+1000 = 6000, depth 1500.
    // 0.7 × 6000 + 0.2 × 1500 = 4200 + 300 = 4500.
    expect(tiers["Balanced"].score).toBe(4500);
    // With picks double-counted the hoarder scored 700 + 9600 − 4800 =
    // 5500 and OUTRANKED Balanced, taking the mid-tier slot and pushing
    // a deeper roster into the rebuilder bucket.
    expect(tiers["Pick Hoard"].rank).toBe(3);
    expect(tiers["Pick Hoard"].tier).toBe("rebuilder");
    expect(tiers["Balanced"].rank).toBe(2);
    expect(tiers["Balanced"].tier).toBe("middle");
    expect(tiers["Win Now"].rank).toBe(1);
    expect(tiers["Win Now"].tier).toBe("contender");
  });
});
