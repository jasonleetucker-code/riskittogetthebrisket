// League activity page must surface the news feed's explicit
// unavailable state instead of a misleading "No activity in this
// view" when the News-only filter is active — and mixed views keep
// trades/roster activity while noting the news portion is missing.
//
// Trades now come from the PUBLIC league pipeline, not the private
// contract.  The page previously read ``useApp().rawData``, which is
// hard-coded ``null`` on every /league route (PUBLIC_ONLY_ROUTE_PREFIXES)
// — so its trade half was permanently empty in the real app even
// though this spec passed against a mocked ``useApp``.  Mocking the
// public fetch instead means the test exercises the path production
// actually takes.
import { afterEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const mockUseNews = vi.fn();
const mockFetchPublicSection = vi.fn();

vi.mock("@/components/useUserState", () => ({
  useUserState: () => ({ state: {} }),
}));
vi.mock("@/components/useNews", () => ({
  useNews: (...args) => mockUseNews(...args),
}));
vi.mock("@/lib/public-league-data", () => ({
  fetchPublicSection: (...args) => mockFetchPublicSection(...args),
}));

import ActivityPage from "@/app/league/activity/page";

// One trade, shaped like src/public_league/activity.py's feed entries.
const PUBLIC_FEED = [
  {
    transactionId: "t1",
    season: "2025",
    createdAt: 1714000000000,
    sides: [
      {
        rosterId: 1,
        ownerId: "ownA",
        teamName: "Team A",
        receivedAssets: [{ kind: "player", name: "Caleb Williams", position: "QB" }],
        grade: { grade: "A", color: "var(--green)", label: "Fair trade" },
      },
      {
        rosterId: 2,
        ownerId: "ownB",
        teamName: "Team B",
        receivedAssets: [{ kind: "player", name: "Drake Maye", position: "QB" }],
        grade: { grade: "A", color: "var(--green)", label: "Fair trade" },
      },
    ],
    totalAssets: 2,
    notableAssetCount: 2,
  },
];

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

function renderPage() {
  mockFetchPublicSection.mockResolvedValue({ data: { feed: PUBLIC_FEED } });
  return render(<ActivityPage />);
}

afterEach(() => {
  mockUseNews.mockReset();
  mockFetchPublicSection.mockReset();
});

describe("ActivityPage news-outage handling", () => {
  it("News filter during an outage shows the explicit unavailable state", async () => {
    mockUseNews.mockReturnValue(UNAVAILABLE);
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "News" }));
    expect(screen.getByRole("alert")).toHaveTextContent("News unavailable");
    expect(screen.queryByText("No activity in this view")).toBeNull();
  });

  it("mixed (All) view keeps trade activity and notes the missing news portion", async () => {
    mockUseNews.mockReturnValue(UNAVAILABLE);
    renderPage();
    // The trade event still renders...
    expect(await screen.findByText("TRADE")).toBeInTheDocument();
    // ...alongside an inline note, not the red alert card.
    expect(screen.getByRole("status")).toHaveTextContent("News unavailable");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("healthy feed under the News filter renders items, no unavailable state", async () => {
    mockUseNews.mockReturnValue(HEALTHY);
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "News" }));
    expect(screen.getByText("Caleb Williams practice note")).toBeInTheDocument();
    expect(screen.queryByText("News unavailable")).toBeNull();
  });
});

describe("ActivityPage trade feed source", () => {
  it("reads the public activity section, never the private contract", async () => {
    mockUseNews.mockReturnValue(HEALTHY);
    renderPage();
    expect(await screen.findByText("TRADE")).toBeInTheDocument();
    expect(mockFetchPublicSection).toHaveBeenCalledWith("activity");
  });

  it("renders the trade with both teams resolved from the public payload", async () => {
    mockUseNews.mockReturnValue(HEALTHY);
    renderPage();
    expect(await screen.findByText("Team A ↔ Team B")).toBeInTheDocument();
    // Asset names come resolved from the public payload too.  (The
    // detail string appears in both the desktop and mobile rows, so
    // match all rather than requiring exactly one.)
    expect(screen.getAllByText("Caleb Williams · Drake Maye").length).toBeGreaterThan(0);
  });

  it("shows an explicit failure state when the public section cannot load", async () => {
    mockUseNews.mockReturnValue(HEALTHY);
    mockFetchPublicSection.mockRejectedValue(new Error("public league offline"));
    render(<ActivityPage />);
    expect(await screen.findByText("Couldn't load data")).toBeInTheDocument();
  });
});
