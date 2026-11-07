import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makePlayer } from "../fixtures/players";

let mockApp;
let mockOwnership;
let mockParams = { playerId: "4984" };
const toggleWatchlist = vi.fn();
vi.mock("next/navigation", () => ({ useParams: () => mockParams }));
vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/components/AppShell", () => ({ useApp: () => mockApp }));
vi.mock("@/components/useUserState", () => ({
  useUserState: () => ({
    state: { watchlist: [] },
    toggleWatchlist,
    serverBacked: true,
  }),
}));
vi.mock("@/components/PlayerRankHistoryChart", () => ({
  default: ({ row }) => (
    <div data-testid="canonical-history">{row.name} history</div>
  ),
}));
vi.mock("@/components/PlayerPopup", () => ({
  computeOwnership: () => mockOwnership,
  computeValueChain: () => [],
  computeSiteDetails: () => [],
  computeConsensusText: () => "",
  RosContextSection: () => <div>Canonical ROS section</div>,
  PlayerContextSection: () => <div>Canonical context section</div>,
  RealizedPointsSection: () => <div>Canonical realized section</div>,
  IntelContextSection: () => <div>Canonical intel section</div>,
  PlayerNewsSection: () => <div>Canonical player news section</div>,
}));
import PlayerFilePage from "@/app/players/[playerId]/page";

const JOSH = makePlayer({
  name: "Josh Allen",
  pos: "QB",
  rankDerivedValue: 9200,
  values: { full: 9200 },
  canonicalConsensusRank: 2,
  confidenceLabel: "High",
  siteCount: 5,
  raw: { playerId: "4984", team: "BUF" },
});
const LAMAR = makePlayer({
  name: "Lamar Jackson",
  pos: "QB",
  rankDerivedValue: 9500,
  values: { full: 9500 },
  canonicalConsensusRank: 1,
  raw: { playerId: "4881", team: "BAL" },
});
const QB_WITHOUT_ID = makePlayer({
  name: "Unresolved QB",
  pos: "QB",
  rankDerivedValue: 4000,
  values: { full: 4000 },
  canonicalConsensusRank: 40,
  raw: { team: "FA" },
});
beforeEach(() => {
  toggleWatchlist.mockClear();
  mockParams = { playerId: "4984" };
  mockOwnership = { ownerLabel: "Test roster", positionLabel: "QB2" };
  mockApp = {
    rows: [JOSH, LAMAR, QB_WITHOUT_ID],
    rawData: { sleeper: { teams: [] } },
    loading: false,
    error: "",
    failure: null,
    retry: vi.fn(),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }),
  );
});

describe("Sports Network Player File", () => {
  it("distinguishes absent roster coverage from a known unrostered player", () => {
    mockOwnership = null;
    const { rerender } = render(<PlayerFilePage />);
    expect(
      screen.getByText("Roster ownership unavailable"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Unrostered in your league")).toBeNull();
    mockApp = {
      ...mockApp,
      rawData: { sleeper: { teams: [{ name: "Other roster", players: [] }] } },
    };
    rerender(<PlayerFilePage />);
    expect(screen.getByText("Unrostered in your league")).toBeInTheDocument();
  });
  it("unifies real identity, canonical valuation and existing actions in the hero", async () => {
    render(<PlayerFilePage />);
    const hero = screen.getByRole("region", {
      name: "Player identity and valuation",
    });
    expect(within(hero).getByRole("heading", { level: 1 })).toHaveTextContent(
      "Josh Allen",
    );
    expect(
      within(hero).getByRole("img", { name: "Josh Allen" }),
    ).toHaveAttribute(
      "src",
      "https://sleepercdn.com/content/nfl/players/4984.jpg",
    );
    const valuation = within(hero).getByRole("complementary", {
      name: "Current dynasty valuation",
    });
    expect(valuation).toHaveTextContent((9200).toLocaleString());
    expect(valuation).toHaveTextContent("QB2");
    expect(
      within(hero).getByRole("link", { name: "Compare", exact: true }),
    ).toHaveAttribute("href", "/players/compare?p1=Josh%20Allen");
    expect(
      within(hero).getByRole("link", { name: "Open in Trade Calculator" }),
    ).toHaveAttribute("href", "/trade");
    await userEvent.click(
      within(hero).getByRole("button", { name: "Watch", exact: true }),
    );
    expect(toggleWatchlist).toHaveBeenCalledWith("Josh Allen");
  });

  it("shows same-position peers in stamped value order, linking only resolved identities", () => {
    mockApp.rows.push(
      makePlayer({
        name: "Different Position",
        pos: "WR",
        rankDerivedValue: 9800,
        raw: { playerId: "wr-1" },
      }),
    );
    mockApp.rows.push(
      makePlayer({
        name: "Unpriced QB",
        pos: "QB",
        rankDerivedValue: null,
        values: {},
        raw: { playerId: "qb-0" },
      }),
    );
    render(<PlayerFilePage />);
    const rail = screen.getByRole("complementary", {
      name: "Positional context and evidence",
    });
    const peers = within(rail).getByRole("list");
    expect(within(peers).getAllByRole("listitem")).toHaveLength(2);
    expect(
      within(peers).getByRole("link", { name: "Lamar Jackson" }),
    ).toHaveAttribute("href", "/players/4881");
    expect(within(peers).getByText("QB1")).toBeInTheDocument();
    expect(within(peers).getByText("QB3")).toBeInTheDocument();
    expect(within(peers).getByText("Unresolved QB")).toBeInTheDocument();
    expect(
      within(peers).queryByRole("link", { name: "Unresolved QB" }),
    ).toBeNull();
    expect(within(peers).queryByText("Different Position")).toBeNull();
    expect(within(peers).queryByText("Unpriced QB")).toBeNull();
  });

  it("retains the shared research sections and tab activation behavior", async () => {
    render(<PlayerFilePage />);
    expect(screen.getByTestId("canonical-history")).toHaveTextContent(
      "Josh Allen history",
    );
    expect(screen.queryByText("Canonical ROS section")).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "Performance" }));
    expect(screen.getByText("Canonical ROS section")).toBeInTheDocument();
    expect(screen.getByText("Canonical context section")).toBeInTheDocument();
    expect(screen.getByText("Canonical realized section")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Intel" }));
    expect(screen.getByText("Canonical intel section")).toBeInTheDocument();
    expect(
      screen.getByText("Canonical player news section"),
    ).toBeInTheDocument();
  });

  it("keeps unpriced identity honest and offers no invented positional peers", () => {
    mockApp.rows = [
      {
        ...JOSH,
        rankDerivedValue: null,
        values: {},
        canonicalConsensusRank: null,
        rank: undefined,
      },
    ];
    render(<PlayerFilePage />);
    expect(
      screen.getByRole("complementary", { name: "Current dynasty valuation" }),
    ).toHaveTextContent("not priced");
    expect(
      screen.getByText(
        "No priced positional peers are available on this board.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("#0")).toBeNull();
    expect(screen.queryByRole("link", { name: "Lamar Jackson" })).toBeNull();
  });
});
