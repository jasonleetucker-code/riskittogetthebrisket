// League activity page must surface the news feed's explicit
// unavailable state instead of a misleading "No activity in this
// view" when the News-only filter is active — and mixed views keep
// trades/roster activity while noting the news portion is missing.
import { afterEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const mockUseNews = vi.fn();

vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ rawData: FAKE_RAW, loading: false, error: null }),
}));
vi.mock("@/components/useUserState", () => ({
  useUserState: () => ({ state: {} }),
}));
vi.mock("@/components/useNews", () => ({
  useNews: (...args) => mockUseNews(...args),
}));

import ActivityPage from "@/app/league/activity/page";

const FAKE_RAW = {
  sleeper: {
    teams: [
      { ownerId: "ownA", rosterId: "1", name: "Team A", players: ["Caleb Williams"] },
      { ownerId: "ownB", rosterId: "2", name: "Team B", players: ["Drake Maye"] },
    ],
    positions: { 100: { name: "Caleb Williams" } },
    trades: [
      {
        transaction_id: "t1",
        roster_ids: ["1", "2"],
        adds: { 100: "2" },
        drops: { 100: "1" },
        status_updated: 1714000000000,
      },
    ],
  },
};

const UNAVAILABLE = {
  loading: false,
  error: null,
  items: [],
  source: null,
  unavailable: true,
  reason: "backend_unavailable",
  scored: [],
  byPlayer: new Map(),
};

const HEALTHY = {
  loading: false,
  error: null,
  items: [
    {
      id: "n1",
      ts: "2026-07-25T10:00:00Z",
      headline: "Caleb Williams practice note",
      severity: "info",
      players: [{ name: "Caleb Williams" }],
    },
  ],
  source: "backend",
  unavailable: false,
  reason: null,
  scored: [],
  byPlayer: new Map(),
};

afterEach(() => {
  mockUseNews.mockReset();
});

describe("ActivityPage news-outage handling", () => {
  it("News filter during an outage shows the explicit unavailable state", () => {
    mockUseNews.mockReturnValue(UNAVAILABLE);
    render(<ActivityPage />);
    fireEvent.click(screen.getByRole("tab", { name: "News" }));
    expect(screen.getByRole("alert")).toHaveTextContent("News unavailable");
    expect(screen.queryByText("No activity in this view")).toBeNull();
  });

  it("mixed (All) view keeps trade activity and notes the missing news portion", () => {
    mockUseNews.mockReturnValue(UNAVAILABLE);
    render(<ActivityPage />);
    // The trade event still renders...
    expect(screen.getByText("TRADE")).toBeInTheDocument();
    // ...alongside an inline note, not the red alert card.
    expect(screen.getByRole("status")).toHaveTextContent("News unavailable");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("healthy feed under the News filter renders items, no unavailable state", () => {
    mockUseNews.mockReturnValue(HEALTHY);
    render(<ActivityPage />);
    fireEvent.click(screen.getByRole("tab", { name: "News" }));
    expect(screen.getByText("Caleb Williams practice note")).toBeInTheDocument();
    expect(screen.queryByText("News unavailable")).toBeNull();
  });
});
