/**
 * Absence of evidence must not render as a finding — W26-F010, W12-F011.
 *
 * Three panels stated a fact about THE MARKET when the true fact was about
 * OUR DATA:
 *
 *   MoversPanel   "No qualifying movers in this window." under a subtitle
 *                 asserting "Rank deltas vs. 30d ago", while /api/movers
 *                 had answered historyDepthDays: 0, window: 0, asOf: null.
 *   MarketTicker  "Market quiet in my roster — fewer than 3 moves since
 *                 last update." off a contract stamping rankChange: null
 *                 on every row.
 *   BuySellHold   665 of 665 rostered players HOLD, rationale "Stable — no
 *                 movement, volatility, or news triggers."
 *
 * A 30-day rank delta was never computed in any of the three.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

const mockUseApp = vi.fn();

vi.mock("@/components/AppShell", () => ({
  useApp: (...a) => mockUseApp(...a),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedTeam: { ownerId: "own1", name: "Team", players: ["Josh Allen"] } }),
}));
vi.mock("@/components/useNews", () => ({
  useNews: () => ({ loading: false, items: [], scored: [], byPlayer: new Map() }),
}));

import MoversPanel from "@/components/terminal/MoversPanel";
import MarketTicker from "@/components/terminal/MarketTicker";

const NO_HISTORY_MOVERS = {
  window: 0,
  windowRequested: 14,
  historyDepthDays: 0,
  threshold: 15,
  asOf: null,
  risers: [],
  fallers: [],
};

// A real /api/movers answer with history: nobody cleared the 15-rank bar.
const MEASURED_BUT_QUIET = {
  window: 14,
  windowRequested: 14,
  historyDepthDays: 40,
  threshold: 15,
  asOf: "2026-08-04T00:00:00Z",
  risers: [],
  fallers: [],
};

function mockMoversFetch(payload) {
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }),
  );
}

describe("MoversPanel — zero rank history", () => {
  beforeEach(() => {
    mockUseApp.mockReturnValue({ openPlayerPopup: vi.fn(), rawData: null, rows: [] });
  });

  it("says the history is missing, not that nobody moved", async () => {
    mockMoversFetch(NO_HISTORY_MOVERS);
    render(<MoversPanel />);
    const empties = await screen.findAllByText(/no rank history yet/i);
    expect(empties.length).toBeGreaterThanOrEqual(2); // risers + fallers
    expect(screen.queryByText(/no qualifying movers/i)).toBeNull();
  });

  it("drops the delta claim from the subtitle", async () => {
    mockMoversFetch(NO_HISTORY_MOVERS);
    render(<MoversPanel />);
    await screen.findAllByText(/no rank history yet/i);
    expect(screen.queryByText(/rank deltas vs\./i)).toBeNull();
  });

  it("still says 'no qualifying movers' when history exists and nobody moved", async () => {
    mockMoversFetch(MEASURED_BUT_QUIET);
    render(<MoversPanel />);
    const empties = await screen.findAllByText(/no qualifying movers/i);
    expect(empties.length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/no rank history yet/i)).toBeNull();
  });
});

describe("MarketTicker — no measured rank change", () => {
  it("does not call the market quiet when nothing was measured", () => {
    mockUseApp.mockReturnValue({
      openPlayerPopup: vi.fn(),
      rawData: { sleeper: { teams: [] } },
      rows: [{ name: "Josh Allen", pos: "QB", rankChange: null, rankDerivedValue: 9988 }],
    });
    render(<MarketTicker />);
    expect(screen.getByText(/no rank-change data yet/i)).toBeTruthy();
    expect(screen.queryByText(/market quiet/i)).toBeNull();
  });

  it("keeps 'market quiet' when changes WERE measured and were small", () => {
    mockUseApp.mockReturnValue({
      openPlayerPopup: vi.fn(),
      rawData: { sleeper: { teams: [] } },
      rows: [{ name: "Josh Allen", pos: "QB", rankChange: 0, rankDerivedValue: 9988 }],
    });
    render(<MarketTicker />);
    expect(screen.getByText(/market quiet/i)).toBeTruthy();
    expect(screen.queryByText(/no rank-change data yet/i)).toBeNull();
  });
});
