import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { rankByRelevance } from "@/lib/news-service";

const mocks = vi.hoisted(() => ({ news: null, selectedTeam: null, openPlayer: vi.fn() }));
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({
    rows: [
      { name: "Darius Vale", pos: "WR", raw: { team: "SEA" } },
      { name: "Elias Brooks", pos: "QB", raw: { team: "BUF" } },
    ],
    rawData: {
      sleeper: { teams: [{ players: ["Darius Vale", "Elias Brooks"] }] },
    },
    openPlayerPopup: mocks.openPlayer,
  }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({
    selectedTeam: mocks.selectedTeam,
  }),
}));
vi.mock("@/components/useNews", () => ({ useNews: () => mocks.news }));
import NewsPage from "@/app/news/page";

const ITEMS = [
  {
    id: "a",
    ts: "2026-11-07T11:00:00Z",
    headline: "Vale earns expanded role",
    body: "A test report about opportunity.",
    provider: "one",
    providerLabel: "Fixture bulletin",
    severity: "info",
    kind: "role",
    players: [{ name: "Darius Vale" }],
    url: "https://example.com/source-a",
  },
  {
    id: "b",
    ts: "2026-11-07T10:00:00Z",
    headline: "Brooks returns to practice",
    body: "A test practice report.",
    provider: "two",
    providerLabel: "Fixture wire",
    severity: "watch",
    kind: "practice",
    players: [{ name: "Elias Brooks" }],
    url: "https://example.com/source-b",
  },
  {
    id: "c",
    ts: "2026-11-05T11:00:00Z",
    headline: "Mixed roster report",
    body: "Two distinct players in one test report.",
    provider: "one",
    providerLabel: "Fixture bulletin",
    severity: "alert",
    kind: "injury",
    players: [{ name: "Darius Vale" }, { name: "Elias Brooks" }],
    url: "https://example.com/source-c",
  },
];
const DIGESTS = [
  {
    player: "Darius Vale",
    position: "WR",
    team: "SEA",
    summary: "Combined fixture analysis for Vale.",
    latestTs: ITEMS[0].ts,
    storyCount: 2,
    sources: ["Fixture bulletin"],
    severity: "info",
  },
  {
    player: "Elias Brooks",
    position: "QB",
    team: "BUF",
    summary: "Combined fixture analysis for Brooks.",
    latestTs: ITEMS[1].ts,
    storyCount: 2,
    sources: ["Fixture bulletin", "Fixture wire"],
    severity: "watch",
  },
];
function healthy(items = ITEMS) {
  return {
    items,
    digests: DIGESTS,
    scored: rankByRelevance(items, {
      rosterNames: ["Darius Vale"],
      leagueNames: ["Elias Brooks"],
    }),
    providersUsed: ["one", "two"],
    loading: false,
    unavailable: false,
    reason: null,
  };
}
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-07T12:00:00Z"));
  mocks.news = healthy();
  mocks.selectedTeam = { name: "Fixture roster", players: ["Darius Vale"] };
  mocks.openPlayer.mockReset();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Sports Network News Desk live-contract presentation", () => {
  it("does not represent absent roster coverage as a measured zero", () => {
    mocks.selectedTeam = null;
    render(<NewsPage />);
    const roster = screen.getByText("Roster stories").closest("div");
    expect(roster.querySelector("dd")).toHaveTextContent("—");
    expect(roster).toHaveTextContent("No team selected");
    expect(roster.querySelector("dd")).not.toHaveTextContent("0");
    expect(screen.getByText("Player digests")).toBeInTheDocument();
  });

  it("keeps the canonical title, digest default and source-attributed lead", () => {
    render(<NewsPage />);
    expect(
      screen.getByRole("heading", { level: 1, name: "News" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "By player" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("Fixture roster")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Fixture roster" })).toBeNull();
    const feature = screen.getByRole("region", { name: "Featured coverage" });
    expect(
      within(feature).getByRole("heading", {
        level: 2,
        name: "Vale earns expanded role",
      }),
    ).toBeInTheDocument();
    expect(
      within(feature).getByRole("link", { name: "Vale earns expanded role" }),
    ).toHaveAttribute("href", "https://example.com/source-a");
    expect(
      within(feature).getByText("Nov 7, 11:00 AM UTC"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Combined fixture analysis for Vale."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/breaking|official confirmation|sources live/i),
    ).toBeNull();
  });
  it("manually advances only recent report-wire items without a live claim", () => {
    render(<NewsPage />);
    const wire = screen.getByRole("region", { name: "Report wire" });
    expect(
      within(wire).getByText("Vale earns expanded role"),
    ).toBeInTheDocument();
    fireEvent.click(within(wire).getByRole("button", { name: "Next report" }));
    expect(
      within(wire).getByText("Brooks returns to practice"),
    ).toBeInTheDocument();
    fireEvent.click(within(wire).getByRole("button", { name: "Next report" }));
    expect(
      within(wire).getByText("Vale earns expanded role"),
    ).toBeInTheDocument();
    expect(within(wire).queryByText("Mixed roster report")).toBeNull();
  });
  it("retains conjunction-per-mention filtering in feed, lead and wire", () => {
    render(<NewsPage />);
    fireEvent.click(screen.getByRole("tab", { name: "Stories" }));
    fireEvent.change(
      screen.getByRole("combobox", { name: "Filter by NFL team" }),
      { target: { value: "SEA" } },
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Filter by position" }),
      { target: { value: "QB" } },
    );
    expect(screen.getByText("No matching stories")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Featured coverage" }),
    ).toBeNull();
    expect(screen.queryByRole("region", { name: "Report wire" })).toBeNull();
    expect(screen.queryByText("Mixed roster report")).toBeNull();
  });
  it("source and search facets update the featured report, preserving source URLs", () => {
    render(<NewsPage />);
    fireEvent.change(
      screen.getByRole("combobox", { name: "Filter by source" }),
      { target: { value: "two" } },
    );
    const feature = screen.getByRole("region", { name: "Featured coverage" });
    expect(
      within(feature).getByRole("link", { name: "Brooks returns to practice" }),
    ).toHaveAttribute("href", "https://example.com/source-b");
    fireEvent.change(
      screen.getByRole("searchbox", {
        name: "Search news by player or headline",
      }),
      { target: { value: "not-present" } },
    );
    expect(
      screen.queryByRole("region", { name: "Featured coverage" }),
    ).toBeNull();
    expect(
      screen.getByText("No players match these filters"),
    ).toBeInTheDocument();
  });
  it("player actions retain the shared popup path and roster relevance scope", () => {
    render(<NewsPage />);
    const feature = screen.getByRole("region", { name: "Featured coverage" });
    fireEvent.click(
      within(feature).getByRole("button", { name: "Darius Vale" }),
    );
    expect(mocks.openPlayer).toHaveBeenCalledWith("Darius Vale");
    fireEvent.click(screen.getByRole("radio", { name: "My roster" }));
    expect(
      screen.getByText("Combined fixture analysis for Vale."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Combined fixture analysis for Brooks."),
    ).toBeNull();
  });
  it("preserves an honest outage and never displays retained stale stories as current", () => {
    mocks.news = {
      ...healthy(),
      unavailable: true,
      reason: "backend_unavailable",
      items: [],
      scored: [],
      digests: [],
    };
    render(<NewsPage />);
    expect(screen.getByRole("alert")).toHaveTextContent("News unavailable");
    expect(screen.getByText("No news to show")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Featured coverage" }),
    ).toBeNull();
    expect(screen.queryByRole("region", { name: "Report wire" })).toBeNull();
  });
  it("old reports keep their actual date and do not enter the report wire", () => {
    mocks.news = healthy([ITEMS[2]]);
    render(<NewsPage />);
    expect(screen.queryByRole("region", { name: "Report wire" })).toBeNull();
    expect(screen.getByText("Nov 5, 11:00 AM UTC")).toBeInTheDocument();
  });
  it("loading retains placeholders instead of synthetic headlines", () => {
    mocks.news = {
      ...healthy(),
      loading: true,
      items: [],
      scored: [],
      digests: [],
    };
    render(<NewsPage />);
    expect(
      screen.queryByRole("region", { name: "Featured coverage" }),
    ).toBeNull();
    expect(screen.queryByRole("region", { name: "Report wire" })).toBeNull();
    expect(screen.queryByText("Vale earns expanded role")).toBeNull();
  });
});
