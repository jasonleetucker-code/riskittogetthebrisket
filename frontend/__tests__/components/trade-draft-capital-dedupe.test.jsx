/**
 * TC-A — /trade fetches /api/draft-capital ONCE, for the resolved league.
 *
 * Measured on load (UX audit §6): GET /api/draft-capital twice — first with
 * no leagueKey (while the league key was still ""), then with
 * ?leagueKey=dynasty_main once /api/leagues answered.  The fetch now waits
 * for the league to resolve.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, waitFor } from "@testing-library/react";

const team = { leagueLoading: true, selectedLeagueKey: "" };

// Stable identities: a mock that returns a fresh array/object per render
// re-fires every effect keyed on it, forever.
const ROWS = [];
const RAW_DATA = { currentDraftYear: 2026, sleeper: { teams: [] } };
const SETTINGS = {};
const noop = () => {};

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({ loading: false, error: null, rows: ROWS, rawData: RAW_DATA }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: SETTINGS, hydrated: true, update: noop }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({
    selectedTeam: null,
    setSelectedTeam: noop,
    idpEnabled: true,
    leagueMismatch: false,
    selectedLeagueKey: team.selectedLeagueKey,
    leagueLoading: team.leagueLoading,
    loading: false,
  }),
}));

let TradePage;
let fetchSpy;

beforeEach(async () => {
  window.localStorage.clear();
  fetchSpy = vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) }));
  vi.stubGlobal("fetch", fetchSpy);
  ({ default: TradePage } = await import("@/app/trade/page"));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const draftCapitalCalls = () =>
  fetchSpy.mock.calls.map((c) => String(c[0])).filter((u) => u.startsWith("/api/draft-capital"));

describe("draft-capital fetch on /trade", () => {
  it("waits for the league key and fetches exactly once", async () => {
    const { rerender } = render(<TradePage />);
    expect(draftCapitalCalls()).toEqual([]);
    team.leagueLoading = false;
    team.selectedLeagueKey = "dynasty_main";
    rerender(<TradePage />);
    await waitFor(() => expect(draftCapitalCalls()).toEqual(["/api/draft-capital?leagueKey=dynasty_main"]));
    rerender(<TradePage />);
    expect(draftCapitalCalls()).toHaveLength(1);
  });
});
