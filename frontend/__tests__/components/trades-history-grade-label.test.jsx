// /trades renders the relabelled history tier and states its basis
// (OD-F6 option A, owner 2026-10-21).  The grade math is pinned elsewhere
// (history-grade-relabel-no-change.test.js); this pins the page copy: the
// evenly-valued badge reads HISTORY_EVEN_LABEL (never "Fair trade"), the
// basis sentence is on the page, and a trade at or past HISTORY_EVEN_PCT
// still gets its "won by" badge exactly as before.
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const mockUseApp = vi.fn();

vi.mock("@/components/AppShell", () => ({
  useApp: () => mockUseApp(),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {} }),
}));
vi.mock("@/components/useManagerScout", () => ({
  useManagerScout: () => ({ loading: false, data: null, failure: "unavailable" }),
}));
vi.mock("@/components/useTradeAsofGrades", () => ({
  useTradeAsofGrades: () => ({
    status: "unavailable",
    byTrade: new Map(),
    packageModel: null,
    reason: "at_time_unavailable",
  }),
}));

import TradesPage from "@/app/trades/page";
import {
  HISTORY_EVEN_LABEL,
  historyGradeBasisText,
} from "@/lib/trade-history-grade-policy";

const ROWS = [
  { name: "Even One", pos: "WR", values: { full: 5000, raw: 5000 } },
  { name: "Even Two", pos: "WR", values: { full: 5000, raw: 5000 } },
  { name: "Big Piece", pos: "RB", values: { full: 6000, raw: 6000 } },
];

function rawWith(trades) {
  return {
    sleeper: {
      teams: [
        { name: "Team A", roster_id: 1, ownerId: "a", players: [] },
        { name: "Team B", roster_id: 2, ownerId: "b", players: [] },
      ],
      trades,
      positions: {},
    },
  };
}

function trade(got, gave, offsetDaysAgo = 1) {
  return {
    week: 3,
    timestamp: Date.now() - offsetDaysAgo * 24 * 60 * 60 * 1000,
    sides: [
      { team: "Team A", rosterId: 1, ownerId: "a", got, gave },
      { team: "Team B", rosterId: 2, ownerId: "b", got: gave, gave: got },
    ],
  };
}

describe("/trades history grade label", () => {
  it("an evenly valued trade reads HISTORY_EVEN_LABEL, with the basis on the page", () => {
    mockUseApp.mockReturnValue({
      rows: ROWS,
      rawData: rawWith([trade(["Even One"], ["Even Two"])]),
      loading: false,
      error: null,
    });
    render(<TradesPage />);
    expect(screen.getByTestId("trade-even-badge").textContent).toBe(HISTORY_EVEN_LABEL);
    expect(screen.getByTestId("trade-grade-basis").textContent).toBe(historyGradeBasisText());
    expect(document.body.textContent).not.toMatch(/Fair trade/);
    // Per-side "Today" grade carries the basis on hover.
    for (const el of screen.getAllByTestId("trade-grade-today")) {
      expect(el.textContent).toContain(HISTORY_EVEN_LABEL);
      expect(el.getAttribute("title")).toBe(historyGradeBasisText());
    }
  });

  it("a trade past the cut keeps its won-by badge", () => {
    mockUseApp.mockReturnValue({
      rows: ROWS,
      rawData: rawWith([trade(["Big Piece"], ["Even One"])]),
      loading: false,
      error: null,
    });
    render(<TradesPage />);
    expect(screen.queryByTestId("trade-even-badge")).toBeNull();
    expect(document.body.textContent).toMatch(/won by \d+\.\d%/);
  });
});
