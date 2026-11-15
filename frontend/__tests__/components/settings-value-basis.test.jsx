/**
 * /settings -> Valuation.  The "Value basis: Market / My league" selector
 * used to say it was "the only setting that changes the numbers
 * themselves".  The league-adjusted lens was withdrawn 2026-08-14 (the
 * server ignores the request and `readValuationMode()` is always market),
 * so the selector changed nothing while claiming to change everything.
 *
 * The control now states what is true: market only, read-only, whatever an
 * old device still has stored.  Other hooks still list `valuationMode` as a
 * fetch dependency, so the settings key survives; nothing on this page may
 * write it.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
// Static import (vi.mock calls are hoisted above it): the settings page is
// large, and transforming it inside a test body could exceed the timeout.
import SettingsPage from "@/app/settings/page";

const SLOW = 30000;

const state = vi.hoisted(() => ({
  update: null,
  stored: "leagueAdjusted",
}));

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: null,
    failure: null,
    rows: [],
    rawData: null,
    retry: () => {},
  }),
}));
vi.mock("@/app/AppShellWrapper", () => ({
  useAuthContext: () => ({ isAdmin: false }),
}));
vi.mock("@/components/useSettings", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useSettings: () => ({
      // The stale value a device from before the withdrawal still holds.
      settings: { ...actual.SETTINGS_DEFAULTS, valuationMode: state.stored },
      hydrated: true,
      update: (...args) => state.update(...args),
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

afterEach(() => {
  vi.restoreAllMocks();
});

function renderSettings() {
  state.update = vi.fn();
  globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }));
  return render(<SettingsPage />);
}

describe("/settings Value basis (withdrawn lens)", () => {
  it(
    "shows a read-only market control that offers no other basis",
    () => {
      renderSettings();
      const select = screen.getByRole("combobox", { name: "Valuation mode" });
      expect(select).toBeDisabled();
      expect(select.value).toBe("market");
      const options = Array.from(select.options).map((o) => o.textContent);
      expect(options).toEqual(["Market"]);
    },
    SLOW,
  );

  it(
    "shows market even when this device still has the withdrawn lens saved",
    () => {
      state.stored = "leagueAdjusted";
      renderSettings();
      const select = screen.getByRole("combobox", { name: "Valuation mode" });
      expect(select.value).toBe("market");
      expect(select.selectedOptions[0].textContent).toBe("Market");
    },
    SLOW,
  );

  it(
    "no longer claims the selector changes the numbers, and says the lens was withdrawn",
    () => {
      const { container } = renderSettings();
      const text = container.textContent.replace(/\s+/g, " ");
      expect(text).not.toMatch(/only setting that changes the numbers/i);
      expect(text).not.toMatch(/re-prices it by how scarce/i);
      expect(text).toMatch(/Values are always the market board/);
      expect(text).toMatch(/was withdrawn and no longer changes any number/);
      expect(screen.queryByRole("button", { name: /What this changes/i })).toBeNull();
    },
    SLOW,
  );

  it(
    "never writes valuationMode from this page",
    () => {
      renderSettings();
      const writes = state.update.mock.calls.filter(([key]) => key === "valuationMode");
      expect(writes).toEqual([]);
    },
    SLOW,
  );
});
