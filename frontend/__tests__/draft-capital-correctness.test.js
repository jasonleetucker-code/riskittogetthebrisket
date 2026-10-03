import { describe, expect, it } from "vitest";

import * as PS from "@/lib/pick-stack";
import { tradeRequestForTeam, analyzeRequestKey } from "@/lib/trade-war-room";

// Wave A — draft-capital correctness (owner directive 2026-10-03).  Three
// independent defects, each RED against the pre-fix code:
//
//   1. the /trade stack anchored on the BOARD's draft year (2026) while this
//      league's draft capital was 2027's;
//   2. the workbook payload's teamTotals cover one season but said nothing,
//      so /trade re-added that season's owned picks (and joined teams by
//      display NAME across two different name spaces);
//   3. a side was debited for any pick by name, owned or not.
//
// Uniqueness is enforced only where a pick is ATTRIBUTED to a real team.  The
// hypothetical calculator keeps letting a user add any asset any number of
// times (owner decision 2026-10-03, #1619) -- trade-asset-quantity.test.js.

// The production shape measured on 2026-10-03: the board still prices the
// 2026 class (some served league has not retired it) while THIS league's
// rookie draft for 2026 is done, so its workbook covers 2027.
const BOARD = {
  currentDraftYear: 2026,
  pickClassLifecycle: { retiredYears: [], firstActiveClass: 2026 },
};

function workbook2027({ withFields = true } = {}) {
  const r1 = [120, 110, 100, 90, 80, 70, 60, 50, 40, 30, 20, 10];
  const picks = r1.map((d, i) => ({
    season: 2027,
    round: 1,
    pickInRound: i + 1,
    dollarValue: d,
    ...(withFields ? { assetId: `pick:lk:2027:r1:o${i + 1}` } : {}),
  }));
  return {
    season: 2027,
    numTeams: 12,
    picks,
    // Sleeper TEAM names (``user.metadata.team_name``)...
    teamTotals: [
      { team: "Russini Panini", auctionDollars: 300, ...(withFields ? { rosterId: 1 } : {}) },
      { team: "Gridiron Gang", auctionDollars: 180, ...(withFields ? { rosterId: 2 } : {}) },
    ],
    ...(withFields ? { coveredPickYears: [2027], upcomingDraftYear: 2027 } : {}),
  };
}

// ...while sleeper.teams carry OWNER first names.
const TEAMS = [
  {
    name: "Jason",
    roster_id: 1,
    pickDetails: [
      { season: 2027, round: 1, label: "2027 Early 1st (own)", assetId: "pick:lk:2027:r1:o1" },
      { season: 2028, round: 1, label: "2028 Early 1st (own)", assetId: "pick:lk:2028:r1:o1" },
    ],
  },
  {
    name: "Blaine",
    roster_id: 2,
    pickDetails: [
      { season: 2027, round: 1, label: "2027 Early 1st (own)", assetId: "pick:lk:2027:r1:o2" },
      { season: 2028, round: 1, label: "2028 Mid 1st (own)", assetId: "pick:lk:2028:r1:o2" },
    ],
  },
];

const ROW = (name) => ({ name, assetClass: "pick" });
const resolveRow = (label) => {
  const m = String(label).match(/^(20\d{2} (?:Early|Mid|Late) 1st)/);
  return m ? ROW(m[1]) : null;
};

describe("Defect 1 — the stack anchors on THIS league's upcoming draft", () => {
  it("reads the draft-capital payload's league-scoped year, not the board's", () => {
    // RED before Wave A: 2026 (board firstActiveClass).
    expect(PS.pickStackAnchorYear(BOARD, workbook2027())).toBe(2027);
  });

  it("older payloads without the stamp still use the draft-capital season", () => {
    expect(PS.pickStackAnchorYear(BOARD, workbook2027({ withFields: false }))).toBe(2027);
  });

  it("the board's year is only a last resort", () => {
    expect(PS.pickStackAnchorYear(BOARD, null)).toBe(2026);
    expect(PS.pickStackAnchorYear(null, null)).toBe(null);
  });
});

