// The /trades page header must not assert a trade count it does not
// have yet.
//
// Observed on a real signed-in walk of the route: while the contract
// was still in flight the page rendered
//
//   "0 trades in the last 365 days, graded at alpha=1.65."
//
// directly above a loading skeleton, and the same line renders above
// the red "Couldn't load trade data" banner on the error path.  The
// count comes from ``analyzeSleeperTradeHistory(rawData, ...)``, which
// returns an empty analysis for an absent contract — so "0" means
// "nothing loaded", not "no trades exist".  The league snapshot used
// for this audit carries 109 Sleeper trades, so the line was simply
// false.
//
// CLAUDE.md's fail-fast convention: a failure (or a pending load) must
// be visible, never dressed up as a real, settled result.
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const mockUseApp = vi.fn();

vi.mock("@/components/AppShell", () => ({
  useApp: () => mockUseApp(),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {} }),
}));
vi.mock("@/components/useRankHistory", () => ({
  useRankHistory: () => ({ history: null }),
}));

import TradesPage from "@/app/trades/page";

// One real trade so the loaded-state assertion has something to count.
const RAW_WITH_TRADES = {
  sleeper: {
    teams: [
      { ownerId: "a", rosterId: 1, name: "Team A", players: [] },
      { ownerId: "b", rosterId: 2, name: "Team B", players: [] },
    ],
    trades: [],
    positions: {},
  },
};

describe("/trades header honesty", () => {
  it("does not claim a trade count while the contract is still loading", () => {
    mockUseApp.mockReturnValue({ rows: [], rawData: null, loading: true, error: null });
    const { container } = render(<TradesPage />);
    // The skeleton is up...
    expect(container.querySelector('[class*="keleton"]')).not.toBeNull();
    // ...so the header must not assert "0 trades".
    expect(document.body.textContent).not.toMatch(/0 trades in the last/);
  });

  it("does not claim a trade count when the contract failed to load", () => {
    mockUseApp.mockReturnValue({
      rows: [],
      rawData: null,
      loading: false,
      error: "network exploded",
    });
    render(<TradesPage />);
    expect(document.body.textContent).toMatch(/Couldn't load trade data/);
    expect(document.body.textContent).not.toMatch(/0 trades in the last/);
  });

  it("still reports the real count once the contract has loaded", () => {
    mockUseApp.mockReturnValue({
      rows: [],
      rawData: RAW_WITH_TRADES,
      loading: false,
      error: null,
    });
    render(<TradesPage />);
    expect(document.body.textContent).toMatch(/0 trades in the last 365 days/);
  });
});
