import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SharpRosterPercentagePage from "@/app/market/sharp-roster-percentage/page";

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

const PLAYER = {
  assetId: "4046",
  rank: 1,
  displayName: "Justin Jefferson",
  position: "WR",
  nflTeam: "MIN",
  sharpRosters: 44,
  eligibleRosters: 48,
  sharpRosterPct: 0.9167,
  marketRosterPct: null,
  sharpRosterAdvantage: null,
  value: 9500,
  overallRank: 2,
  slots: { active: 44 },
  buySell: { signal: "distributing", buys: 1, sells: 6, net: -5, window: "30d" },
  sampleWarning: null,
  trend: {
    sevenDay: { available: true, rosterPctChange: 0.02, rostersAdded: 1, rostersDropped: 0 },
    thirtyDay: { available: true, rosterPctChange: -0.05, rostersAdded: 0, rostersDropped: 2 },
    seasonToDate: { available: false, reason: "roster_population_changed", comparableRosters: 3 },
  },
};

const BOARD = {
  status: "ok",
  generatedAt: 1_800_000_000_000,
  lastUpdated: 1_800_000_000_000,
  players: [PLAYER],
  totalQualifyingPlayers: 1,
  transparency: {
    uniqueSharpManagers: 40,
    eligibleRosters: 48,
    sleeperRosters: 48,
    ffpcRosters: 0,
    otherPlatformRosters: 0,
    cohortManagers: 50,
    cohortManagersRepresented: 40,
    cohortCoveragePct: 0.8,
    lastRefreshedMs: 1_800_000_000_000,
  },
  cohort: { selectedManagers: 50 },
  sample: { eligibleRosters: 48, rankable: true, warning: null },
  marketComparison: { available: false, source: null, note: "No general-dynasty feed is ingested." },
  exclusions: { byReason: { stale_roster_data: 3 }, excludedRosters: 3 },
  dataQuality: { playersWithoutBoardValue: 0 },
};

function mockFetch(board = BOARD) {
  return vi.fn(async () => jsonResponse(200, board));
}

beforeEach(() => {
  global.fetch = mockFetch();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Sharp Roster Percentage page", () => {
  it("renders the canonical title", async () => {
    render(<SharpRosterPercentagePage />);
    const heading = await screen.findByRole("heading", { name: "Sharp Roster Percentage", level: 1 });
    expect(heading).toBeInTheDocument();
  });

  it("shows the percentage alongside the sample that produced it", async () => {
    render(<SharpRosterPercentagePage />);
    expect(await screen.findByText("91.7%")).toBeInTheDocument();
    expect(screen.getByText("44 of 48")).toBeInTheDocument();
  });

  it("surfaces the transparency disclosures", async () => {
    render(<SharpRosterPercentagePage />);
    expect(await screen.findByText("Sharp managers")).toBeInTheDocument();
    expect(screen.getByText("Eligible rosters")).toBeInTheDocument();
    expect(screen.getByText("Sleeper rosters")).toBeInTheDocument();
    expect(screen.getByText("FFPC rosters")).toBeInTheDocument();
    expect(screen.getByText("Cohort represented")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
  });

  it("explains that no market comparison exists rather than showing a zero", async () => {
    render(<SharpRosterPercentagePage />);
    expect(await screen.findByText(/No general-dynasty feed is ingested/)).toBeInTheDocument();
  });

  it("shows a widely-rostered player that sharps are selling", async () => {
    // The whole point of joining the two boards: high ownership and
    // active distribution tell different stories.
    render(<SharpRosterPercentagePage />);
    expect(await screen.findByText("Selling")).toBeInTheDocument();
  });

  it("warns explicitly when the sample is small", async () => {
    global.fetch = mockFetch({
      ...BOARD,
      sample: {
        eligibleRosters: 14,
        rankable: true,
        warning: {
          level: "directional",
          message:
            "Based on 14 eligible sharp rosters. Treat this result as directional because of the limited sample size.",
        },
      },
    });
    render(<SharpRosterPercentagePage />);
    expect(
      await screen.findByText(/Based on 14 eligible sharp rosters\. Treat this result as directional/),
    ).toBeInTheDocument();
  });

  it("renders the not-collected-yet state as an explanation, not an error", async () => {
    global.fetch = mockFetch({
      ...BOARD,
      status: "cohort_building",
      players: [],
      totalQualifyingPlayers: 0,
    });
    render(<SharpRosterPercentagePage />);
    expect(await screen.findByText("Collecting sharp rosters")).toBeInTheDocument();
  });

  it("lists excluded rosters with their reasons", async () => {
    render(<SharpRosterPercentagePage />);
    expect(await screen.findByText("Excluded rosters")).toBeInTheDocument();
  });

  it("refetches with the chosen filter when one changes", async () => {
    const user = userEvent.setup();
    render(<SharpRosterPercentagePage />);
    await screen.findByText("91.7%");

    const positionSelect = screen.getByLabelText(/Position/i);
    await user.selectOptions(positionSelect, "LB");

    await waitFor(() => {
      const urls = global.fetch.mock.calls.map(([url]) => String(url));
      expect(urls.some((u) => u.includes("position=LB"))).toBe(true);
    });
  });

  it("requests the top 50 by default", async () => {
    render(<SharpRosterPercentagePage />);
    await waitFor(() => {
      const urls = global.fetch.mock.calls.map(([url]) => String(url));
      expect(urls.some((u) => u.includes("limit=50"))).toBe(true);
    });
  });

  it("offers every documented list size and alternate view", async () => {
    render(<SharpRosterPercentagePage />);
    const show = await screen.findByLabelText(/Show/i);
    expect([...show.options].map((o) => o.value)).toEqual(["25", "50", "100", "0"]);

    const sort = screen.getByLabelText(/Sort by/i);
    expect([...sort.options].map((o) => o.value)).toEqual([
      "rostered",
      "advantage",
      "negativeAdvantage",
      "valueWithoutRosters",
      "rosteredWithoutValue",
      "trend",
    ]);
  });

  it("carries the caveat that ownership is not a buy signal", async () => {
    render(<SharpRosterPercentagePage />);
    expect(
      await screen.findByText(/A high roster percentage is not a buy signal on its own/),
    ).toBeInTheDocument();
  });
});
