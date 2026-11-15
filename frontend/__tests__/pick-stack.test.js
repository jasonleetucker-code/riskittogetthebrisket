import { describe, expect, it } from "vitest";

import {
  parsePickAsset,
  tierSlotRange,
  buildSlotDollarGrid,
  pickAuctionDollars,
  buildLeagueStacks,
  pickStackAnchorYear,
  poolBoardPerDollar,
} from "@/lib/pick-stack";

describe("parsePickAsset", () => {
  it("parses an explicit slot pick", () => {
    expect(parsePickAsset("2026 Pick 1.04")).toEqual({
      year: 2026,
      round: 1,
      tier: null,
      slot: 4,
    });
  });

  it("parses an Early/Mid/Late tier pick", () => {
    expect(parsePickAsset("2027 Early 1st")).toEqual({
      year: 2027,
      round: 1,
      tier: "early",
      slot: null,
    });
    expect(parsePickAsset("2028 Mid 2nd")).toEqual({
      year: 2028,
      round: 2,
      tier: "mid",
      slot: null,
    });
  });

  it("parses a round-only future pick", () => {
    expect(parsePickAsset("2027 1st")).toEqual({
      year: 2027,
      round: 1,
      tier: null,
      slot: null,
    });
  });

  it("returns null for non-picks", () => {
    expect(parsePickAsset("Josh Allen")).toBeNull();
    expect(parsePickAsset("")).toBeNull();
  });
});

describe("tierSlotRange (equal thirds, remainder to Mid then Late)", () => {
  it("12 teams → 1-4 / 5-8 / 9-12 (the spec example)", () => {
    expect(tierSlotRange("early", 12)).toEqual([1, 4]);
    expect(tierSlotRange("mid", 12)).toEqual([5, 8]);
    expect(tierSlotRange("late", 12)).toEqual([9, 12]);
  });

  it("10 teams → 1-3 / 4-7 / 8-10", () => {
    expect(tierSlotRange("early", 10)).toEqual([1, 3]);
    expect(tierSlotRange("mid", 10)).toEqual([4, 7]);
    expect(tierSlotRange("late", 10)).toEqual([8, 10]);
  });

  it("14 teams → 1-4 / 5-9 / 10-14", () => {
    expect(tierSlotRange("early", 14)).toEqual([1, 4]);
    expect(tierSlotRange("mid", 14)).toEqual([5, 9]);
    expect(tierSlotRange("late", 14)).toEqual([10, 14]);
  });

  it("degenerate tiny league falls back to whole round", () => {
    expect(tierSlotRange("early", 2)).toEqual([1, 2]);
  });
});

// Round 1: slot $ 120,110,100,90,80,70,60,50,40,30,20,10 (12 teams)
function dc12() {
  const picks = [];
  const r1 = [120, 110, 100, 90, 80, 70, 60, 50, 40, 30, 20, 10];
  r1.forEach((d, idx) =>
    picks.push({ round: 1, pickInRound: idx + 1, dollarValue: d }),
  );
  return {
    season: "2026",
    numTeams: 12,
    picks,
    teamTotals: [
      { team: "Alpha", auctionDollars: 300 },
      { team: "Bravo", auctionDollars: 180 },
      { team: "Charlie", auctionDollars: 120 },
    ],
  };
}

