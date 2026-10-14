import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: "",
    rows: [],
    rawData: {
      sleeper: {
        teams: [
          { name: "My Team", ownerId: "me", players: ["Send Alpha"] },
          {
            name: "Other Team",
            ownerId: "them",
            players: ["Target Bob", "Target Charlie"],
          },
        ],
      },
    },
  }),
}));

vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedLeagueKey: "dynasty_main", selectedOwnerId: "me" }),
}));

vi.mock("@/lib/market-arbitrage", async (importOriginal) => ({
  ...(await importOriginal()),
  buildArbitrageRows: () => [],
}));

vi.mock("@/lib/trade-share", () => ({
  buildShareUrl: () => "/trade",
}));

import ArbitragePage from "@/app/arbitrage/page";

function response(payload) {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  };
}

function trade(receiveName) {
  return {
    give: [
      {
        name: "Send Alpha",
        position: "WR",
        modelValue: 3000,
        ktcValue: 3200,
      },
    ],
    receive: [
      {
        name: receiveName,
        position: "RB",
        modelValue: 3400,
        ktcValue: 3000,
      },
    ],
    boardDelta: 400,
    ktcDelta: 200,
    arbitrageScore: 12.5,
    packageSize: "1-for-1",
    marketsUsed: ["ktc"],
    mixedMarket: false,
  };
}

function payload(receiveName) {
  return {
    trades: [trade(receiveName)],
    warnings: [],
    metadata: {
      totalQualified: 1,
      returned: 1,
      assetPoolSize: 4,
      marketCoveragePercent: 100,
      assetsUnpricedByBoard: 0,
      mixedMarketTrades: 0,
      valueSource: "rankDerivedValue",
    },
  };
}

function requestBody(call) {
  return JSON.parse(call[1].body);
}

function arbitrageControl(call) {
  const body = JSON.parse(call[1].body);
  return body.opponentTeams.find(
    (item) => item && typeof item === "object" && item.__arbitrageControl,
  )?.__arbitrageControl;
}

