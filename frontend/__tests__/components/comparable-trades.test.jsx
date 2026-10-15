/**
 * TC-09 comparable mode of the /trade real-trades panel, and the TC-08
 * /market/trade-database page.
 *
 * Pins: per-side identity refs (two sides, a third side reported not
 * dropped silently); the mode switch requests the comparable endpoint and
 * renders "% similar" plus the reasons, never as a value; the empty state
 * explains below-minimum candidates; the database page sends only set
 * filters, says how many rows a filter hid because the fact is unknown, and
 * never resolves an ambiguous player name.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import RecentRealTrades from "@/components/trade/RecentRealTrades";
import {
  comparableQueryFromSides,
  comparableQueryString,
  databaseQueryString,
  excludedUnknownText,
  similarityText,
  uniquePlayerIndex,
} from "@/lib/recent-real-trades";

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    rows: [
      { name: "Justin Jefferson", playerId: "6794", pos: "WR" },
      { name: "Mike Williams", playerId: "1", pos: "WR" },
      { name: "Mike Williams", playerId: "2", pos: "WR" },
      { name: "2027 Early 1st", pos: "PICK", assetClass: "pick" },
    ],
  }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedLeagueKey: "dynasty_main" }),
}));

const SIDES = [
  { assets: [{ name: "Justin Jefferson", playerId: "6794", assetClass: "offense" }] },
  {
    assets: [
      { name: "2027 Early 1st", assetClass: "pick" },
      { name: "Owned", assetClass: "pick", assetId: "pick:dynasty_main:2028:r1:o3" },
    ],
  },
  { assets: [{ name: "Ja'Marr Chase", playerId: "7564", assetClass: "offense" }] },
];

const TRADE = {
  id: "aaaaaaaaaaaaaaaa",
  occurredDate: "2026-10-01",
  sidesSemantics: "packages_orientation_unstated",
  provenance: ["KTC_MARKET"],
  sides: [
    [{ kind: "player", label: "Justin Jefferson", match: "exact" }],
    [{ kind: "pick", label: "2027 Early 1st", match: "exact" }],
  ],
  formatTags: { superflex: true, teams: 12 },
  formatTiming: "unknown",
  formatMatch: { appliesToThisLeague: true, disposition: "BROAD_CONTEXT" },
};

const COMP_BODY = {
  state: "ok",
  since: "2025-10-08",
  ledger: { builtAt: "2026-10-08T08:52:00Z" },
  query: {
    sideA: { players: ["6794"], picks: [], pickAssetIds: [], unresolved: [] },
    sideB: { players: [], picks: ["2027 Early 1st"], pickAssetIds: [], unresolved: [] },
  },
  methodology: {
    status: "PRIOR_UNVALIDATED",
    notIncluded: { packageValueProximity: "Deferred: needs at-the-time values." },
  },
  samplingBiases: [],
  withheld: {},
  truncated: true,
  candidates: 4,
  trades: [
    {
      ...TRADE,
      comparability: {
        score: 0.8234,
        components: {},
        reasons: [
          { key: "sharedExact", text: "Same asset: Justin Jefferson, 2027 Early 1st" },
          { key: "topology", text: "Same 1-for-1 shape" },
        ],
      },
    },
  ],
};

function mockFetch(impl) {
  const fn = vi.fn(impl);
  globalThis.fetch = fn;
  return fn;
}

describe("comparable query helpers", () => {
  it("splits refs per side and reports extra sides", () => {
    const q = comparableQueryFromSides(SIDES);
    expect(q.a).toEqual({ players: ["6794"], picks: [], pickAssetIds: [] });
    expect(q.b).toEqual({
      players: [],
      picks: ["2027 Early 1st"],
      pickAssetIds: ["pick:dynasty_main:2028:r1:o3"],
    });
    expect(q.extraSides).toBe(1);
    const qs = new URLSearchParams(comparableQueryString(q, "dynasty_main"));
    expect(qs.get("aPlayers")).toBe("6794");
    expect(qs.get("bPicks")).toBe("2027 Early 1st");
    expect(qs.get("bPickAssetIds")).toBe("pick:dynasty_main:2028:r1:o3");
    expect(qs.get("leagueKey")).toBe("dynasty_main");
    expect(qs.has("bPlayers")).toBe(false);
  });

  it("similarity is a percentage of relevance, null when absent", () => {
    expect(similarityText({ score: 0.8234 })).toBe("82% similar");
    expect(similarityText({})).toBeNull();
    expect(similarityText(null)).toBeNull();
  });

  it("database query drops unset and 'any' filters", () => {
    const qs = new URLSearchParams(
      databaseQueryString({ teams: "12", superflex: "any", since: "", shape: " 2x1 " }, "k"),
    );
    expect([...qs.keys()].sort()).toEqual(["leagueKey", "shape", "teams"]);
    expect(qs.get("shape")).toBe("2x1");
  });

  it("explains unknown-fact exclusions in words", () => {
    expect(excludedUnknownText({ teams: 3, idp: 0 })).toBe(
      "Not shown because the filtered fact is not recorded: 3 with unknown team count.",
    );
    expect(excludedUnknownText({})).toBeNull();
  });

  it("indexes only names exactly one player carries", () => {
    const idx = uniquePlayerIndex([
      { name: "A", playerId: "1" },
      { name: "B", playerId: "2" },
      { name: "B", playerId: "3" },
      { name: "C", playerId: "4" },
      { name: "C" },
      { name: "2027 Early 1st", pos: "PICK", assetClass: "pick" },
    ]);
    expect([...idx.entries()]).toEqual([["A", "1"]]);
  });
});

describe("RecentRealTrades comparable mode", () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => {
    vi.useRealTimers();
    globalThis.fetch = realFetch;
  });

  it("switching mode requests the comparable endpoint and shows similarity + reasons", async () => {
    const fetchFn = mockFetch(async (url) => ({
      ok: true,
      json: async () =>
        String(url).includes("/comparable")
          ? COMP_BODY
          : { ...COMP_BODY, query: { players: [], picks: [], pickAssetIds: [], unresolved: [] }, trades: [TRADE] },
    }));
    render(<RecentRealTrades sides={SIDES} leagueKey="dynasty_main" />);
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(String(fetchFn.mock.calls[0][0])).toContain("/api/market/trades/reference?");
    fireEvent.click(screen.getByRole("radio", { name: "Most comparable" }));
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    await waitFor(() => expect(screen.getByText("82% similar")).toBeTruthy());
    const lastUrl = String(fetchFn.mock.calls.at(-1)[0]);
    expect(lastUrl).toContain("/api/market/trades/comparable?");
    expect(lastUrl).toContain("aPlayers=6794");
    expect(screen.getByText("Same asset: Justin Jefferson, 2027 Early 1st")).toBeTruthy();
    expect(screen.getByText(/the other 1 side was not used/)).toBeTruthy();
    expect(screen.getByText(/most similar of 4 candidate trades/)).toBeTruthy();
    expect(screen.getByText(/never a price or a value/)).toBeTruthy();
  });

  it("an empty comparable result names the below-minimum candidates", async () => {
    mockFetch(async () => ({
      ok: true,
      json: async () => ({ ...COMP_BODY, trades: [], truncated: false, belowMinScore: 3 }),
    }));
    render(<RecentRealTrades sides={SIDES} leagueKey="dynasty_main" />);
    fireEvent.click(screen.getByRole("radio", { name: "Most comparable" }));
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    await waitFor(() => expect(screen.getByText("No comparable trades")).toBeTruthy());
    expect(screen.getByText(/3 recorded trades shared an asset/)).toBeTruthy();
  });
});

describe("/market/trade-database", () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  async function renderPage(body = null) {
    const fetchFn = mockFetch(async () => ({
      ok: true,
      json: async () =>
        body || {
          state: "ok",
          filters: { since: "2025-10-08", until: null },
          ledger: {},
          trades: [TRADE],
          hasMore: true,
          nextCursor: { beforeDate: "2026-09-30", skip: 1 },
          excludedUnknown: { teams: 2 },
          excludedNotApplicable: { ktcTepLevel: 3 },
          withheld: {},
          notes: [],
          samplingBiases: [],
          notSupported: { valueBand: "Needs at-the-time values." },
          maxLookbackDays: 1095,
        },
    }));
    const { default: Page } = await import("@/app/market/trade-database/page");
    render(<Page />);
    await waitFor(() => expect(fetchFn).toHaveBeenCalled());
    return fetchFn;
  }

  it("loads, renders rows, the unknown-exclusion note and paging", async () => {
    const fetchFn = await renderPage();
    await waitFor(() => expect(screen.getByText("Justin Jefferson")).toBeTruthy());
    expect(screen.getByRole("heading", { name: "Trade Database" })).toBeTruthy();
    expect(screen.getByText(/2 with unknown team count/)).toBeTruthy();
    expect(screen.getByText(/3 non-KTC trades hidden/)).toBeTruthy();
    expect(String(fetchFn.mock.calls[0][0])).toContain("leagueKey=dynasty_main");
    fireEvent.click(screen.getByRole("button", { name: "Older" }));
    await waitFor(() => {
      const url = String(fetchFn.mock.calls.at(-1)[0]);
      expect(url).toContain("beforeDate=2026-09-30");
      expect(url).toContain("skip=1");
    });
    // The page label renders after the second fetch RESOLVES, not when it is
    // called: wait for the label itself (a bare getByText raced under CI load).
    expect(await screen.findByText("Page 2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Newer" }));
    await waitFor(() => expect(String(fetchFn.mock.calls.at(-1)[0])).not.toContain("beforeDate"));
  });

  it("applies set filters only and refuses an ambiguous player name", async () => {
    const fetchFn = await renderPage();
    fireEvent.change(screen.getByLabelText("Teams"), { target: { value: "12" } });
    const asset = screen.getByLabelText("Player or pick");
    fireEvent.change(asset, { target: { value: "Mike Williams" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByText(/a name two players share/)).toBeTruthy();
    fireEvent.change(asset, { target: { value: "Justin Jefferson" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => {
      const url = String(fetchFn.mock.calls.at(-1)[0]);
      expect(url).toContain("teams=12");
      expect(url).toContain("players=6794");
      expect(url).not.toContain("superflex");
    });
    expect(window.location.search).toContain("teams=12");
  });

  it("a 400 says the filter was not understood", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 400,
      json: async () => ({ error: "bad_request", message: "shape must look like 2x1" }),
    }));
    const { default: Page } = await import("@/app/market/trade-database/page");
    render(<Page />);
    await waitFor(() => expect(screen.getByText("Filter not understood")).toBeTruthy());
    expect(screen.getByText(/shape must look like 2x1/)).toBeTruthy();
  });
});
