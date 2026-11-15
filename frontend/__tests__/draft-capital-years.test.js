/**
 * Draft Capital year selector — pure selection + URL state
 * (owner request 2026-10-01; lib/draft-capital-years.js).
 *
 * Nothing here values a pick.  Available seasons and per-season capital come
 * from the backend's `availableYears` / `teamTotalsByYear`; these tests pin
 * that the client reads them (rather than a year list of its own), that the
 * `?year=` param round-trips through the /league router helper, and that bad
 * params fall back to All Years.
 */
import { describe, expect, it } from "vitest";

import { leagueTabHref } from "@/app/league/tabs.js";
import {
  ALL_YEARS,
  DRAFT_CAPITAL_YEAR_PARAM,
  availableDraftCapitalYears,
  draftCapitalPickLabel,
  draftCapitalPicksForYear,
  draftCapitalSlotsAreStandIns,
  draftCapitalTeamRows,
  draftCapitalYearSummary,
  isUnpricedPick,
  parseDraftCapitalYear,
  serializeDraftCapitalYear,
} from "@/lib/draft-capital-years";

function payload(years = [2027, 2028]) {
  return {
    season: years[0],
    availableYears: years,
    teamTotals: [
      { team: "A", auctionDollars: 700 },
      { team: "B", auctionDollars: 500 },
    ],
    teamTotalsByYear: Object.fromEntries(
      years.map((y, i) => [
        String(y),
        i === 0
          ? [
              { team: "A", auctionDollars: 600, rank: 1, pickCount: 3 },
              { team: "B", auctionDollars: 100, rank: 2, pickCount: 1 },
            ]
          : [
              { team: "B", auctionDollars: 400, rank: 1, pickCount: 3 },
              { team: "A", auctionDollars: 100, rank: 2, pickCount: 1 },
            ],
      ]),
    ),
    yearSummaries: Object.fromEntries(years.map((y) => [String(y), { pickCount: 4 }])),
    picks: years.flatMap((y) => [
      { season: y, round: 1, pick: "1.01", currentOwner: "A", dollarValue: 10 },
      { season: y, round: 1, pick: "1.02", currentOwner: "B", dollarValue: 5 },
    ]),
  };
}

describe("available years are data, not a list", () => {
  it("reads the backend's availableYears, whatever they are", () => {
    expect(availableDraftCapitalYears(payload([2027, 2028]))).toEqual([2027, 2028]);
    // A later season appears and a retired one disappears with no code change.
    expect(availableDraftCapitalYears(payload([2028, 2029, 2030]))).toEqual([2028, 2029, 2030]);
  });

  it("offers no season when the payload predates the per-season views", () => {
    const legacy = { season: 2027, teamTotals: [], picks: [] };
    expect(availableDraftCapitalYears(legacy)).toEqual([]);
    expect(availableDraftCapitalYears(null)).toEqual([]);
    // A season with no ranked view behind it is not offered.
    const partial = { ...payload([2027, 2028]), teamTotalsByYear: { 2027: [] } };
    expect(availableDraftCapitalYears(partial)).toEqual([2027]);
  });
});

describe("?year= parse / serialize", () => {
  const years = [2027, 2028, 2029];

  it("accepts an available season", () => {
    expect(parseDraftCapitalYear("2028", years)).toBe(2028);
  });

  it.each([["", null], [null, null], ["all", null], ["abc", null], ["2026", null], ["20281", null], ["2028.0", null]])(
    "falls back to All Years for %j",
    (raw) => {
      expect(parseDraftCapitalYear(raw, years)).toBe(null);
    },
  );

  it("serializes a season and removes the param for All Years", () => {
    expect(serializeDraftCapitalYear(2027)).toBe("2027");
    expect(serializeDraftCapitalYear("2029")).toBe("2029");
    expect(serializeDraftCapitalYear(null)).toBe(null);
    expect(serializeDraftCapitalYear(ALL_YEARS)).toBe(null);
  });

  it("round-trips through the /league router helper (reload / direct link)", () => {
    const href = leagueTabHref("draft-capital", "", {
      [DRAFT_CAPITAL_YEAR_PARAM]: serializeDraftCapitalYear(2028),
    });
    expect(href).toBe("/league?tab=draft-capital&year=2028");
    const reloaded = new URLSearchParams(href.split("?")[1]);
    expect(parseDraftCapitalYear(reloaded.get(DRAFT_CAPITAL_YEAR_PARAM), years)).toBe(2028);

    // Back to All Years strips the param rather than writing year=all.
    const back = leagueTabHref("draft-capital", "tab=draft-capital&year=2028", {
      [DRAFT_CAPITAL_YEAR_PARAM]: serializeDraftCapitalYear(null),
    });
    expect(back).toBe("/league?tab=draft-capital");
  });
});

describe("selection over backend views", () => {
  it("All Years is the existing teamTotals, untouched", () => {
    const data = payload();
    expect(draftCapitalTeamRows(data, null)).toBe(data.teamTotals);
  });

  it("a season reads the backend's ranked rows — the order genuinely changes", () => {
    const data = payload();
    expect(draftCapitalTeamRows(data, 2027).map((r) => r.team)).toEqual(["A", "B"]);
    expect(draftCapitalTeamRows(data, 2028).map((r) => r.team)).toEqual(["B", "A"]);
    expect(draftCapitalTeamRows(data, 2031)).toEqual([]);
    expect(draftCapitalYearSummary(data, 2027)).toEqual({ pickCount: 4 });
    expect(draftCapitalYearSummary(data, null)).toBe(null);
  });

  it("filters picks to the season and keeps every pick for All Years", () => {
    const data = payload();
    expect(draftCapitalPicksForYear(data.picks, null)).toHaveLength(4);
    const p28 = draftCapitalPicksForYear(data.picks, 2028);
    expect(p28).toHaveLength(2);
    expect(p28.every((p) => p.season === 2028)).toBe(true);
    // Workbook rows without a per-row season fall back to the board season.
    const workbook = [{ round: 1, pick: "1.01" }];
    expect(draftCapitalPicksForYear(workbook, 2027, 2027)).toHaveLength(1);
    expect(draftCapitalPicksForYear(workbook, 2028, 2027)).toHaveLength(0);
  });
});

describe("missing is never zero; slots are never invented", () => {
  it("treats a null-dollar or flagged pick as unpriced, and $0 as priced", () => {
    expect(isUnpricedPick({ dollarValue: null, isUnpriced: true })).toBe(true);
    expect(isUnpricedPick({ dollarValue: null })).toBe(true);
    expect(isUnpricedPick({ dollarValue: 0, isUnpriced: false })).toBe(false);
    expect(isUnpricedPick({ adjustedDollarValue: 3.5 })).toBe(false);
  });

  it("shows round-only labels when the board's slots are stand-ins", () => {
    const p = { season: 2028, round: 2, pick: "2.05" };
    expect(draftCapitalSlotsAreStandIns({ source: "sleeper_derived" })).toBe(true);
    expect(draftCapitalSlotsAreStandIns({})).toBe(false);
    expect(draftCapitalPickLabel(p, { slotsAreStandIns: true })).toBe("R2");
    expect(draftCapitalPickLabel(p, { slotsAreStandIns: false })).toBe("2.05");
    expect(draftCapitalPickLabel(p, { slotsAreStandIns: true, withSeason: true })).toBe("'28 R2");
  });
});
