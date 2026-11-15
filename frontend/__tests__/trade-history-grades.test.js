/**
 * Trade History under one package model (owner package 2026-10-17):
 * at-the-time request shape, aging = change in ADJUSTED net (±200 PRIOR),
 * fail-closed aging, and Winners & Losers = Σ per-trade adjusted nets.
 */
import { describe, expect, it } from "vitest";
import { analyzeSleeperTradeHistory } from "@/lib/league-analysis";
import {
  AGING,
  AGING_STABLE_BAND_PRIOR,
  buildAsofRequest,
  indexAsofResponse,
  itemToAsset,
  sideAging,
  tradeKey,
} from "@/lib/trade-history-grades";

const rows = [
  { name: "Test Star", pos: "QB", values: { full: 7200, raw: 7200 }, raw: { playerId: "p1" } },
  { name: "Test Mid", pos: "RB", values: { full: 6000, raw: 6000 }, raw: { playerId: "p2" } },
  { name: "Test Dart", pos: "WR", values: { full: 500, raw: 500 }, raw: { playerId: "p3" } },
  { name: "2027 Round 1", pos: "PICK", values: { full: 3000, raw: 3000 } },
];

const DAY = 24 * 60 * 60 * 1000;

function rawWith(trades) {
  return {
    sleeper: {
      teams: [
        { name: "Alpha", roster_id: 1, ownerId: "a" },
        { name: "Beta", roster_id: 2, ownerId: "b" },
      ],
      trades,
    },
  };
}

const TRADES = [
  {
    transactionId: "t-1",
    week: 3,
    timestamp: Date.now() - 30 * DAY,
    sides: [
      { team: "Alpha", rosterId: 1, ownerId: "a", got: ["Test Star"], gave: ["Test Mid", "Test Dart"] },
      { team: "Beta", rosterId: 2, ownerId: "b", got: ["Test Mid", "Test Dart"], gave: ["Test Star"] },
    ],
  },
  {
    transactionId: "t-2",
    week: 5,
    timestamp: Date.now() - 10 * DAY,
    sides: [
      { team: "Alpha", rosterId: 1, ownerId: "a", got: ["Test Dart"], gave: ["Test Dart"] },
      { team: "Beta", rosterId: 2, ownerId: "b", got: ["Test Dart"], gave: ["Test Dart"] },
    ],
  },
];

describe("Winners & Losers — Σ per-trade adjusted nets", () => {
  it("netAdjustedTotal is exactly the sum of every side's netAdjusted, fair trades included", () => {
    const { analyzed, teamScores } = analyzeSleeperTradeHistory(rawWith(TRADES), rows);
    expect(analyzed).toHaveLength(2);
    for (const [, score] of Object.entries(teamScores)) {
      const sum = analyzed
        .flatMap((a) => a.sides)
        .filter((s) => s.ownerId === score.ownerId)
        .reduce((acc, s) => acc + s.netAdjusted, 0);
      expect(score.netAdjustedTotal).toBeCloseTo(sum, 9);
      expect(score.trades).toBe(2);
    }
    // Zero-sum across a 2-team league.
    const total = Object.values(teamScores).reduce((acc, s) => acc + s.netAdjustedTotal, 0);
    expect(total).toBeCloseTo(0, 9);
  });

  it("counts sides whose today's total excludes an unpriced asset", () => {
    const trades = [
      {
        transactionId: "t-3",
        timestamp: Date.now() - DAY,
        sides: [
          { team: "Alpha", rosterId: 1, ownerId: "a", got: ["Nobody Known"], gave: ["Test Dart"] },
          { team: "Beta", rosterId: 2, ownerId: "b", got: ["Test Dart"], gave: ["Nobody Known"] },
        ],
      },
    ];
    const { teamScores } = analyzeSleeperTradeHistory(rawWith(trades), rows);
    for (const s of Object.values(teamScores)) expect(s.incompleteTrades).toBe(1);
  });
});

describe("at-the-time request", () => {
  it("keys trades by Sleeper transaction id and carries the trade instant", () => {
    const { analyzed } = analyzeSleeperTradeHistory(rawWith(TRADES), rows);
    const req = buildAsofRequest(analyzed);
    expect(req.trades.map((t) => t.id)).toEqual(analyzed.map((a) => `tx:${a.trade.transactionId}`));
    expect(req.trades[0].createdAt).toBe(analyzed[0].trade.timestamp);
    const sideA = req.trades.find((t) => t.id === "tx:t-1").sides[0];
    expect(sideA.receivedAssets).toEqual([
      { kind: "player", playerId: "p1", playerName: "Test Star", position: "QB" },
    ]);
    expect(sideA.sentAssets.map((a) => a.playerName)).toEqual(["Test Mid", "Test Dart"]);
  });

  it("an undated trade sends createdAt null — never now", () => {
    const a = { trade: { transactionId: "", timestamp: 0 }, sides: [] };
    expect(buildAsofRequest([a]).trades[0]).toEqual({ id: "idx:0", createdAt: null, sides: [] });
    expect(tradeKey(a, 4)).toBe("idx:4");
  });

  it("picks become the generic (season, round) asset; unparseable picks stay unresolvable", () => {
    expect(itemToAsset({ name: "2027 1st", isPick: true })).toEqual({
      kind: "pick",
      label: "2027 1st",
      season: 2027,
      round: 1,
    });
    expect(itemToAsset({ name: "2026 2.07", isPick: true })).toMatchObject({ season: 2026, round: 2 });
    expect(itemToAsset({ name: "mystery pick", isPick: true })).toMatchObject({
      kind: "pick",
      season: null,
      round: null,
    });
  });

  it("indexes the response by trade id", () => {
    const idx = indexAsofResponse({ trades: [{ id: "tx:1", sides: [{ available: false }] }] });
    expect(idx.get("tx:1")).toEqual([{ available: false }]);
  });
});

describe("How It Aged — change in adjusted net, same model", () => {
  const now = { netAdjusted: 900, unresolvedAssets: 0 };
  it("measures today − at-the-time adjusted net", () => {
    const r = sideAging(now, { available: true, netAdjusted: 300 });
    expect(r).toEqual({ verdict: AGING.AGED_WELL, reason: null, delta: 600 });
    expect(sideAging(now, { available: true, netAdjusted: 1500 }).verdict).toBe(AGING.AGED_POORLY);
  });

  it("the ±200 band is a labelled prior, inclusive at the edge", () => {
    expect(AGING_STABLE_BAND_PRIOR).toBe(200);
    expect(sideAging(now, { available: true, netAdjusted: 700 }).verdict).toBe(AGING.STABLE);
    expect(sideAging(now, { available: true, netAdjusted: 699 }).verdict).toBe(AGING.AGED_WELL);
  });

  it("fails closed: missing at-time evidence, unpriced today, or a model mismatch", () => {
    expect(sideAging(now, { available: false, reason: "no_historical_evidence" })).toEqual({
      verdict: AGING.UNAVAILABLE,
      reason: "no_historical_evidence",
      delta: null,
    });
    expect(sideAging({ netAdjusted: 900, unresolvedAssets: 1 }, { available: true, netAdjusted: 0 }).reason).toBe(
      "unpriced_today",
    );
    expect(sideAging(now, { available: true, netAdjusted: 0 }, { modelMatches: false }).reason).toBe(
      "package_model_mismatch",
    );
    expect(sideAging(now, undefined).verdict).toBe(AGING.UNAVAILABLE);
  });
});
