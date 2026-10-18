import { describe, expect, it } from "vitest";
import {
  activityPairs,
  defaultScoutDirection,
  leagueScoutHref,
  leagueScoutQuery,
  managerLookupHref,
  rankText,
  rosterSlotsText,
  rosterValueText,
  scoutCoverageProblems,
  scoutPicksText,
  scoutRows,
  sortScoutRows,
  tendencySummaryText,
} from "@/lib/manager-intel";
import { LEAGUE } from "./fixtures/manager-intel-league";

const byRoster = (rid) => LEAGUE.managers.find((m) => m.rosterId === rid);

describe("league scouting helpers (Batch C)", () => {
  it("builds the API query and private page links", () => {
    expect(leagueScoutQuery("123")).toBe("/api/manager-intel/league?leagueId=123");
    expect(leagueScoutQuery("123", "90d")).toBe(
      "/api/manager-intel/league?leagueId=123&window=90d",
    );
    expect(leagueScoutHref("1312006700437352448")).toBe(
      "/managers/league/1312006700437352448",
    );
    // Only a numeric Sleeper id becomes a link (no path injection).
    expect(leagueScoutHref("L1")).toBeNull();
    expect(leagueScoutHref("../admin")).toBeNull();
    expect(managerLookupHref("u1")).toBe("/managers?username=u1");
    expect(managerLookupHref(null)).toBeNull();
    expect(managerLookupHref("bad id")).toBeNull();
  });

  it("maps backend rows without inventing values", () => {
    const rows = scoutRows(LEAGUE);
    expect(rows.map((r) => r.rosterId)).toEqual([1, 2, 3]);
    const orphan = rows.find((r) => r.rosterId === 3);
    expect(orphan.name).toBe("Open roster");
    expect(orphan.valueRank).toBeNull();
    expect(orphan.rosterValue).toBeNull(); // only unpriced players: no total
    expect(orphan.picksHeld).toBeNull(); // unknown ownership, not 0 picks
    expect(orphan.pickValue).toBeNull();
    expect(scoutRows(null)).toEqual([]);
  });

  it("sorts with missing values always last", () => {
    const rows = scoutRows(LEAGUE);
    expect(sortScoutRows(rows, "valueRank", "asc").map((r) => r.rosterId)).toEqual([
      1, 2, 3,
    ]);
    expect(sortScoutRows(rows, "valueRank", "desc").map((r) => r.rosterId)).toEqual([
      2, 1, 3,
    ]);
    expect(sortScoutRows(rows, "rosterValue", "desc").at(-1).rosterId).toBe(3);
    expect(sortScoutRows(rows, "name", "asc").map((r) => r.name)).toEqual([
      "Ann",
      "Bob",
      "Open roster",
    ]);
    expect(defaultScoutDirection("valueRank")).toBe("asc");
    expect(defaultScoutDirection("pickValue")).toBe("desc");
  });

  it("labels ranks, totals and picks; unknown is never zero", () => {
    expect(rankText(1, 2)).toBe("#1 of 2");
    expect(rankText(null, 2)).toBe("—");
    expect(rosterValueText(byRoster(1).roster)).toBe("11,000 · 1 unpriced");
    expect(rosterValueText(byRoster(3).roster)).toBe("— · 1 unpriced");
    expect(rosterSlotsText(byRoster(1).roster)).toBe("3 players · 2 starting · 1 taxi");
    expect(scoutPicksText(byRoster(3).draftCapital)).toBe("Unknown");
    expect(scoutPicksText(byRoster(1).draftCapital)).toMatch(/^\d+ held · /);
    expect(scoutPicksText({ available: false })).toBe("Not read (earlier season)");
  });

  it("summarises tendencies as counts, never labels", () => {
    expect(tendencySummaryText(byRoster(1))).toMatch(/^n = 3 · mostly /);
    expect(tendencySummaryText(byRoster(3))).toBe("Insufficient sample (n = 0)");
    expect(
      tendencySummaryText({
        tendenciesSource: "manager_scout",
        scout: {
          tradeTendencies: {
            sampleSize: 4,
            packageShape: { consolidating: 1 },
          },
        },
      }),
    ).toBe("4 trades on record · 1 consolidating");
    expect(
      tendencySummaryText({ tendenciesSource: "manager_scout", scout: null }),
    ).toBe("No Manager Scout profile");
    expect(
      tendencySummaryText({
        tendenciesSource: "manager_scout",
        scout: { tradeTendencies: { state: "unavailable", sampleSize: null } },
      }),
    ).toBe("Manager Scout unavailable");
  });

  it("names coverage problems and activity counts", () => {
    expect(scoutCoverageProblems(LEAGUE)).toEqual([]);
    const partial = {
      ...LEAGUE,
      coverage: {
        ...LEAGUE.coverage,
        transactions: "partial",
        weeksFailed: 2,
        tradedPicks: "rate_limited",
        leagueUsers: "unavailable",
        budgetExhausted: true,
      },
    };
    const problems = scoutCoverageProblems(partial);
    expect(problems[0]).toBe("Transactions partly read (2 weeks missing).");
    expect(problems.join(" ")).toMatch(/pick ownership is unknown/);
    expect(problems.join(" ")).toMatch(/names are missing/);
    expect(problems.join(" ")).toMatch(/call budget/);
    const pairs = activityPairs(byRoster(2).activity);
    expect(pairs.find((p) => p.label === "FAAB spent").value).toBe("$7 (1 claim)");
    expect(activityPairs(byRoster(1).activity).find((p) => p.label === "FAAB spent").value).toBe("—");
  });
});