describe("/arbitrage package refinement", () => {
  let originalFetch;

  beforeEach(() => {
    originalFetch = global.fetch;
    window.localStorage.clear();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("requests equal-count packages; Skip reruns without that target (incoming only)", async () => {
    const user = userEvent.setup();
    let resolveSkippedSearch;

    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(response(payload("Target Bob")))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSkippedSearch = () => resolve(response(payload("Target Charlie")));
          }),
      )
      .mockResolvedValueOnce(response(payload("Target Bob")));

    render(<ArbitragePage />);

    await user.click(screen.getByRole("button", { name: "Find trade packages" }));

    const skipBob = await screen.findByRole("button", {
      name: "Don't target Target Bob in this scan",
    });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(arbitrageControl(global.fetch.mock.calls[0])).toEqual({
      equalCountOnly: true,
      skipTargets: [],
    });
    expect(requestBody(global.fetch.mock.calls[0]).refinement).toEqual({ lock: [], exclude: [] });

    await user.click(skipBob);

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(arbitrageControl(global.fetch.mock.calls[1])).toEqual({
      equalCountOnly: true,
      skipTargets: ["Target Bob"],
    });
    // Skip is a search filter, never a constraint: it does not travel as
    // refinement and is never stored.
    expect(requestBody(global.fetch.mock.calls[1]).refinement).toEqual({ lock: [], exclude: [] });
    expect(window.localStorage.length).toBe(0);
    expect(screen.getByRole("button", { name: "Remove skip: Target Bob" })).toBeTruthy();

    await act(async () => {
      resolveSkippedSearch();
    });
    await screen.findByRole("button", { name: "Don't target Target Charlie in this scan" });

    await user.click(screen.getByRole("button", { name: "Remove skip: Target Bob" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(3));
    expect(arbitrageControl(global.fetch.mock.calls[2])).toEqual({
      equalCountOnly: true,
      skipTargets: [],
    });
  });

  it("LOCK and EXCLUDE are outgoing-only, mutually exclusive, regenerate, and persist until cleared", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(response(payload("Target Bob")));
    render(<ArbitragePage />);

    await user.click(screen.getByRole("button", { name: "Find trade packages" }));
    await user.click(
      await screen.findByRole("button", { name: "Lock Send Alpha into every package" }),
    );
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(requestBody(global.fetch.mock.calls[1]).refinement).toEqual({
      lock: ["Send Alpha"],
      exclude: [],
    });
    const key = "rit.refinement.v1:me:dynasty_main:arbitrage:My Team|all";
    expect(JSON.parse(window.localStorage.getItem(key))).toEqual({
      lock: ["Send Alpha"],
      exclude: [],
    });
    // The receive side never offers LOCK / EXCLUDE.
    expect(screen.queryByRole("button", { name: "Lock Target Bob into every package" })).toBeNull();

    await user.click(
      await screen.findByRole("button", { name: "Exclude Send Alpha from outgoing packages" }),
    );
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(3));
    expect(requestBody(global.fetch.mock.calls[2]).refinement).toEqual({
      lock: [],
      exclude: ["Send Alpha"],
    });

    await user.click(screen.getByRole("button", { name: "Clear refinements" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(4));
    expect(requestBody(global.fetch.mock.calls[3]).refinement).toEqual({ lock: [], exclude: [] });
    expect(window.localStorage.getItem(key)).toBeNull();
  });

  it("restores a saved refinement for this team and opponent context", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      "rit.refinement.v1:me:dynasty_main:arbitrage:My Team|all",
      JSON.stringify({ lock: [], exclude: ["Send Alpha"] }),
    );
    global.fetch = vi.fn().mockResolvedValue(response(payload("Target Bob")));
    render(<ArbitragePage />);

    expect(await screen.findByRole("button", { name: "Remove exclusion: Send Alpha" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Find trade packages" }));
    expect(requestBody(global.fetch.mock.calls[0]).refinement).toEqual({
      lock: [],
      exclude: ["Send Alpha"],
    });
  });

  it("sends Team Context ON by default and re-scans in Asset-only when switched (C3-CTX-01)", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn().mockResolvedValue(response(payload("Target Bob")));
    render(<ArbitragePage />);

    await user.click(screen.getByRole("button", { name: "Find trade packages" }));
    await screen.findByRole("button", { name: "Don't target Target Bob in this scan" });
    expect(JSON.parse(global.fetch.mock.calls[0][1].body).useTeamContext).toBe(true);

    await user.click(screen.getByRole("radio", { name: "Asset only" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(JSON.parse(global.fetch.mock.calls[1][1].body).useTeamContext).toBe(false);
  });

  it("shows both teams' roster consequence and names the counterparty", async () => {
    const user = userEvent.setup();
    const body = payload("Target Bob");
    body.trades[0].counterparty = "Other Team";
    body.trades[0].rosterCapacity = {
      requiresDrops: true,
      forcedDropsAreUpperBound: false,
      rosterLimit: 58,
      forcedDrops: [{ name: "Bench Guy" }],
    };
    body.trades[0].counterpartyRosterCapacity = {
      requiresDrops: null,
      rosterLimit: 58,
      forcedDrops: [],
    };
    global.fetch = vi.fn().mockResolvedValue(response(body));
    render(<ArbitragePage />);

    await user.click(screen.getByRole("button", { name: "Find trade packages" }));
    const list = await screen.findByRole("list", { name: "Roster consequences" });
    expect(list).toHaveTextContent("Your roster: must release 1: Bench Guy");
    expect(list).toHaveTextContent(
      "Other Team's roster: may need a release (taxi occupancy unknown)",
    );
  });

  it("labels a derived pick market value as derived, never a native price", async () => {
    const user = userEvent.setup();
    const body = payload("Target Bob");
    body.trades[0].give.push({
      name: "2027 1st (My Team)",
      position: "PICK",
      modelValue: 5800,
      ktcValue: 5967,
      marketDerivation: { basis: "plain_ktc_tier_average", isNativeMarketPrice: false },
    });
    global.fetch = vi.fn().mockResolvedValue(response(body));
    render(<ArbitragePage />);
    await user.click(screen.getByRole("button", { name: "Find trade packages" }));
    expect(await screen.findByText(/KTC tier average — slot unknown/)).toBeInTheDocument();
  });

  it("drops a stale scan when the mode is switched mid-flight", async () => {
    const user = userEvent.setup();
    let resolveFirst;
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(response(payload("Target Bob")))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = () => resolve(response(payload("Stale Asset Pick")));
          }),
      )
      .mockResolvedValueOnce(response(payload("Target Charlie")));
    render(<ArbitragePage />);
    await user.click(screen.getByRole("button", { name: "Find trade packages" }));
    await screen.findByRole("button", { name: "Don't target Target Bob in this scan" });

    await user.click(screen.getByRole("radio", { name: "Asset only" })); // slow, will be stale
    await user.click(screen.getByRole("radio", { name: "Team context" })); // latest
    await screen.findByRole("button", { name: "Don't target Target Charlie in this scan" });
    await act(async () => {
      resolveFirst();
    });
    expect(
      screen.queryByRole("button", { name: "Don't target Stale Asset Pick in this scan" }),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "Don't target Target Charlie in this scan" }),
    ).toBeTruthy();
  });
});