describe("pickAuctionDollars", () => {
  const dc = dc12();
  const grid = buildSlotDollarGrid(dc);
  // The current-year generic tier row ("2026 Early 1st") is
  // deliberately ABSENT (→ 0) to mirror the backend suppressing it
  // when authoritative slot rows exist; the discount denominator must
  // come from the current-year SLOT rows instead.
  const board = (name) =>
    ({
      "2027 Early 1st": 800,
      "2026 Pick 1.01": 1000,
      "2026 Pick 1.02": 1000,
      "2026 Pick 1.03": 1000,
      "2026 Pick 1.04": 1000,
    })[name] || 0;
  const ctx = {
    slotGrid: grid,
    teamsPerRound: 12,
    currentDraftYear: 2026,
    boardValueByName: board,
  };

  it("tier = average of its slot third (current year)", () => {
    // Early 1st = avg(120,110,100,90) = 105
    expect(pickAuctionDollars("2026 Early 1st", ctx)).toBeCloseTo(105, 6);
    // Mid 1st = avg(80,70,60,50) = 65
    expect(pickAuctionDollars("2026 Mid 1st", ctx)).toBeCloseTo(65, 6);
    // Late 1st = avg(40,30,20,10) = 25
    expect(pickAuctionDollars("2026 Late 1st", ctx)).toBeCloseTo(25, 6);
  });

  it("explicit slot uses the exact (year, round, slot) dollar", () => {
    // slot 3 of round 1 = 100 in the grid for year 2026
    expect(pickAuctionDollars("2026 Pick 1.03", ctx)).toBeCloseTo(100, 6);
  });

  it("multi-season payload: each year's slot $ is independent (no collision)", () => {
    // Sleeper-derived shape: same round/slot across two seasons with
    // DIFFERENT dollars + per-row season.  The next year must not
    // overwrite the current year (the bug this guards).
    const multi = {
      season: "2026",
      numTeams: 12,
      coveredPickYears: [2026, 2027],
      picks: [
        { season: 2026, round: 1, slot: 1, dollarValue: 120 },
        { season: 2027, round: 1, slot: 1, dollarValue: 60 },
      ],
      teamTotals: [],
    };
    const g = buildSlotDollarGrid(multi);
    expect(g[2026][1][1]).toBe(120);
    expect(g[2027][1][1]).toBe(60);
    const c = { slotGrid: g, teamsPerRound: 12, currentDraftYear: 2026 };
    expect(pickAuctionDollars("2026 Pick 1.01", c)).toBe(120);
    expect(pickAuctionDollars("2027 Pick 1.01", c)).toBe(60);
  });

  it("future tier applies the board-derived year discount", () => {
    // base avg(120,110,100,90)=105, discount = 800/1000 = 0.8 → 84
    expect(pickAuctionDollars("2027 Early 1st", ctx)).toBeCloseTo(84, 6);
  });

  it("round-only pick = whole-round average", () => {
    // avg of all 12 slots (120…10) = 780/12 = 65
    expect(pickAuctionDollars("2026 1st", ctx)).toBeCloseTo(65, 6);
  });

  it("non-pick → 0", () => {
    expect(pickAuctionDollars("Josh Allen", ctx)).toBe(0);
  });
});

describe("buildLeagueStacks", () => {
  it("upcoming-draft $ from teamTotals plus future-year owned picks", () => {
    const dc = dc12();
    const ctx = {
      slotGrid: buildSlotDollarGrid(dc),
      teamsPerRound: 12,
      currentDraftYear: 2026,
      boardValueByName: (n) =>
        ({ "2027 Early 1st": 1000, "2026 Early 1st": 1000 })[n] || 0,
    };
    // Alpha also owns a 2027 Early 1st (discount 1.0 → 105)
    const stacks = buildLeagueStacks(
      dc,
      { Alpha: ["2027 Early 1st"] },
      ctx,
    );
    expect(stacks.Alpha).toBeCloseTo(300 + 105, 6);
    expect(stacks.Bravo).toBe(180);
    expect(stacks.Charlie).toBe(120);
  });
});

