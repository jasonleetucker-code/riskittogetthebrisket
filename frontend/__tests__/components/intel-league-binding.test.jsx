// League binding for the Insider Trading surfaces:
//   1. /league/insider-trading refetches when the active league changes
//      while mounted, and always sends the selected leagueKey explicitly.
//      (Insider Trading is league-scoped BY DESIGN; Sharp Tracker at
//      /market/sharp-tracker deliberately is not, and has no such binding.)
//   2. PlayerPopup's intel cache is keyed on (leagueKey, asset) so a
//      league switch never serves the previous league's counts.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor, act } from "@testing-library/react";

// Mutable league state the mocked hook reads — tests flip it and
// rerender to simulate the league switcher.
const leagueState = { selectedLeagueKey: "dynasty_main", loading: false };
vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ ...leagueState }),
}));

// PlayerPopup pulls in five context hooks + a network-fetching chart;
// stub them so importing its _loadPlayerIntel helper stays light
// (same mock set as PlayerPopup.test.jsx).
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ rows: [], rawData: {} }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedTeam: null }),
}));
vi.mock("@/components/useTerminal", () => ({
  useTerminal: () => ({ signals: [] }),
}));
vi.mock("@/components/useUserState", () => ({
  useUserState: () => ({ state: {}, toggleWatchlist: vi.fn(), serverBacked: false }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {} }),
}));
vi.mock("@/components/PlayerRankHistoryChart", () => ({
  default: () => <div data-testid="rank-history-stub" />,
}));
vi.mock("next/link", () => ({
  default: ({ children, href }) => <a href={href}>{children}</a>,
}));

import IntelPage from "@/app/league/insider-trading/page";
import { _loadPlayerIntel } from "@/components/PlayerPopup";

function emptySummary() {
  return {
    assets: [],
    staleHours: 1,
    generatedAt: new Date().toISOString(),
    memberCount: 0,
    leagueCount: 0,
    truncatedMemberCount: 0,
  };
}

beforeEach(() => {
  leagueState.selectedLeagueKey = "dynasty_main";
  leagueState.loading = false;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => emptySummary() }),
  );
});

describe("IntelPage league binding", () => {
  it("sends the selected leagueKey explicitly on the summary fetch", async () => {
    render(<IntelPage />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    const url = fetch.mock.calls[0][0];
    expect(url).toContain("/api/intel/summary");
    expect(url).toContain("leagueKey=dynasty_main");
  });

  it("refetches when the active league changes while mounted", async () => {
    const { rerender } = render(<IntelPage />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

    leagueState.selectedLeagueKey = "dynasty_new";
    await act(async () => {
      rerender(<IntelPage />);
    });

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(fetch.mock.calls[1][0]).toContain("leagueKey=dynasty_new");
  });

  it("waits for the league hook before fetching (no default-league race)", async () => {
    leagueState.loading = true;
    const { rerender } = render(<IntelPage />);
    // Nothing fetched while the league is unresolved.
    expect(fetch).not.toHaveBeenCalled();

    leagueState.loading = false;
    await act(async () => {
      rerender(<IntelPage />);
    });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(fetch.mock.calls[0][0]).toContain("leagueKey=dynasty_main");
  });
});

describe("PlayerPopup intel cache league keying", () => {
  it("caches per (leagueKey, asset) and refetches on league switch", async () => {
    const payload = { holderCount: 2, windows: { "7d": { net: 1, buys: 1, sells: 0 } } };
    fetch.mockResolvedValue({ ok: true, json: async () => payload });

    await _loadPlayerIntel("1234", "Test Guy", "league_a");
    await _loadPlayerIntel("1234", "Test Guy", "league_a"); // cache hit
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toContain("leagueKey=league_a");

    await _loadPlayerIntel("1234", "Test Guy", "league_b"); // different league → refetch
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][0]).toContain("leagueKey=league_b");
  });
});
