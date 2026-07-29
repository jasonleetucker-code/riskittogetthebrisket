// useTeam().loading is the "team identity not yet answerable" signal —
// all seven useTerminal call sites pass it as ``skip`` to hold the
// /api/terminal fetch.  Before this gate it was just the contract
// loading flag, so two windows still fired a discarded anonymous fetch
// and then refired with the team:
//   1. settings not yet hydrated (stored team selection unknown), and
//   2. auto-assign pending (the effect resolves the team one commit
//      AFTER the contract lands).
//
// Pinned here:
//   - loading stays true until settings hydrate;
//   - loading stays true across the auto-assign window and flips false
//     WITH the team already resolved (no anonymous window);
//   - it also flips false when auto-assign finds NO match (a league
//     with no default team must not wait forever);
//   - a deliberately-cleared selection (selectionTouched) skips the
//     auto-assign hold and gets the anonymous slice.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const mockUseApp = vi.fn();
const mockUseSettings = vi.fn();
const mockUseLeague = vi.fn();

vi.mock("@/components/AppShell", () => ({
  useApp: () => mockUseApp(),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => mockUseSettings(),
}));
vi.mock("@/components/useLeague", () => ({
  useLeague: () => mockUseLeague(),
}));

import { useTeam } from "@/components/useTeam";

function Probe() {
  const { loading, selectedTeam } = useTeam();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="team">{selectedTeam?.name || "none"}</span>
    </div>
  );
}

const TEAMS = [
  { ownerId: "u1", rosterId: 1, name: "Rossini Panini", players: [] },
  { ownerId: "u2", rosterId: 2, name: "Bravo", players: [] },
];

function appState({ loading = false } = {}) {
  return {
    rawData: {
      meta: { leagueKey: "main", sleeperDataReady: true },
      sleeper: { teams: TEAMS },
    },
    privateDataEnabled: true,
    loading,
  };
}

function settingsState({ hydrated = true, touched = false, stored = null } = {}) {
  // Stateful mock: ``setSelectedTeam`` persists the auto-assigned team
  // via ``update(patch)``; the next render (triggered by the hook's own
  // evaluated-state flip in the same commit) must observe it, exactly
  // like the real settings store.
  const box = {
    settings: {
      selectedTeamsByLeague: stored ? { main: stored } : {},
      selectedTeamTouchedByLeague: touched ? { main: true } : {},
    },
    hydrated,
  };
  box.update = vi.fn((key, value) => {
    box.settings = { ...box.settings, [key]: value };
  });
  return box;
}

function leagueState() {
  return {
    selectedLeague: { userDefaultTeam: { ownerId: "u2" } },
    selectedLeagueKey: "main",
    defaultLeagueKey: "main",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockUseLeague.mockReturnValue(leagueState());
});

describe("useTeam loading gate", () => {
  it("stays loading while settings have not hydrated", () => {
    mockUseApp.mockReturnValue(appState());
    mockUseSettings.mockReturnValue(settingsState({ hydrated: false }));
    render(<Probe />);
    expect(screen.getByTestId("loading").textContent).toBe("true");
  });

  it("holds through the auto-assign window and lands with the team resolved", async () => {
    mockUseApp.mockReturnValue(appState());
    mockUseSettings.mockReturnValue(settingsState());
    render(<Probe />);
    // After the auto-assign effect settles, loading is false AND the
    // server-default team (u2 → Bravo) is already selected — at no
    // point does a consumer observe loading:false with team:none.
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    expect(screen.getByTestId("team").textContent).toBe("Bravo");
  });

  it("clears the hold when auto-assign finds no match", async () => {
    mockUseApp.mockReturnValue(appState());
    mockUseSettings.mockReturnValue(settingsState());
    mockUseLeague.mockReturnValue({
      selectedLeague: { userDefaultTeam: null },
      selectedLeagueKey: "other",
      defaultLeagueKey: "main",
    });
    render(<Probe />);
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    expect(screen.getByTestId("team").textContent).toBe("none");
  });

  it("a deliberately-cleared selection is not held by auto-assign", () => {
    mockUseApp.mockReturnValue(appState());
    mockUseSettings.mockReturnValue(settingsState({ touched: true }));
    render(<Probe />);
    expect(screen.getByTestId("loading").textContent).toBe("false");
    expect(screen.getByTestId("team").textContent).toBe("none");
  });

  it("still reports loading while the contract downloads", () => {
    mockUseApp.mockReturnValue({ rawData: null, privateDataEnabled: true, loading: true });
    mockUseSettings.mockReturnValue(settingsState());
    render(<Probe />);
    expect(screen.getByTestId("loading").textContent).toBe("true");
  });
});