// #1414 / #1442 / Wave A: the stack anchors on THIS LEAGUE's upcoming draft
// -- the draft-capital payload's league-scoped ``upcomingDraftYear`` (else its
// ``season``) -- never the board's ``pickClassLifecycle.firstActiveClass``,
// which stays on a class until every league sharing the board retires it.
describe("pickStackAnchorYear", () => {
  it("prefers the league-scoped upcoming draft on the draft-capital payload", () => {
    const contract = {
      currentDraftYear: 2026,
      pickClassLifecycle: { retiredYears: [], firstActiveClass: 2026 },
    };
    expect(pickStackAnchorYear(contract, { upcomingDraftYear: 2027, season: 2027 })).toBe(2027);
  });

  it("falls back to the draft-capital season, then the board's years", () => {
    expect(pickStackAnchorYear({ currentDraftYear: 2026 }, { season: "2027" })).toBe(2027);
    expect(
      pickStackAnchorYear({ pickClassLifecycle: { firstActiveClass: 2027 }, currentDraftYear: 2026 }, null),
    ).toBe(2027);
    expect(pickStackAnchorYear({ currentDraftYear: 2026 }, null)).toBe(2026);
    expect(pickStackAnchorYear(null, null)).toBe(null);
  });

  it("with the retired class gone, the upcoming class is undiscounted and later ones discount against it", () => {
    // 2026 retired: its slot rows are ABSENT from the board.  The upcoming
    // draft is 2027 (tiers only, no slot rows yet); the draft-capital grid
    // is the 2027 draft's.
    const dc = { ...dc12(), season: "2027" };
    const board = (name) =>
      ({ "2027 Early 1st": 1000, "2028 Early 1st": 800, "2029 Early 1st": 640 })[name] || 0;
    const contract = {
      currentDraftYear: 2026,
      pickClassLifecycle: { retiredYears: [2026], firstActiveClass: 2027 },
    };
    const ctx = {
      slotGrid: buildSlotDollarGrid(dc),
      teamsPerRound: 12,
      currentDraftYear: pickStackAnchorYear(contract, dc),
      boardValueByName: board,
    };
    // base avg(120,110,100,90) = 105
    expect(pickAuctionDollars("2027 Early 1st", ctx)).toBeCloseTo(105, 6); // factor 1.0
    expect(pickAuctionDollars("2028 Early 1st", ctx)).toBeCloseTo(84, 6); // 0.8
    expect(pickAuctionDollars("2029 Early 1st", ctx)).toBeCloseTo(67.2, 6); // 0.64

    // Anchoring on the horizon year instead (the regression this guards):
    // the retired 2026 rows are absent, so every future class loses its
    // discount.
    const horizonCtx = { ...ctx, currentDraftYear: contract.currentDraftYear };
    expect(pickAuctionDollars("2028 Early 1st", horizonCtx)).toBeCloseTo(105, 6);
  });
});

describe("poolBoardPerDollar (league pool $ -> board rate)", () => {
  const dc = {
    season: 2027,
    picks: [
      { round: 1, pickInRound: 1, dollarValue: 100 },
      { round: 1, pickInRound: 12, dollarValue: 50 },
      { round: 6, pickInRound: 5, dollarValue: 1 },
      { round: 6, pickInRound: 6, dollarValue: 0 }, // unpriced: excluded
    ],
  };
  const board = {
    "2027 Pick 1.01": 6000,
    "2027 Late 1st": 4000, // no slot row for 1.12 -> tier row
    "2027 Pick 6.05": 1000,
    "2027 Pick 6.06": 900,
  };
  const lookup = (n) => board[n] || 0;

  it("sums board over dollars for the draft's own picks, slot then tier", () => {
    expect(poolBoardPerDollar(dc, lookup, 12)).toBeCloseTo((6000 + 4000 + 1000) / 151, 9);
  });

  it("leaves a pick with no board row out of BOTH sums", () => {
    const partial = (n) => (n === "2027 Pick 6.05" ? 0 : lookup(n));
    expect(poolBoardPerDollar(dc, partial, 12)).toBeCloseTo((6000 + 4000) / 150, 9);
  });

  it("is null when nothing pairs (the stack effect is then withheld)", () => {
    expect(poolBoardPerDollar(dc, () => 0, 12)).toBeNull();
    expect(poolBoardPerDollar({ picks: [] }, lookup, 12)).toBeNull();
    expect(poolBoardPerDollar(null, lookup, 12)).toBeNull();
    expect(poolBoardPerDollar(dc, null, 12)).toBeNull();
  });
});
