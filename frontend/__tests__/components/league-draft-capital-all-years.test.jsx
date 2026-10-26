/**
 * /league Draft Capital — every Sleeper draft class (owner directive
 * 2026-10-17).
 *
 * The default league's workbook carries ONE class in `picks`; the league's
 * other owned classes arrive in `additionalClassPicks` and the backend's
 * per-year views / `allYearsTeamTotals` cover all of them.  Pinned:
 *   - the selector is data-driven: All Years | 2027 | 2028 | 2029;
 *   - All Years renders `allYearsTeamTotals` (each class once), not the
 *     workbook-only `teamTotals`;
 *   - `?year=2028` renders only 2028 picks and 2028's ranking;
 *   - future classes show round only (no invented slot) and are labelled
 *     estimated; the workbook class's slots are labelled projected;
 *   - acquired / traded-away counts come from the backend;
 *   - unpriced is "?" / "—", never $0;
 *   - Batch E: every class is on the rookie-auction formula; classes on the
 *     frozen 2026 inputs carry the provisional label; a legacy payload's
 *     retired interim curve keeps its own label.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/dynamic", () => ({ default: () => () => null }));

import DraftCapitalSection from "@/app/league/sections/draft-capital.jsx";
import {
  draftCapitalAllPicks,
  draftCapitalBudgetPolicy,
  draftCapitalInterimSeasons,
  draftCapitalPickLabel,
  draftCapitalProvisionalSeasons,
  draftCapitalSlotsAreStandIns,
  draftCapitalTeamRows,
  draftCapitalYearSummary,
} from "@/lib/draft-capital-years";

function wbPick(round, slot, owner, original, dollars) {
  return {
    pick: `${round}.${String(slot).padStart(2, "0")}`,
    season: 2027,
    round,
    pickInRound: slot,
    overallPick: (round - 1) * 2 + slot,
    currentOwner: owner,
    originalOwner: original,
    isTraded: owner !== original,
    dollarValue: dollars,
    adjustedDollarValue: dollars,
    slotStatus: "projected",
    valueBasis: "workbook",
    dollarValueEstimated: false,
  };
}

function futurePick(season, round, origin, owner, dollars) {
  return {
    pick: `R${round}`,
    season,
    round,
    pickInRound: null,
    slot: null,
    slotStatus: "unknown",
    currentOwner: owner,
    originalOwner: origin,
    isTraded: owner !== origin,
    assetId: `pick:lg:${season}:r${round}:o${origin === "Ann" ? 1 : 2}`,
    dollarValue: dollars,
    adjustedDollarValue: dollars,
    isUnpriced: dollars == null,
    dollarValueEstimated: true,
    curveMethod: dollars == null ? "none" : "workbook_rookie_auction",
    inputMode: dollars == null ? null : "frozen_fallback",
  };
}

const PAYLOAD = {
  season: 2027,
  numTeams: 2,
  draftRounds: 2,
  totalBudget: 1200,
  coveredPickYears: [2027],
  availableYears: [2027, 2028, 2029],
  budgetPolicy: {
    basis: "per_class_pool",
    budget: 1200,
    allYearsBudget: 3600,
    seasons: [2027, 2028, 2029],
    unpricedClasses: [],
    status: "owner_confirmed",
    decidedBy: "owner",
    decidedAt: "2026-10-18",
    classCurveMethods: {
      2027: "workbook_rookie_auction",
      2028: "workbook_rookie_auction",
      2029: "workbook_rookie_auction",
    },
    interimCurveLabel: null,
    provisionalClasses: [2028, 2029],
    classes: {
      2027: { budgetBasis: "per_class_pool", inputMode: null, provisional: false },
      2028: {
        budgetBasis: "per_class_pool",
        inputMode: "frozen_fallback",
        provisional: true,
        spineYears: [2024, 2025, 2026],
        curveId: "draft_data_workbook_v1|frozen_fallback:2026_spreadsheet_baseline|spine:2024-2025-2026",
      },
      2029: {
        budgetBasis: "per_class_pool",
        inputMode: "frozen_fallback",
        provisional: true,
        spineYears: [2024, 2025, 2026],
        curveId: "draft_data_workbook_v1|frozen_fallback:2026_spreadsheet_baseline|spine:2024-2025-2026",
      },
    },
  },
  picks: [
    wbPick(1, 1, "Ann", "Ann", 700),
    wbPick(1, 2, "Bob", "Bob", 300),
    wbPick(2, 1, "Bob", "Ann", 120),
    wbPick(2, 2, "Bob", "Bob", 80),
  ],
  additionalClassPicks: [
    futurePick(2028, 1, "Ann", "Ann", 400),
    futurePick(2028, 1, "Bob", "Ann", 400),
    futurePick(2028, 2, "Ann", "Ann", 200),
    futurePick(2028, 2, "Bob", "Bob", 200),
    futurePick(2029, 1, "Ann", "Ann", 600),
    futurePick(2029, 1, "Bob", "Bob", 600),
    futurePick(2029, 2, "Ann", "Ann", null),
    futurePick(2029, 2, "Bob", "Bob", null),
  ],
  // The workbook class only — the auction budgets /draft and /trade read.
  teamTotals: [
    { team: "Ann", auctionDollars: 700 },
    { team: "Bob", auctionDollars: 500 },
  ],
  allYearsTeamTotals: [
    { team: "Ann", auctionDollars: 2300, rank: 1, pickCount: 6, unpricedPickCount: 1, acquiredPickCount: 1, tradedAwayPickCount: 1, draftCapitalByYear: { 2027: 700, 2028: 1000, 2029: 600 } },
    { team: "Bob", auctionDollars: 1300, rank: 2, pickCount: 6, unpricedPickCount: 1, acquiredPickCount: 1, tradedAwayPickCount: 1, draftCapitalByYear: { 2027: 500, 2028: 200, 2029: 600 } },
  ],
  allYearsSummary: { totalDollars: 3600, pickCount: 12, pricedPickCount: 10, unpricedPickCount: 2, teamsWithPicks: 2 },
  teamTotalsByYear: {
    2027: [
      { team: "Ann", auctionDollars: 700, rank: 1, pickCount: 1, unpricedPickCount: 0, acquiredPickCount: 0, tradedAwayPickCount: 1 },
      { team: "Bob", auctionDollars: 500, rank: 2, pickCount: 3, unpricedPickCount: 0, acquiredPickCount: 1, tradedAwayPickCount: 0 },
    ],
    2028: [
      { team: "Ann", auctionDollars: 1000, rank: 1, pickCount: 3, unpricedPickCount: 0, acquiredPickCount: 1, tradedAwayPickCount: 0 },
      { team: "Bob", auctionDollars: 200, rank: 2, pickCount: 1, unpricedPickCount: 0, acquiredPickCount: 0, tradedAwayPickCount: 1 },
    ],
    2029: [
      { team: "Ann", auctionDollars: 600, rank: 1, pickCount: 2, unpricedPickCount: 1, acquiredPickCount: 0, tradedAwayPickCount: 0 },
      { team: "Bob", auctionDollars: 600, rank: 2, pickCount: 2, unpricedPickCount: 1, acquiredPickCount: 0, tradedAwayPickCount: 0 },
    ],
  },
  yearSummaries: {
    2027: { totalDollars: 1200, pickCount: 4, pricedPickCount: 4, unpricedPickCount: 0, teamsWithPicks: 2 },
    2028: { totalDollars: 1200, pickCount: 4, pricedPickCount: 4, unpricedPickCount: 0, teamsWithPicks: 2 },
    2029: { totalDollars: 1200, pickCount: 4, pricedPickCount: 2, unpricedPickCount: 2, teamsWithPicks: 2 },
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

describe("draft-capital-years lib — every class", () => {
  it("All picks = workbook class + additional classes, each once", () => {
    const all = draftCapitalAllPicks(PAYLOAD);
    expect(all).toHaveLength(12);
    expect([...new Set(all.map((p) => p.season))]).toEqual([2027, 2028, 2029]);
    // A legacy payload without the field is just `picks`.
    expect(draftCapitalAllPicks({ picks: PAYLOAD.picks })).toHaveLength(4);
  });

  it("All Years rows span every class; legacy payloads fall back to teamTotals", () => {
    expect(draftCapitalTeamRows(PAYLOAD, null)[0].auctionDollars).toBe(2300);
    expect(draftCapitalTeamRows({ teamTotals: PAYLOAD.teamTotals }, null)[0].auctionDollars).toBe(700);
    expect(draftCapitalYearSummary(PAYLOAD, null).pickCount).toBe(12);
  });

  it("round-only labels for an unknown slot; per-season stand-in detection", () => {
    expect(draftCapitalPickLabel(PAYLOAD.additionalClassPicks[0])).toBe("R1");
    expect(draftCapitalPickLabel(PAYLOAD.picks[0])).toBe("1.01");
    expect(draftCapitalSlotsAreStandIns(PAYLOAD, PAYLOAD.additionalClassPicks)).toBe(true);
    expect(draftCapitalSlotsAreStandIns(PAYLOAD, PAYLOAD.picks)).toBe(false);
  });

  it("names the provisional seasons from the per-class blocks, limited to the screen", () => {
    expect(draftCapitalProvisionalSeasons(PAYLOAD, draftCapitalAllPicks(PAYLOAD))).toEqual([
      2028, 2029,
    ]);
    expect(draftCapitalProvisionalSeasons(PAYLOAD, PAYLOAD.picks)).toEqual([]);
    // Without the per-class blocks, the list, then the per-pick stamp answers.
    expect(
      draftCapitalProvisionalSeasons(
        { budgetPolicy: { provisionalClasses: [2029] } },
        PAYLOAD.additionalClassPicks,
      ),
    ).toEqual([2029]);
    expect(draftCapitalProvisionalSeasons({}, PAYLOAD.additionalClassPicks)).toEqual([2028, 2029]);
    // The retired interim curve: absent from a current payload.
    expect(draftCapitalInterimSeasons(PAYLOAD, draftCapitalAllPicks(PAYLOAD))).toEqual([]);
  });

  it("a legacy payload still names its interim-curve seasons", () => {
    const legacy = {
      budgetPolicy: {
        classCurveMethods: { 2027: "workbook_rookie_auction", 2028: "interim_generic_market" },
      },
    };
    expect(draftCapitalInterimSeasons(legacy, [{ season: 2028 }])).toEqual([2028]);
    // Without the per-class map, the per-pick stamp answers.
    expect(
      draftCapitalInterimSeasons({}, [
        { season: 2028, curveMethod: "interim_generic_market" },
        { season: 2027, curveMethod: "workbook_rookie_auction" },
      ]),
    ).toEqual([2028]);
  });

  it("reads the owner-decided per-class basis from the payload", () => {
    // Owner decision 2026-10-18: "$1,200 per draft class".
    expect(draftCapitalBudgetPolicy(PAYLOAD)).toMatchObject({
      perClass: true,
      allYearsBudget: 3600,
      pricedClassCount: 3,
      decided: true,
    });
    // A class the board cannot price at all holds no dollars.
    expect(
      draftCapitalBudgetPolicy({
        budgetPolicy: { ...PAYLOAD.budgetPolicy, allYearsBudget: 2400, unpricedClasses: [2029] },
      }),
    ).toMatchObject({ perClass: true, allYearsBudget: 2400, pricedClassCount: 2 });
    // Legacy payloads (no policy, or the retired shared pool) state no basis.
    expect(draftCapitalBudgetPolicy({ totalBudget: 1200 })).toMatchObject({
      perClass: false,
      allYearsBudget: 1200,
      decided: false,
      note: null,
    });
    expect(
      draftCapitalBudgetPolicy({
        totalBudget: 1200,
        budgetPolicy: { basis: "shared_multi_class_pool", budget: 1200, note: "One $1200 pool" },
      }),
    ).toMatchObject({ perClass: false, note: null });
  });
});

describe("DraftCapitalSection — every Sleeper draft year", () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => stubFetch(PAYLOAD));
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  it("offers All Years | 2027 | 2028 | 2029 from the payload", async () => {
    render(<DraftCapitalSection yearParam="" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(2));
    expect(screen.getAllByRole("radio").map((r) => r.textContent)).toEqual([
      "All Years",
      "2027",
      "2028",
      "2029",
    ]);
  });

  it("All Years ranks on every class combined and labels the basis", async () => {
    render(<DraftCapitalSection yearParam="" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(2));
    expect(teamOrder()).toEqual(["Ann", "Bob"]);
    expect(within(rowFor("Ann")).getByText("$2300")).toBeInTheDocument();
    expect(within(rowFor("Ann")).getByText("6pk")).toBeInTheDocument();
    expect(
      within(rowFor("Ann")).getByTestId("draft-capital-year-breakdown").textContent,
    ).toBe("2027 $700 · 2028 $1000 · 2029 $600");
    expect(screen.getAllByText(/\$3600 = 3 classes × \$1200/).length).toBeGreaterThan(0);
    expect(screen.getByTestId("draft-capital-budget-note").textContent).toMatch(
      /Each draft class is its own \$1200 pool/,
    );
    expect(screen.getByTestId("draft-capital-projected-note").textContent).toMatch(/2027 slots are projected/);
    // Batch E: the later classes are the rookie-auction formula on the frozen
    // 2026 provisional inputs — labelled provisional, never the retired interim.
    expect(screen.getByTestId("draft-capital-provisional-curve-note").textContent).toMatch(
      /^2028, 2029 dollars: provisional estimate — the rookie-auction formula on the frozen 2026/,
    );
    expect(screen.queryByTestId("draft-capital-interim-curve-note")).toBeNull();
    expect(screen.getByTestId("draft-capital-round-only-note")).toBeInTheDocument();
  });

  it("?year=2028 shows only 2028 picks, re-ranked, round-only, with trade counts", async () => {
    render(<DraftCapitalSection yearParam="2028" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(2));
    expect(screen.getByRole("radio", { name: "2028" })).toHaveAttribute("aria-checked", "true");
    const ann = rowFor("Ann");
    expect(within(ann).getByText("$1000")).toBeInTheDocument();
    expect(within(ann).getByText("3pk")).toBeInTheDocument();
    // Round only — a 2028 pick never claims a slot.
    expect(within(ann).getAllByText(/^R[12]\*?$/).length).toBe(3);
    expect(within(ann).queryByText(/1\.0\d/)).toBeNull();
    expect(within(ann).getByTestId("draft-capital-trade-counts").textContent).toBe(
      "(1 acquired · 0 traded away)",
    );
    expect(
      within(rowFor("Bob")).getByTestId("draft-capital-trade-counts").textContent,
    ).toBe("(0 acquired · 1 traded away)");
    expect(screen.getAllByText(/the 2028 class's own \$1200 pool/).length).toBeGreaterThan(0);
  });

  it("a class not on the frozen inputs carries no provisional label", async () => {
    render(<DraftCapitalSection yearParam="2027" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(2));
    expect(screen.queryByTestId("draft-capital-interim-curve-note")).toBeNull();
    expect(screen.queryByTestId("draft-capital-provisional-curve-note")).toBeNull();
  });

  it("a legacy interim payload keeps the interim label", async () => {
    stubFetch({
      ...PAYLOAD,
      budgetPolicy: {
        ...PAYLOAD.budgetPolicy,
        classes: undefined,
        provisionalClasses: undefined,
        classCurveMethods: { 2027: "workbook_rookie_auction", 2028: "interim_generic_market" },
      },
      additionalClassPicks: PAYLOAD.additionalClassPicks.map((p) => ({ ...p, inputMode: undefined })),
    });
    render(<DraftCapitalSection yearParam="2028" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(2));
    expect(screen.getByTestId("draft-capital-interim-curve-note").textContent).toMatch(
      /^2028 dollars: provisional estimate — final rookie-auction curve pending/,
    );
  });

  it("slots ordered by verified final standings are labelled as such", async () => {
    stubFetch({
      ...PAYLOAD,
      picks: PAYLOAD.picks.map((p) => ({ ...p, slotStatus: "final_standings" })),
    });
    render(<DraftCapitalSection yearParam="2027" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(2));
    expect(screen.getByTestId("draft-capital-final-order-note").textContent).toMatch(
      /2027 slots follow final regular-season standings/,
    );
    expect(screen.queryByTestId("draft-capital-projected-note")).toBeNull();
  });

  it("?year=2029 keeps unpriced picks visible and never $0", async () => {
    render(<DraftCapitalSection yearParam="2029" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(2));
    expect(screen.getByTestId("draft-capital-notes").textContent).toMatch(/2 of 4 picks could not be priced/);
    expect(within(rowFor("Ann")).getByText("R2?")).toBeInTheDocument();
    expect(screen.getAllByText("unpriced").length).toBe(2);
  });

  it("a legacy shared-pool payload never renders the retired shared-pool note", async () => {
    stubFetch({
      ...PAYLOAD,
      budgetPolicy: { basis: "shared_multi_class_pool", budget: 1200, allYearsBudget: 1200 },
    });
    render(<DraftCapitalSection yearParam="2028" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(2));
    expect(screen.queryByTestId("draft-capital-budget-note")).toBeNull();
    expect(document.body.textContent).not.toMatch(/pool is spread across every listed pick/);
  });

  it("unavailable auction budgets render as unavailable, never $0 (MISSING IS NEVER ZERO)", async () => {
    stubFetch({
      ...PAYLOAD,
      teamTotalsState: "unavailable",
      teamTotalsReason: "upcoming_class_unpriced",
      teamTotals: PAYLOAD.teamTotals.map((t) => ({ ...t, auctionDollars: null })),
    });
    render(<DraftCapitalSection yearParam="" setYear={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("draft-capital-team-row")).toHaveLength(2));
    expect(screen.getByTestId("draft-capital-budgets-unavailable").textContent).toMatch(
      /Auction budgets unavailable: the upcoming draft class has no priced picks\. Not shown as \$0\./,
    );
    // The simulator, which reads the budgets, is replaced by the stated state.
    expect(screen.getByTestId("draft-capital-simulator-unavailable").textContent).toMatch(
      /Trade simulator unavailable/,
    );
  });

  it("selecting 2029 writes it through setYear", async () => {
    const setYear = vi.fn();
    render(<DraftCapitalSection yearParam="" setYear={setYear} />);
    await waitFor(() => screen.getByRole("radio", { name: "2029" }));
    fireEvent.click(screen.getByRole("radio", { name: "2029" }));
    expect(setYear).toHaveBeenLastCalledWith("2029");
  });
});
