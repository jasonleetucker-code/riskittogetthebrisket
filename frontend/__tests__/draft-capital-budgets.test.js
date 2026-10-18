// MISSING IS NEVER ZERO for draft-capital auction budgets (#1785, 2026-10-18).
//
// A cold deploy (no league draft-class snapshot) used to serve dynasty_new's
// drafted class as "upcoming": unpriced, so every team's auction budget read
// $0 on /draft, the auction room, the /league simulator and the /trade stack.
// The backend now publishes `teamTotalsState: "unavailable"` with null
// `auctionDollars`; these tests pin that every frontend reader refuses to
// turn that into $0.
import { describe, expect, it } from "vitest";

import {
  draftCapitalBudgetRows,
  draftCapitalBudgetsUnavailableReason,
  draftCapitalBudgetsUnavailableText,
} from "@/lib/draft-capital-budgets";
import { buildLeagueStacks } from "@/lib/pick-stack";
import { mergeDraftCapitalTeams } from "@/lib/draft-logic";

const UNAVAILABLE = {
  season: 2026,
  teamTotalsState: "unavailable",
  teamTotalsReason: "upcoming_class_unpriced",
  coveredPickYears: [],
  teamTotals: [
    { team: "Alpha", auctionDollars: null, rosterId: 1 },
    { team: "Beta", auctionDollars: null, rosterId: 2 },
  ],
  picks: [],
};

const AVAILABLE = {
  season: 2027,
  teamTotalsState: "available",
  teamTotalsReason: null,
  coveredPickYears: [2027],
  teamTotals: [
    { team: "Alpha", auctionDollars: 700, rosterId: 1 },
    { team: "Beta", auctionDollars: 500, rosterId: 2 },
  ],
  picks: [],
};

describe("draftCapitalBudgetsUnavailableReason", () => {
  it("names the backend's reason when budgets are unavailable", () => {
    expect(draftCapitalBudgetsUnavailableReason(UNAVAILABLE)).toBe("upcoming_class_unpriced");
    expect(
      draftCapitalBudgetsUnavailableReason({
        ...UNAVAILABLE,
        teamTotalsReason: "upcoming_draft_year_unverified",
      }),
    ).toBe("upcoming_draft_year_unverified");
  });

  it("reads available and legacy numeric payloads as available", () => {
    expect(draftCapitalBudgetsUnavailableReason(AVAILABLE)).toBeNull();
    const { teamTotalsState: _s, teamTotalsReason: _r, ...legacy } = AVAILABLE;
    expect(draftCapitalBudgetsUnavailableReason(legacy)).toBeNull();
  });

  it("treats a legacy payload of all-null budgets as unavailable, not $0", () => {
    const { teamTotalsState: _s, teamTotalsReason: _r, ...legacy } = UNAVAILABLE;
    expect(draftCapitalBudgetsUnavailableReason(legacy)).toBe("no_team_budgets");
  });

  it("says why, and that it is not $0", () => {
    expect(draftCapitalBudgetsUnavailableText("upcoming_class_unpriced")).toMatch(
      /Auction budgets unavailable: the upcoming draft class has no priced picks\. Not shown as \$0\./,
    );
    expect(draftCapitalBudgetsUnavailableText("upcoming_draft_year_unverified")).toMatch(
      /upcoming draft year could not be verified/,
    );
  });
});

describe("/draft loader — draftCapitalBudgetRows", () => {
  it("refuses unavailable budgets instead of handing nulls to the merge", () => {
    expect(() => draftCapitalBudgetRows(UNAVAILABLE)).toThrow(/Auction budgets unavailable/);
  });

  it("returns real budgets unchanged", () => {
    expect(draftCapitalBudgetRows(AVAILABLE)).toBe(AVAILABLE.teamTotals);
  });

  it("is the guard that matters: the merge itself would coerce null to $0", () => {
    // Pinning WHY the loader must ask first: mergeDraftCapitalTeams reads a
    // null budget as 0.  The loader never reaches it with unavailable rows.
    const { workspace } = mergeDraftCapitalTeams(
      { teams: [] },
      UNAVAILABLE.teamTotals,
      { mode: "force" },
    );
    const budgets = (workspace.teams || []).map((t) => t.budget ?? t.initialBudget);
    expect(budgets).toEqual([0, 0]);
  });
});

describe("/trade stack — buildLeagueStacks", () => {
  it("builds no stacks on unavailable budgets (never zero stacks)", () => {
    expect(buildLeagueStacks(UNAVAILABLE, {}, {})).toBeNull();
  });

  it("still builds stacks on real budgets", () => {
    const stacks = buildLeagueStacks(AVAILABLE, {}, {});
    expect(Object.values(stacks).sort((a, b) => a - b)).toEqual([500, 700]);
  });
});
