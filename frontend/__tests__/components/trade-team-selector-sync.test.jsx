/**
 * V1-45: the in-page "Your team" dropdown (Trade Suggestions, #suggest-team)
 * must propagate to the global team context (`useTeam().selectedTeam`), not
 * just the local `selectedTeamIdx` state.
 *
 * Before this fix, sync was one-directional: picking a team in the topbar
 * TeamSwitcher flowed down and snapped this local dropdown, but picking a
 * team via this LOCAL dropdown never flowed back up. Consequences:
 *   - `/trade`'s "Simulate impact" button is gated on `selectedTeam` from
 *     `useTeam()` (page.jsx), so a user who only used this local selector
 *     never saw it enable, even with a fully populated roster — the exact
 *     failure the V1-45 authenticated E2E recipe hit
 *     (v1-45-trade-surface.spec.js).
 *   - Any other surface reading `useTeam().selectedTeam` (topbar display,
 *     other pages via the shared context) silently disagreed with what
 *     this page was actually using.
 *
 * This test drives the real dropdown and asserts `setSelectedTeam` is
 * called with the picked team — not the roster/opponent-population side
 * effects, which are already covered elsewhere.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const SLEEPER_TEAMS = [
  {
    ownerId: "owner-a",
    name: "Team A",
    players: ["Bijan Robinson"],
    picks: [],
  },
  {
    ownerId: "owner-b",
    name: "Team B",
    players: ["Puka Nacua"],
    picks: [],
  },
];

const ROWS = [
  {
    name: "Bijan Robinson",
    pos: "RB",
    position: "RB",
    assetClass: "offense",
    rankDerivedValue: 8000,
    values: { full: 8000 },
    rank: 1,
    blendedSourceRank: 1,
  },
];

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: null,
    rows: ROWS,
    rawData: {
      currentDraftYear: 2026,
      sleeper: { teams: SLEEPER_TEAMS },
    },
  }),
}));

vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({
    settings: {},
    setSettings: () => {},
    valueMode: "full",
    setValueMode: () => {},
  }),
}));

const setSelectedTeam = vi.fn();

vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({
    selectedTeam: null,
    setSelectedTeam,
    idpEnabled: true,
    leagueMismatch: false,
    selectedLeagueKey: "dynasty_main",
    loading: false,
  }),
}));

let TradePage;

beforeEach(async () => {
  window.localStorage.clear();
  setSelectedTeam.mockClear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })),
  );
  ({ default: TradePage } = await import("@/app/trade/page"));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("trade page team-selector sync", () => {
  it("propagates a local team pick to the global team context", async () => {
    const user = userEvent.setup();
    render(<TradePage />);

    const select = await screen.findByLabelText("Your team");
    await user.selectOptions(select, "1"); // "Team B" (index 1)

    await waitFor(() => {
      expect(setSelectedTeam).toHaveBeenCalledWith(SLEEPER_TEAMS[1]);
    });
  });
});
