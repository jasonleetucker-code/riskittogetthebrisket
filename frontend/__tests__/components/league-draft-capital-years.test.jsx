/**
 * /league Draft Capital tab — year selector rendering (owner request
 * 2026-10-01).
 *
 * The section renders backend numbers; it never re-derives capital.  Pinned:
 *   - All Years renders the existing `teamTotals` in its existing order;
 *   - a season renders `teamTotalsByYear[season]` — re-ranked, re-valued, the
 *     pick lists filtered to that season;
 *   - a team with no picks in the season stays, with an explicit
 *     "No <season> picks";
 *   - capital that is unknown (every pick unpriced) renders "—", never $0;
 *   - an obsolete `?year=` renders All Years and asks the router to drop it;
 *   - a single-season (workbook) board renders exactly as before — no notes.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/dynamic", () => ({ default: () => () => null }));

import DraftCapitalSection from "@/app/league/sections/draft-capital.jsx";

function pick(season, round, slot, owner, original, dollars) {
  return {
    pick: `${round}.${String(slot).padStart(2, "0")}`,
    season,
    round,
    slot,
    overallPick: (round - 1) * 3 + slot,
    currentOwner: owner,
    originalOwner: original,
    isTraded: owner !== original,
    dollarValue: dollars,
    adjustedDollarValue: dollars,
    isUnpriced: dollars == null,
  };
}

// Three teams, two seasons, Sleeper-derived (slots are stand-ins).
// Alpha owns Gamma's 2027 1st; Gamma owns nothing in 2027.
// 2028 is unpriced for Beta's 2nd.
const MULTI = {
  source: "sleeper_derived",
  season: 2027,
  numTeams: 3,
  draftRounds: 2,
  totalBudget: 1200,
  availableYears: [2027, 2028],
  picks: [
    pick(2027, 1, 1, "Alpha", "Alpha", 300),
    pick(2027, 1, 3, "Alpha", "Gamma", 300),
    pick(2027, 1, 2, "Beta", "Beta", 300),
    pick(2027, 2, 1, "Alpha", "Alpha", 20),
    pick(2027, 2, 2, "Beta", "Beta", 20),
    pick(2027, 2, 3, "Alpha", "Gamma", 20),
    pick(2028, 1, 1, "Gamma", "Alpha", 70),
    pick(2028, 1, 2, "Gamma", "Beta", 70),
    pick(2028, 1, 3, "Gamma", "Gamma", 70),
    pick(2028, 2, 1, "Alpha", "Alpha", 10),
    pick(2028, 2, 2, "Beta", "Beta", null),
    pick(2028, 2, 3, "Gamma", "Gamma", 10),
  ],
  teamTotals: [
    {
      team: "Alpha",
      auctionDollars: 650,
      draftCapitalByYear: { 2027: 640, 2028: 10 },
      pickCount: 5,
      unpricedPickCount: 0,
    },
    {
      team: "Beta",
      auctionDollars: 320,
      draftCapitalByYear: { 2027: 320, 2028: null },
      pickCount: 3,
      unpricedPickCount: 1,
    },
    {
      team: "Gamma",
      auctionDollars: 220,
      draftCapitalByYear: { 2027: 0, 2028: 220 },
      pickCount: 4,
      unpricedPickCount: 0,
    },
  ],
  teamTotalsByYear: {
    2027: [
      { team: "Alpha", auctionDollars: 640, rank: 1, pickCount: 4, unpricedPickCount: 0 },
      { team: "Beta", auctionDollars: 320, rank: 2, pickCount: 2, unpricedPickCount: 0 },
      { team: "Gamma", auctionDollars: 0, rank: 3, pickCount: 0, unpricedPickCount: 0 },
    ],
    2028: [
      { team: "Gamma", auctionDollars: 220, rank: 1, pickCount: 4, unpricedPickCount: 0 },
      { team: "Alpha", auctionDollars: 10, rank: 2, pickCount: 1, unpricedPickCount: 0 },
      { team: "Beta", auctionDollars: null, rank: null, pickCount: 1, unpricedPickCount: 1 },
    ],
  },
  yearSummaries: {
    2027: { totalDollars: 960, pickCount: 6, pricedPickCount: 6, unpricedPickCount: 0, teamsWithPicks: 2 },
    2028: { totalDollars: 230, pickCount: 6, pricedPickCount: 5, unpricedPickCount: 1, teamsWithPicks: 3 },
  },
};

function stubFetch(body) {
  globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => body }));
}

function teamOrder() {
  return screen
    .getAllByTestId("draft-capital-team-row")
    .map((row) => row.querySelector(".truncate").textContent);
}

function rowFor(team) {
  return screen
    .getAllByTestId("draft-capital-team-row")
    .find((row) => row.querySelector(".truncate").textContent === team);
}

describe("DraftCapitalSection year selector", () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => stubFetch(MULTI));
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  it("All Years renders the existing totals, order and a per-year breakdown", async () => {
    render(<DraftCapitalSection yearParam="" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(3));
    expect(teamOrder()).toEqual(["Alpha", "Beta", "Gamma"]);
    expect(within(rowFor("Alpha")).getByText("$650")).toBeInTheDocument();
    const breakdown = within(rowFor("Beta")).getByTestId("draft-capital-year-breakdown");
    expect(breakdown.textContent).toBe("2027 $320 · 2028 unpriced");
    // Selector offers exactly the backend's seasons.
    const radios = screen.getAllByRole("radio").map((r) => r.textContent);
    expect(radios).toEqual(["All Years", "2027", "2028"]);
    expect(screen.getByRole("radio", { name: "All Years" })).toHaveAttribute("aria-checked", "true");
    // Every season's picks are listed under All Years, season-qualified.
    expect(within(rowFor("Alpha")).getByText(/'28 R2/)).toBeInTheDocument();
  });

  it("a season re-values, re-ranks and filters the pick lists", async () => {
    render(<DraftCapitalSection yearParam="2028" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(3));
    expect(teamOrder()).toEqual(["Gamma", "Alpha", "Beta"]);
    expect(within(rowFor("Gamma")).getByText("$220")).toBeInTheDocument();
    // Alpha's 2027 picks are not in the 2028 view.
    expect(within(rowFor("Alpha")).queryByText(/R1/)).toBeNull();
    // Unknown capital is "—", never $0, and the unpriced pick is counted.
    const beta = rowFor("Beta");
    expect(within(beta).getByTitle("None of these picks could be priced").textContent).toBe("—");
    // ...and it is unranked rather than ranked last as if it were zero.
    expect(beta.querySelector(".font-mono").textContent).toBe("—");
    expect(within(beta).queryByText("$0")).toBeNull();
    expect(within(beta).getByText("(1 unpriced)")).toBeInTheDocument();
    expect(screen.getByTestId("draft-capital-notes").textContent).toMatch(/1 of 6 picks could not be priced/);
    expect(screen.getByRole("radio", { name: "2028" })).toHaveAttribute("aria-checked", "true");
  });

  it("a team with no picks in the season stays, at zero, with an explicit note", async () => {
    render(<DraftCapitalSection yearParam="2027" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(3));
    const gamma = rowFor("Gamma");
    expect(within(gamma).getByText("$0")).toBeInTheDocument();
    expect(within(gamma).getByTestId("draft-capital-no-picks").textContent).toBe("No 2027 picks");
    // The acquired 1st counts for its current owner.
    expect(within(rowFor("Alpha")).getByText("4pk")).toBeInTheDocument();
  });

  it("selecting a season writes it through setYear; All Years clears it", async () => {
    const setYear = vi.fn();
    render(<DraftCapitalSection yearParam="2027" setYear={setYear} />);
    await waitFor(() => screen.getByRole("radio", { name: "2028" }));
    fireEvent.click(screen.getByRole("radio", { name: "2028" }));
    expect(setYear).toHaveBeenLastCalledWith("2028");
    fireEvent.click(screen.getByRole("radio", { name: "All Years" }));
    expect(setYear).toHaveBeenLastCalledWith(null);
  });

  it("an obsolete ?year= renders All Years and drops the param", async () => {
    const setYear = vi.fn();
    render(<DraftCapitalSection yearParam="2026" setYear={setYear} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(3));
    expect(teamOrder()).toEqual(["Alpha", "Beta", "Gamma"]);
    expect(screen.getByRole("radio", { name: "All Years" })).toHaveAttribute("aria-checked", "true");
    await waitFor(() => expect(setYear).toHaveBeenCalledWith(null));
  });

  it("a single-season workbook board renders as before", async () => {
    stubFetch({
      season: 2027,
      numTeams: 2,
      draftRounds: 1,
      totalBudget: 1200,
      availableYears: [2027],
      picks: [
        { pick: "1.01", season: 2027, round: 1, pickInRound: 1, overallPick: 1, currentOwner: "Ann", originalOwner: "Ann", isTraded: false, dollarValue: 700, adjustedDollarValue: 700 },
        { pick: "1.02", season: 2027, round: 1, pickInRound: 2, overallPick: 2, currentOwner: "Ann", originalOwner: "Bob", isTraded: true, dollarValue: 500, adjustedDollarValue: 500 },
      ],
      teamTotals: [
        { team: "Ann", auctionDollars: 1200, draftCapitalByYear: { 2027: 1200 }, pickCount: 2, unpricedPickCount: 0 },
        { team: "Bob", auctionDollars: 0, draftCapitalByYear: { 2027: 0 }, pickCount: 0, unpricedPickCount: 0 },
      ],
      teamTotalsByYear: {
        2027: [
          { team: "Ann", auctionDollars: 1200, rank: 1, pickCount: 2, unpricedPickCount: 0 },
          { team: "Bob", auctionDollars: 0, rank: 2, pickCount: 0, unpricedPickCount: 0 },
        ],
      },
      yearSummaries: { 2027: { totalDollars: 1200, pickCount: 2, pricedPickCount: 2, unpricedPickCount: 0, teamsWithPicks: 1 } },
    });
    render(<DraftCapitalSection yearParam="" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(2));
    expect(screen.queryByTestId("draft-capital-notes")).toBeNull();
    expect(screen.queryByTestId("draft-capital-year-breakdown")).toBeNull();
    // Exact slots stay on the workbook board, as before.
    expect(within(rowFor("Ann")).getByText("1.02*")).toBeInTheDocument();
    expect(screen.getByText(/2027 draft · 2 teams · 1 rounds · \$1200 total budget/)).toBeInTheDocument();
  });

  it("a payload without per-season views offers no selector", async () => {
    const { availableYears, teamTotalsByYear, yearSummaries, ...legacy } = MULTI;
    void availableYears;
    void teamTotalsByYear;
    void yearSummaries;
    stubFetch(legacy);
    render(<DraftCapitalSection yearParam="2028" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(3));
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(teamOrder()).toEqual(["Alpha", "Beta", "Gamma"]);
  });
});