describe("Defect 2 — no owned pick is counted twice in a stack", () => {
  it("teams join by stable roster key across the two name spaces", () => {
    expect(PS.teamStackKey({ team: "Russini Panini", rosterId: 1 })).toBe("roster:1");
    expect(PS.teamStackKey({ name: "Jason", roster_id: 1 })).toBe("roster:1");
  });

  it("covered seasons and covered asset ids are not re-added from roster ownership", () => {
    const inv = PS.ownedPickStackInventory(TEAMS, workbook2027(), resolveRow);
    expect(inv.byTeam).toEqual({
      "roster:1": ["2028 Early 1st"],
      "roster:2": ["2028 Mid 1st"],
    });
  });

  it("an asset id already on a draft-capital row is excluded even with no coveredPickYears", () => {
    const dc = { ...workbook2027(), coveredPickYears: undefined };
    const inv = PS.ownedPickStackInventory(TEAMS, dc, resolveRow);
    expect(Object.values(inv.byTeam).flat()).not.toContain("2027 Early 1st");
  });

  it("a pick id published on two teams counts once", () => {
    const doubled = [
      TEAMS[0],
      { ...TEAMS[1], pickDetails: [...TEAMS[1].pickDetails, TEAMS[0].pickDetails[1]] },
    ];
    const inv = PS.ownedPickStackInventory(doubled, workbook2027(), resolveRow);
    expect(inv.duplicateIds).toEqual(["pick:lk:2028:r1:o1"]);
    expect(Object.values(inv.byTeam).flat().filter((n) => n === "2028 Early 1st")).toHaveLength(1);
  });

  it("one stack per team: covered dollars plus each uncovered real pick once", () => {
    const dc = workbook2027();
    const ctx = {
      slotGrid: PS.buildSlotDollarGrid(dc),
      teamsPerRound: 12,
      currentDraftYear: PS.pickStackAnchorYear(BOARD, dc),
      boardValueByName: (n) => ({ "2027 Early 1st": 1000, "2028 Early 1st": 1000, "2028 Mid 1st": 1000 })[n] || 0,
    };
    const inv = PS.ownedPickStackInventory(TEAMS, dc, resolveRow);
    const stacks = PS.buildLeagueStacks(dc, inv.byTeam, ctx);
    // RED before Wave A: four keys ("Russini Panini", "Gridiron Gang" and the
    // two Sleeper-team keys) with every 2027 pick added on top of the 2027 $.
    expect(Object.keys(stacks).sort()).toEqual(["roster:1", "roster:2"]);
    // 2028 Early 1st = avg(120,110,100,90) x 1.0 discount = 105.
    expect(stacks["roster:1"]).toBeCloseTo(300 + 105, 6);
    // 2028 Mid 1st = avg(80,70,60,50) = 65.
    expect(stacks["roster:2"]).toBeCloseTo(180 + 65, 6);
  });
});

describe("Defect 3 — a side is never debited for a pick its team does not hold", () => {
  const sideTeamKeys = ["roster:1", "roster:2"];
  const opts = {
    sideTeamKeys,
    get ownerKeyByAssetId() {
      return PS.pickOwnerKeyByAssetId(TEAMS);
    },
    destinationOf: (i) => 1 - i,
    dollarsOf: () => 50,
  };
  const owned = (label, assetId) => ({ ...ROW(label.slice(0, 14)), assetId, assetLabel: label });

  it("an owned pick held by the sending team moves the stack", () => {
    const sides = [{ assets: [owned("2028 Early 1st (own)", "pick:lk:2028:r1:o1")] }, { assets: [] }];
    expect(PS.stackPickMoves(sides, { ...opts }).moves).toEqual([{ from: 0, to: 1, dollars: 50 }]);
  });

  it("another team's pick on this side is reported with its owner, not moved", () => {
    const sides = [{ assets: [owned("2028 Mid 1st (own)", "pick:lk:2028:r1:o2")] }, { assets: [] }];
    const out = PS.stackPickMoves(sides, { ...opts });
    expect(out.moves).toEqual([]);
    expect(out.notOwned).toEqual([
      { assetId: "pick:lk:2028:r1:o2", label: "2028 Mid 1st (own)", side: 0, ownerKey: "roster:2" },
    ]);
  });

  it("a generic pick is hypothetical and never debits a team's real stack", () => {
    const sides = [{ assets: [ROW("2028 Early 1st"), ROW("2028 Early 1st")] }, { assets: [] }];
    const out = PS.stackPickMoves(sides, { ...opts });
    expect(out.moves).toEqual([]);
    expect(out.hypothetical).toEqual(["2028 Early 1st", "2028 Early 1st"]);
  });

  it("repeated copies of one owned pick move it once", () => {
    const pick = owned("2028 Early 1st (own)", "pick:lk:2028:r1:o1");
    const sides = [{ assets: [pick, pick, pick] }, { assets: [] }];
    expect(PS.stackPickMoves(sides, { ...opts }).moves).toHaveLength(1);
  });

  it("an id two teams claim is unknown, never moved", () => {
    const doubled = PS.pickOwnerKeyByAssetId([
      TEAMS[0],
      { ...TEAMS[1], pickDetails: [TEAMS[0].pickDetails[1]] },
    ]);
    const sides = [{ assets: [owned("2028 Early 1st (own)", "pick:lk:2028:r1:o1")] }, { assets: [] }];
    const out = PS.stackPickMoves(sides, { ...opts, ownerKeyByAssetId: doubled });
    expect(out.moves).toEqual([]);
    expect(out.notOwned[0].ownerKey).toBe(null);
  });

  it("simulate / Analyze requests carry each owned pick's id beside its label", () => {
    const sides = [
      { assets: [{ name: "2028 Early 1st", assetId: "pick:lk:2028:r1:o1", assetLabel: "2028 Early 1st (own)" }, { name: "2029 Mid 2nd" }] },
      { assets: [{ name: "Player X" }] },
    ];
    const req = tradeRequestForTeam(sides, new Set(["2028 Early 1st"]), "Jason");
    // RED before Wave A: no ids, so the backend matched by label/board row.
    expect(req.picksOut).toEqual(["2028 Early 1st (own)", "2029 Mid 2nd"]);
    expect(req.pickAssetIdsOut).toEqual(["pick:lk:2028:r1:o1", null]);
    expect(req.pickAssetIdsIn).toEqual([]);
    // Two picks sharing a label are different questions.
    const other = tradeRequestForTeam(
      [{ ...sides[0], assets: [{ ...sides[0].assets[0], assetId: "pick:lk:2028:r1:o3" }, sides[0].assets[1]] }, sides[1]],
      new Set(["2028 Early 1st"]),
      "Jason",
    );
    expect(analyzeRequestKey(other, "lk", true)).not.toBe(analyzeRequestKey(req, "lk", true));
  });
});
