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

vi.mock("@/lib/market-arbitrage", () => ({
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
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("requests equal-count packages and X reruns without the player on either side", async () => {
    const user = userEvent.setup();
    let resolveExcludedSearch;

    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(response(payload("Target Bob")))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveExcludedSearch = () => resolve(response(payload("Target Charlie")));
          }),
      )
      .mockResolvedValueOnce(response(payload("Target Bob")));

    render(<ArbitragePage />);

    await user.click(screen.getByRole("button", { name: "Find trade packages" }));

    const excludeBob = await screen.findByRole("button", {
      name: "Exclude Target Bob from suggestions",
    });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(arbitrageControl(global.fetch.mock.calls[0])).toEqual({
      equalCountOnly: true,
      excludePlayers: [],
    });

    await user.click(excludeBob);

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(arbitrageControl(global.fetch.mock.calls[1])).toEqual({
      equalCountOnly: true,
      excludePlayers: ["Target Bob"],
    });

    // The UI records the exclusion immediately instead of waiting for the
    // network response. The backend test separately proves the rerun removes
    // the player from both pools before package enumeration.
    expect(
      screen.getByRole("button", { name: "Restore Target Bob to suggestions" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Exclude Target Bob from suggestions" }),
    ).toBeNull();

    await act(async () => {
      resolveExcludedSearch();
    });

    await screen.findByRole("button", {
      name: "Exclude Target Charlie from suggestions",
    });

    await user.click(
      screen.getByRole("button", { name: "Restore Target Bob to suggestions" }),
    );

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(3));
    expect(arbitrageControl(global.fetch.mock.calls[2])).toEqual({
      equalCountOnly: true,
      excludePlayers: [],
    });
    await screen.findByRole("button", {
      name: "Exclude Target Bob from suggestions",
    });
    expect(
      screen.queryByRole("button", { name: "Restore Target Bob to suggestions" }),
    ).toBeNull();
  });
});
