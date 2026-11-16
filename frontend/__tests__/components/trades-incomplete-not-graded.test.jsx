// /trades must not grade a trade whose total is incomplete as a confident
// win/loss.  A side that sent only assets today's board cannot price has an
// empty priced "gave" list; the 100% gap that produces is an artifact of the
// missing value, not a verdict (MISSING IS NEVER ZERO).
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const mockUseApp = vi.fn();

vi.mock("@/components/AppShell", () => ({ useApp: () => mockUseApp() }));
vi.mock("@/components/useSettings", () => ({ useSettings: () => ({ settings: {} }) }));
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

function trade(got, gave) {
  return {
    week: 3,
    timestamp: Date.now() - 24 * 60 * 60 * 1000,
    sides: [
      { team: "Team A", rosterId: 1, ownerId: "a", got, gave },
      { team: "Team B", rosterId: 2, ownerId: "b", got: gave, gave: got },
    ],
  };
}

function mount(t) {
  mockUseApp.mockReturnValue({
    rows: ROWS,
    rawData: rawWith([t]),
    loading: false,
    error: null,
  });
  return render(<TradesPage />);
}

describe("/trades incomplete trades", () => {
  it("a side that sent only unpriced assets is not graded or headlined", () => {
    mount(trade(["Big Piece"], ["Ghost Kicker"]));
    expect(screen.getByTestId("trade-incomplete-badge").textContent).toBe("Incomplete");
    expect(document.body.textContent).not.toMatch(/won by|overpaid by/);
    for (const el of screen.getAllByTestId("trade-grade-today")) {
      expect(el.textContent).toMatch(/incomplete — 1 unpriced/);
      expect(el.textContent).not.toMatch(/\bA\+/);
    }
    // never "(0)" for a group with nothing priced
    expect(document.body.textContent).toContain("(unpriced)");
    expect(document.body.textContent).not.toMatch(/Gave \(0\)|Got \(0\)/);
  });

  it("a partially unpriced group says its total is partial", () => {
    mount(trade(["Big Piece"], ["Even One", "Ghost Kicker"]));
    expect(document.body.textContent).toContain("(partial: 5,000 + 1 unpriced)");
    expect(screen.getByTestId("trade-incomplete-badge")).toBeTruthy();
  });

  it("a fully priced trade is unchanged", () => {
    mount(trade(["Big Piece"], ["Even One"]));
    expect(screen.queryByTestId("trade-incomplete-badge")).toBeNull();
    expect(document.body.textContent).toMatch(/won by \d+\.\d%/);
    expect(document.body.textContent).not.toMatch(/unpriced|incomplete/i);
  });

  it("the W-L record carries the incomplete asterisk and explanation", () => {
    mount(trade(["Big Piece"], ["Ghost Kicker"]));
    const marked = Array.from(document.querySelectorAll("span[title]")).filter((el) =>
      /may count them as incomplete/.test(el.getAttribute("title") || ""),
    );
    expect(marked.length).toBeGreaterThan(0);
    expect(marked[0].textContent).toMatch(/^\d+-\d+\*$/);
  });

  it("a fully priced trade's W-L has no asterisk", () => {
    mount(trade(["Big Piece"], ["Even One"]));
    const marked = Array.from(document.querySelectorAll("span[title]")).filter((el) =>
      /may count them as incomplete/.test(el.getAttribute("title") || ""),
    );
    expect(marked.length).toBe(0);
  });
});
