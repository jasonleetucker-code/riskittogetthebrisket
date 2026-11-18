// 2026-11-16 verified sweep: Sharp Tracker must never show 0 for a window it
// does not hold.
//
// Each market payload carries exactly ONE window (`windows[query.window]`).
// The table read the SELECTED window's key, so while a new window loaded — or
// after it failed to load — every player showed 0 buys / 0 sells / 0 net /
// 0 volume.  Missing is never zero: a mismatched window is shown as loading,
// or as the window the table actually holds, labelled.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import SharpTrackerPage from "@/app/market/sharp-tracker/page.jsx";

const COHORT = { cohort: { observableManagers: 10, qualifiedManagers: 4 }, methodologyVersion: "sharp-v2" };

function marketFor(window, stats, extraAssets = []) {
  return {
    status: "ok",
    methodologyVersion: "sharp-v2",
    query: { window, sort: "strength", assetType: "player", platform: "all", qualification: "all", limit: 100 },
    cohort: { qualificationMethods: ["automated"] },
    coverage: { platforms: { sleeper: { status: "ok", movements: 20 } }, unmappedAssets: 0 },
    assets: [
      {
        assetId: "p1",
        displayName: "Jeremiyah Love",
        assetType: "player",
        position: "RB",
        signalStrength: 4.2,
        confidence: "medium",
        velocity: null,
        sourceLabels: ["Sleeper"],
        sources: {},
        windows: { [window]: stats },
      },
      ...extraAssets,
    ],
  };
}

const json = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

let marketByWindow;
beforeEach(() => {
  marketByWindow = {};
  vi.stubGlobal(
    "fetch",
    vi.fn((url) => {
      const u = new URL(String(url));
      if (u.pathname === "/api/sharp/cohort") return Promise.resolve(json(200, COHORT));
      const handler = marketByWindow[u.searchParams.get("window")];
      return handler ? handler() : new Promise(() => {});
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const STATS_30D = { buys: 5, sells: 2, net: 3, volume: 7, uniqueManagers: 4, uniqueLeagues: 6 };

function playerRowCells() {
  const row = screen.getByText("Jeremiyah Love").closest("tr");
  return within(row)
    .getAllByRole("cell")
    .map((td) => td.textContent.trim());
}

function chooseWindow(value) {
  // The first filter dropdown is Window.
  fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value } });
}

describe("Sharp Tracker: a window the table does not hold is never shown as 0", () => {
  it("shows the held window's real counts", async () => {
    marketByWindow["30d"] = () => Promise.resolve(json(200, marketFor("30d", STATS_30D)));
    render(<SharpTrackerPage />);
    await screen.findByText("Jeremiyah Love");
    const cells = playerRowCells();
    expect(cells).toEqual(expect.arrayContaining(["5", "2", "+3", "7"]));
  });

  it("shows loading — not a table of zeros — while the newly selected window loads", async () => {
    marketByWindow["30d"] = () => Promise.resolve(json(200, marketFor("30d", STATS_30D)));
    marketByWindow["7d"] = () => new Promise(() => {}); // still in flight
    render(<SharpTrackerPage />);
    await screen.findByText("Jeremiyah Love");

    chooseWindow("7d");

    expect(await screen.findByText("Loading the 7d window…")).toBeInTheDocument();
    expect(screen.queryByText("Jeremiyah Love")).not.toBeInTheDocument();
  });

  it("keeps the held window's numbers, labelled, when the new window fails — never zeros", { timeout: 15000 }, async () => {
    marketByWindow["30d"] = () => Promise.resolve(json(200, marketFor("30d", STATS_30D)));
    marketByWindow["7d"] = () => Promise.resolve(json(500, { error: "boom" }));
    render(<SharpTrackerPage />);
    await screen.findByText("Jeremiyah Love");

    chooseWindow("7d");

    // fetchFreshJson retries a failed request (750 ms + 1500 ms) before giving up.
    expect(await screen.findByText("The 7d window did not load", {}, { timeout: 6000 })).toBeInTheDocument();
    expect(screen.getByText(/Showing the 30d window — 7d has not loaded/)).toBeInTheDocument();
    const cells = playerRowCells();
    expect(cells).toEqual(expect.arrayContaining(["5", "2", "+3", "7"]));
    expect(cells).not.toContain("0");
  });

  it(
    "a failed refresh of the HELD window does not make a newly selected window read as failed",
    { timeout: 15000 },
    async () => {
      let calls30d = 0;
      marketByWindow["30d"] = () => {
        calls30d += 1;
        return calls30d === 1
          ? Promise.resolve(json(200, marketFor("30d", STATS_30D)))
          : Promise.resolve(json(500, { error: "boom" }));
      };
      marketByWindow["7d"] = () => new Promise(() => {}); // still in flight
      render(<SharpTrackerPage />);
      await screen.findByText("Jeremiyah Love");

      // Refresh the held 30d window; it fails (after fetchFreshJson's retries).
      fireEvent.click(screen.getByRole("button", { name: /Refresh now/ }));
      expect(await screen.findByText("Latest refresh failed", {}, { timeout: 6000 })).toBeInTheDocument();

      chooseWindow("7d");

      // 7d is loading, not failed: the 30d error is not attributed to it.
      expect(await screen.findByText("Loading the 7d window…")).toBeInTheDocument();
      expect(screen.queryByText("The 7d window did not load")).not.toBeInTheDocument();
      expect(screen.queryByText("Latest refresh failed")).not.toBeInTheDocument();
    },
  );

  it("switches to the new window's counts once they arrive", async () => {
    marketByWindow["30d"] = () => Promise.resolve(json(200, marketFor("30d", STATS_30D)));
    marketByWindow["7d"] = () =>
      Promise.resolve(json(200, marketFor("7d", { buys: 9, sells: 1, net: 8, volume: 10, uniqueManagers: 3, uniqueLeagues: 2 })));
    render(<SharpTrackerPage />);
    await screen.findByText("Jeremiyah Love");

    chooseWindow("7d");

    await waitFor(() => expect(playerRowCells()).toEqual(expect.arrayContaining(["9", "1", "+8", "10"])));
    expect(screen.queryByText(/has not loaded/)).not.toBeInTheDocument();
  });

  it("renders a missing per-window figure as a dash, not 0", async () => {
    const sparse = {
      assetId: "p2",
      displayName: "Cam Ward",
      assetType: "player",
      position: "QB",
      signalStrength: 1,
      sourceLabels: [],
      sources: {},
      windows: {},
    };
    marketByWindow["30d"] = () => Promise.resolve(json(200, marketFor("30d", STATS_30D, [sparse])));
    render(<SharpTrackerPage />);
    await screen.findByText("Cam Ward");
    const row = screen.getByText("Cam Ward").closest("tr");
    const cells = within(row).getAllByRole("cell").map((td) => td.textContent.trim());
    expect(cells).not.toContain("0");
    expect(cells.filter((c) => c === "—").length).toBeGreaterThanOrEqual(4);
  });
});
