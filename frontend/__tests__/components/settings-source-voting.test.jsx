/**
 * /settings → Source Voting (owner directive 2026-10-19 §8).  Reads the
 * contract's `sourceVotingStatus` from the already-loaded board — no second
 * fetch — and renders the same component as Source Health.  A board built
 * before the block existed reads "not available yet", never rows or 0%.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import votingFixture from "../fixtures/source-voting-status-2026-10-19.json";
// Static import (vi.mock calls are hoisted above it): the settings page is
// large, and transforming it inside a test body could exceed the timeout.
import SettingsPage from "@/app/settings/page";
// The table is React.lazy on /settings; warm its module so the Suspense
// boundary resolves promptly.
import "@/components/SourceVotingStatus";

const LAZY = { timeout: 10000 };

const dataState = { current: null };

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => dataState.current,
}));
vi.mock("@/app/AppShellWrapper", () => ({
  useAuthContext: () => ({ isAdmin: false }),
}));
vi.mock("@/components/useSettings", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useSettings: () => ({
      settings: { ...actual.SETTINGS_DEFAULTS },
      hydrated: true,
      update: () => {},
      updateSiteWeight: () => {},
      resetSiteWeights: () => {},
      reset: () => {},
    }),
  };
});
vi.mock("@/components/useUserState", () => ({
  useUserState: () => ({
    state: { watchlist: [], notificationsEnabled: false, notificationsEmail: null },
    serverBacked: false,
    setNotifications: () => {},
    toggleWatchlist: () => {},
  }),
}));
vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ selectedLeague: null, selectedLeagueKey: null }),
}));
vi.mock("@/components/PushNotificationToggle", () => ({ default: () => null }));
vi.mock("@/components/CustomAlertsConfigurator", () => ({ default: () => null }));

function setData(rawData, extra = {}) {
  dataState.current = {
    loading: false,
    error: null,
    failure: null,
    rows: [],
    rawData,
    retry: () => {},
    ...extra,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

async function renderSettings() {
  globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }));
  return render(<SettingsPage />);
}

// The settings page is large; a full jsdom render of it plus the lazy
// table can take several seconds on a loaded runner.
const SLOW = 30000;

describe("Settings → Source Voting", () => {
  it("renders the contract's sourceVotingStatus with the owner's labels", async () => {
    setData({ sourceVotingStatus: votingFixture });
    await renderSettings();

    expect(screen.getByRole("heading", { name: "Source Voting" })).toBeTruthy();
    const summary = await screen.findByTestId("source-voting-summary", {}, LAZY);
    expect(summary.textContent).toMatch(/17\s+of\s+26\s+sources voting/);
    const idptc = screen.getByTestId("source-voting-status-idpTradeCalc");
    expect(within(idptc).getByText("Active — 75%")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Source Health" }).getAttribute("href")).toBe(
      "/tools/source-health",
    );
    // No extra request: the block rides the board that is already loaded.
    expect(
      globalThis.fetch.mock.calls.filter(([u]) => String(u).includes("/api/sources/weighting")),
    ).toHaveLength(0);
  }, SLOW);

  it("a board without the block says not available yet", async () => {
    setData({ privateSourceAvailability: {} });
    await renderSettings();
    expect(await screen.findByTestId("source-voting-unavailable", {}, LAZY)).toBeTruthy();
    expect(screen.queryByTestId("source-voting-summary")).toBeNull();
  }, SLOW);

  it("a board that failed to load points at the failure instead of claiming absence", async () => {
    setData(null, { failure: { kind: "offline", message: "Could not reach the server.", retryable: true } });
    await renderSettings();
    expect(screen.queryByTestId("source-voting-unavailable")).toBeNull();
    expect(screen.getByText(/needs the board data, which did not load/)).toBeTruthy();
  }, SLOW);
});
