/**
 * Rendered surfaces for unknown pick ownership (#1618 review).
 *
 * The logic is pinned in `__tests__/pick-ownership-unavailable.test.js`;
 * this file proves the components actually SAY it:
 *
 *   PickProjectorPanel   renders the reason instead of silently vanishing
 *   TeamSwitcher         renders "—pk", not "0pk"
 *   PortfolioSummary     renders "Picks —" and the excludes-picks hint
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const UNKNOWN = {
  picks: null,
  pickDetails: null,
  pickOwnershipState: "unavailable",
  pickOwnershipReason: "traded_picks_fetch_failed",
};

let teamState = {};
vi.mock("@/components/useTeam", () => ({ useTeam: () => teamState }));
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({
    rows: [{ name: "Josh Allen", pos: "QB", age: 30, rankDerivedValue: 9988 }],
    rawData: {},
    openPlayerPopup: () => {},
  }),
}));
vi.mock("@/components/useRankHistory", () => ({
  useRankHistory: () => ({ history: {}, loading: false }),
}));
vi.mock("@/components/useTerminal", () => ({ useTerminal: () => ({ portfolio: null }) }));

import PickProjectorPanel from "@/app/league/sections/_pick-projector.jsx";
import TeamSwitcher from "@/components/TeamSwitcher";
import PortfolioSummary from "@/components/terminal/PortfolioSummary";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PickProjectorPanel", () => {
  it("shows the unavailable reason instead of hiding", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          picks: null,
          projectedOrder: [],
          error: "pick_ownership_unavailable",
          meta: {
            pickOwnershipState: "unavailable",
            pickOwnershipReason: "traded_picks_fetch_failed",
          },
        }),
      })),
    );
    render(<PickProjectorPanel leagueKey="dynasty_main" />);
    await waitFor(() => expect(screen.getByText(/Pick ownership unavailable/)).toBeTruthy());
    expect(screen.getByText(/traded-picks feed could not be read/)).toBeTruthy();
  });

  it("still renders nothing for the quiet steady states", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ picks: [], error: "no_teams" }) })),
    );
    const { container } = render(<PickProjectorPanel leagueKey="dynasty_main" />);
    await new Promise((r) => setTimeout(r, 0));
    expect(container.textContent).toBe("");
  });
});

describe("TeamSwitcher", () => {
  it('renders "—pk" for a team with unknown pick ownership', () => {
    teamState = {
      availableTeams: [
        { name: "Alpha", ownerId: "o1", players: ["a", "b"], ...UNKNOWN },
        { name: "Beta", ownerId: "o2", players: ["c"], picks: ["x"], pickOwnershipState: "observed" },
      ],
      selectedTeam: null,
      setSelectedTeam: () => {},
      needsSelection: false,
      privateDataEnabled: true,
    };
    render(<TeamSwitcher />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("2p · —pk")).toBeTruthy();
    expect(screen.getByText("1p · 1pk")).toBeTruthy();
    expect(screen.queryByText(/0pk/)).toBeNull();
  });
});

describe("PortfolioSummary", () => {
  it("says picks are unavailable rather than omitting them", () => {
    teamState = {
      selectedTeam: { name: "Alpha", ownerId: "o1", players: ["Josh Allen"], ...UNKNOWN },
      idpEnabled: false,
      rosterSettings: null,
      loading: false,
    };
    render(<PortfolioSummary />);
    expect(screen.getByText(/excludes picks \(ownership unavailable\)/)).toBeTruthy();
    expect(screen.getByText("Picks").parentElement.textContent).toMatch(/Picks\s*—/);
  });
});
