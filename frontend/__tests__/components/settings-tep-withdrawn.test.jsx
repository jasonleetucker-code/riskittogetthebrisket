/**
 * DEFECT-02 (held for owner approval): the manual TE-premium override is
 * withdrawn.  /settings used to offer two number inputs that wrote
 * `tepMultiplier` / `tepNativeMultiplier` to localStorage; `useDynastyData`
 * posted them, and the server re-ran the blend and returned a different
 * canonical `rankDerivedValue` per device.  The page now shows the premium
 * read-only and never writes either key, even for a device that still has a
 * manual value stored.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
// Static import (vi.mock calls are hoisted above it): the settings page is
// large, and transforming it inside a test body could exceed the timeout.
import SettingsPage from "@/app/settings/page";

const SLOW = 30000;

const state = vi.hoisted(() => ({ update: null }));

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
      // The stale manual values a device from before the withdrawal holds.
      settings: { ...actual.SETTINGS_DEFAULTS, tepMultiplier: 1.45, tepNativeMultiplier: 1.3 },
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

describe("/settings TE premium (manual override withdrawn)", () => {
  it(
    "offers no TE-premium input, only a read-only statement",
    () => {
      renderSettings();
      expect(screen.queryByLabelText(/TEP — non-native/)).toBeNull();
      expect(screen.queryByLabelText(/TEP — native/)).toBeNull();
      expect(screen.queryByRole("button", { name: /Reset to auto/i })).toBeNull();
      const block = screen.getByTestId("tep-premium-readonly");
      const text = block.textContent.replace(/\s+/g, " ");
      expect(text).toMatch(/TE premium — automatic/);
      expect(text).toMatch(/no longer applied/);
      // the stored manual value is not presented as if it applied
      expect(text).not.toMatch(/1\.45/);
    },
    SLOW,
  );

  it(
    "never writes tepMultiplier or tepNativeMultiplier from this page",
    () => {
      renderSettings();
      const writes = state.update.mock.calls.filter(
        ([key]) => key === "tepMultiplier" || key === "tepNativeMultiplier",
      );
      expect(writes).toEqual([]);
    },
    SLOW,
  );
});
