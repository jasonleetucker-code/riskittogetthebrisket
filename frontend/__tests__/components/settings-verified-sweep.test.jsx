/**
 * /settings defects from the 2026-11-16 verified frontend sweep.
 *
 *  1. Ranking Sources promised that toggles / weights / presets "recompute
 *     the board with your own mix" while the server ignores every custom mix
 *     (`_SOURCE_OVERRIDES_DISABLED`, src/api/data_contract.py).
 *  3. League Format, Sort Basis, "Enable ROS engine" and "Monte Carlo
 *     simulations" wrote settings nothing reads.
 *  4. "Reset Defaults" fired on one click and erased the selected team in
 *     every league.
 *  5. Status / Covered were computed in the browser from `canonicalSites`:
 *     a stale source showed a green "Live".  They now come from the board's
 *     own `sourceVotingStatus` block; an unreported source says so.
 *  6. Unnamed controls (ROS source switches/weights, email, watchlist add).
 *
 * Review follow-up (PR #2224): the inert include box is named as the
 * REGISTRY DEFAULT (so "checked" is never read as "in the blend" for a source
 * Status says is not voting), the weight is the backend's own `baseWeight`
 * as text ("—" when unreported), mobile states the status as text, and
 * visible labels are part of each control's name (WCAG 2.5.3).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import votingFixture from "../fixtures/source-voting-status-2026-10-19.json";
// Static import (vi.mock calls are hoisted above it): the settings page is
// large, and transforming it inside a test body could exceed the timeout.
import SettingsPage from "@/app/settings/page";
import "@/components/SourceVotingStatus";

const SLOW = 30000;

const state = vi.hoisted(() => ({
  data: null,
  settings: null,
  update: null,
  reset: null,
  resetSiteWeights: null,
  serverBacked: false,
}));

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => state.data,
}));
vi.mock("@/app/AppShellWrapper", () => ({
  useAuthContext: () => ({ isAdmin: false }),
}));
vi.mock("@/components/useSettings", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useSettings: () => ({
      settings: state.settings ?? actual.SETTINGS_DEFAULTS,
      hydrated: true,
      update: (...args) => state.update(...args),
      updateSiteWeight: () => {
        throw new Error("Settings must not write a per-source override");
      },
      resetSiteWeights: (...args) => state.resetSiteWeights(...args),
      reset: (...args) => state.reset(...args),
    }),
  };
});
vi.mock("@/components/useUserState", () => ({
  useUserState: () => ({
    state: { watchlist: [], notificationsEnabled: false, notificationsEmail: null },
    serverBacked: state.serverBacked,
    setNotifications: () => {},
    toggleWatchlist: () => {},
  }),
}));
vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ selectedLeague: null, selectedLeagueKey: null }),
}));
vi.mock("@/components/PushNotificationToggle", () => ({ default: () => null }));
vi.mock("@/components/CustomAlertsConfigurator", () => ({ default: () => null }));

let DEFAULTS;

beforeEach(async () => {
  DEFAULTS = (await vi.importActual("@/components/useSettings")).SETTINGS_DEFAULTS;
  state.settings = null;
  state.serverBacked = false;
  state.update = vi.fn();
  state.reset = vi.fn();
  state.resetSiteWeights = vi.fn();
  setData(null);
  globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }));
});

afterEach(() => {
  vi.restoreAllMocks();
});

function setData(rawData, extra = {}) {
  state.data = {
    loading: false,
    error: null,
    failure: null,
    rows: [],
    rawData,
    retry: () => {},
    ...extra,
  };
}

// Rows that put a positive value in EVERY registered source's
// `canonicalSites` slot — the signal the old browser-side "Live" read.
function rowsCoveringEverySource(keys) {
  const cs = Object.fromEntries(keys.map((k) => [k, 5000]));
  return [
    { name: "Player A", canonicalSites: cs },
    { name: "Player B", canonicalSites: cs },
  ];
}

// Collapsed sections hide their body, and role queries skip hidden
// content — so a test about a collapsed section must open it first, or an
// absence assertion passes vacuously.
function openSection(title) {
  const button = screen.getByRole("button", { name: new RegExp(`^${title}`) });
  if (button.getAttribute("aria-expanded") !== "true") fireEvent.click(button);
}

function rankingSourcesPanel() {
  const button = screen.getByRole("button", { name: /^Ranking Sources/ });
  return document.getElementById(button.getAttribute("aria-controls"));
}

describe("1. Ranking Sources: custom source mixes are off and the page says so", () => {
  it(
    "states the canonical blend, never promises a recompute, and offers no operable mix control",
    () => {
      render(<SettingsPage />);
      const panel = rankingSourcesPanel();
      const text = panel.textContent.replace(/\s+/g, " ");
      expect(text).not.toMatch(/recompute the board/i);
      expect(text).not.toMatch(/override mode/i);
      expect(screen.getByTestId("custom-mix-off-note").textContent).toMatch(
        /Custom source mixes are switched off.*canonical consensus blend/,
      );
      // No weight presets.
      for (const label of [/^Balanced/, /^Market \(retail-lean\)/, /^Expert consensus/, /^Reset source weights$/]) {
        expect(within(panel).queryByRole("button", { name: label })).toBeNull();
      }
      const includes = within(panel).getAllByRole("checkbox", {
        name: /^Include .+ by registry default/,
      });
      expect(includes.length).toBeGreaterThan(3);
      for (const cb of includes) {
        expect(cb).toBeDisabled();
        expect(cb.getAttribute("aria-describedby")).toBe(
          screen.getByTestId("custom-mix-off-note").id,
        );
      }
      // The columns say they are the registry's default, not live inclusion.
      expect(within(panel).getAllByRole("columnheader", { name: "Registry default" }).length).toBe(2);
      expect(within(panel).getAllByRole("columnheader", { name: "Base weight" }).length).toBe(2);
      // Weights are text, not inputs: nothing in the table can be edited.
      expect(within(panel).queryAllByRole("spinbutton")).toEqual([]);
      // Other copy on the page no longer says the weights apply.
      const page = document.body.textContent.replace(/\s+/g, " ");
      expect(page).not.toMatch(/source weights below are applied/i);
      expect(page).not.toMatch(/source weights and TE premium on this page still apply/i);
    },
    SLOW,
  );

  it(
    "shows the backend's base weight, not a stored custom one, and names a saved mix it does not apply",
    () => {
      state.settings = {
        ...DEFAULTS,
        siteWeights: { fantasyCalc: { include: false, weight: 3 } },
      };
      // A base weight the frontend registry copy (1.0) does not carry, so the
      // cell can only show it by reading the backend block.
      const block = {
        ...votingFixture,
        sources: votingFixture.sources.map((src) =>
          src.key === "fantasyCalc" ? { ...src, baseWeight: 1.5 } : src,
        ),
      };
      setData({ sourceVotingStatus: block });
      render(<SettingsPage />);
      const panel = rankingSourcesPanel();
      expect(within(panel).getByTestId("settings-src-base-weight-fantasyCalc").textContent).toBe("1.5");
      const fcInclude = within(panel).getByRole("checkbox", {
        name: /^Include FantasyCalc Dynasty SF by registry default/,
      });
      expect(fcInclude).toBeChecked();
      const note = screen.getByTestId("saved-source-mix").textContent;
      expect(note).toMatch(/not applied to any value/);
      // The mix may have been saved today (the /rankings popover still writes
      // one), so the note does not date it.
      expect(note).not.toMatch(/from before/);
      fireEvent.click(screen.getByRole("button", { name: "Clear saved source mix" }));
      expect(state.resetSiteWeights).toHaveBeenCalledTimes(1);
    },
    SLOW,
  );

  it(
    "offers no clear button when no custom mix is saved",
    () => {
      render(<SettingsPage />);
      expect(screen.queryByTestId("saved-source-mix")).toBeNull();
      expect(screen.queryByRole("button", { name: "Clear saved source mix" })).toBeNull();
    },
    SLOW,
  );
});

describe("3. controls with no reader are gone", () => {
  it(
    "League Format, Sort Basis, the ROS master switch and Monte Carlo count are not offered",
    () => {
      render(<SettingsPage />);
      openSection("Rest-of-Season Engine");
      expect(screen.queryByRole("combobox", { name: /League format/i })).toBeNull();
      expect(screen.queryByLabelText(/Sort Basis/i)).toBeNull();
      expect(screen.queryByRole("checkbox", { name: /Enable ROS engine/i })).toBeNull();
      expect(screen.queryByText(/Monte Carlo simulations/i)).toBeNull();
      expect(screen.getByTestId("league-format-note").textContent).toMatch(
        /League format is not a setting/,
      );
      // The ROS toggles that ARE read survive.
      expect(
        screen.getByRole("checkbox", { name: /Show ROS Fit panel on Trade Calculator/ }),
      ).toBeTruthy();
      expect(screen.getByRole("checkbox", { name: /Show ROS context tags/ })).toBeTruthy();
    },
    SLOW,
  );
});

describe("4. Reset Defaults asks first and keeps the team selection", () => {
  const team = {
    selectedTeam: "Brisket Bandits",
    selectedTeamTouched: true,
    selectedTeamsByLeague: { dynasty_main: { ownerId: "o1", teamName: "Brisket Bandits" } },
    selectedTeamTouchedByLeague: { dynasty_main: true },
  };

  it(
    "opening the confirmation resets nothing; Cancel resets nothing",
    () => {
      state.settings = { ...DEFAULTS, ...team, faabRiskPosture: "aggressive" };
      render(<SettingsPage />);
      fireEvent.click(screen.getByRole("button", { name: "Reset Defaults" }));
      const dialog = screen.getByRole("dialog", { name: /Reset settings to defaults/ });
      expect(dialog.textContent).toMatch(/FAAB risk posture/);
      expect(dialog.textContent).toMatch(/hidden columns on Rankings/);
      expect(dialog.textContent).toMatch(/selected team in each league is kept/);
      expect(state.reset).not.toHaveBeenCalled();
      fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
      expect(state.reset).not.toHaveBeenCalled();
      expect(state.update).not.toHaveBeenCalled();
      expect(screen.queryByRole("dialog")).toBeNull();
    },
    SLOW,
  );

  it(
    "confirming resets, then restores every team-selection key with its saved value",
    () => {
      state.settings = { ...DEFAULTS, ...team };
      render(<SettingsPage />);
      fireEvent.click(screen.getByRole("button", { name: "Reset Defaults" }));
      fireEvent.click(screen.getByRole("button", { name: "Reset settings" }));
      expect(state.reset).toHaveBeenCalledTimes(1);
      const resetOrder = state.reset.mock.invocationCallOrder[0];
      const writes = state.update.mock.calls;
      // Every restore lands AFTER the reset.
      for (const order of state.update.mock.invocationCallOrder) {
        expect(order).toBeGreaterThan(resetOrder);
      }
      expect(Object.fromEntries(writes)).toEqual(team);
      // selectedTeam is restored before its touched flag, because writing
      // selectedTeam marks it touched.
      const keys = writes.map(([k]) => k);
      expect(keys.indexOf("selectedTeam")).toBeLessThan(keys.indexOf("selectedTeamTouched"));
      expect(screen.queryByRole("dialog")).toBeNull();
    },
    SLOW,
  );
});

describe("5. source Status / Voting on come from the board's own report", () => {
  const keys = votingFixture.sources.map((s) => s.key);

  it(
    "a stale source the rows still carry values for reads Stale — not Live",
    () => {
      setData({ sourceVotingStatus: votingFixture }, { rows: rowsCoveringEverySource(keys) });
      render(<SettingsPage />);
      const stale = screen.getByTestId("settings-src-status-idpShowCombined");
      expect(stale.textContent).toBe("Stale — Not Voting");
      expect(screen.getByTestId("settings-src-voting-on-idpShowCombined").textContent).toBe(
        "0 players",
      );
      const ktc = screen.getByTestId("settings-src-status-ktcCrowdSfTep");
      expect(ktc.textContent).toBe("Active — 100%");
      expect(screen.getByTestId("settings-src-voting-on-ktcCrowdSfTep").textContent).toBe(
        "455 players + 48 picks",
      );
      const panel = rankingSourcesPanel();
      expect(panel.textContent).not.toMatch(/\bLive\b|\bIdle\b/);
    },
    SLOW,
  );

  it(
    "a registered source the report omits is labelled not reported — never Live, never 0",
    () => {
      setData({ sourceVotingStatus: votingFixture }, { rows: rowsCoveringEverySource(["dlfValuesSfTep"]) });
      render(<SettingsPage />);
      expect(screen.getByTestId("settings-src-status-dlfValuesSfTep").textContent).toBe(
        "Not reported",
      );
      expect(screen.getByTestId("settings-src-voting-on-dlfValuesSfTep").textContent).toBe("—");
    },
    SLOW,
  );

  it(
    "a board without the report labels every source not reported, whatever the rows hold",
    () => {
      setData({ privateSourceAvailability: {} }, { rows: rowsCoveringEverySource(keys) });
      render(<SettingsPage />);
      const panel = rankingSourcesPanel();
      const statuses = panel.querySelectorAll('[data-testid^="settings-src-status-"]');
      expect(statuses.length).toBeGreaterThan(3);
      for (const s of statuses) expect(s.textContent).toBe("Not reported");
      for (const c of panel.querySelectorAll('[data-testid^="settings-src-voting-on-"]')) {
        expect(c.textContent).toBe("—");
      }
    },
    SLOW,
  );

  it(
    "a stale source's row reads as the registry default beside its Not Voting status",
    () => {
      setData({ sourceVotingStatus: votingFixture });
      render(<SettingsPage />);
      const row = screen.getByTestId("settings-src-row-idpShowCombined");
      expect(within(row).getByTestId("settings-src-status-idpShowCombined").textContent).toBe(
        "Stale — Not Voting",
      );
      const include = within(row).getByRole("checkbox");
      // Its name never claims the source is in the blend.
      expect(include.getAttribute("aria-label")).toMatch(/by registry default/);
      expect(include.getAttribute("aria-label")).toMatch(/Status shows whether it voted/);
      expect(include.getAttribute("aria-label")).not.toMatch(/ in blend/);
      expect(within(row).getByTestId("settings-src-base-weight-idpShowCombined").textContent).toBe(
        "1.0",
      );
    },
    SLOW,
  );

  it(
    "an unreported source's base weight is a dash, never the registry copy",
    () => {
      setData({ privateSourceAvailability: {} });
      render(<SettingsPage />);
      const panel = rankingSourcesPanel();
      const cells = panel.querySelectorAll('[data-testid^="settings-src-base-weight-"]');
      expect(cells.length).toBeGreaterThan(3);
      for (const c of cells) expect(c.textContent).toBe("—");
    },
    SLOW,
  );

  it(
    "mobile states the status as text, not only as the coloured dot",
    () => {
      setData({ sourceVotingStatus: votingFixture });
      render(<SettingsPage />);
      const row = screen.getByTestId("settings-src-row-idpShowCombined");
      const mobile = row.querySelector(".settings-src-covered-mobile");
      expect(mobile.textContent).toMatch(/Stale — Not Voting/);
      expect(mobile.textContent).toMatch(/voting on 0 players/);
    },
    SLOW,
  );

  it(
    "while the board is still loading the status says so instead of Idle",
    () => {
      setData(null, { loading: true });
      render(<SettingsPage />);
      expect(screen.getByTestId("settings-src-status-fantasyCalc").textContent).toBe("Loading…");
    },
    SLOW,
  );
});

describe("6. every form control has a programmatic name", () => {
  it(
    "ROS source switches and weights, the watchlist input and the email field are named",
    () => {
      state.serverBacked = true;
      render(<SettingsPage />);
      openSection("Rest-of-Season Engine");
      openSection("Notifications");
      openSection("Watchlist");
      expect(screen.getAllByRole("checkbox", { name: / ROS source on$/ }).length).toBeGreaterThan(0);
      expect(screen.getAllByRole("spinbutton", { name: / ROS weight$/ }).length).toBeGreaterThan(0);
      expect(screen.getByRole("combobox", { name: "Add player by name to watchlist" })).toBeTruthy();
      expect(screen.getByLabelText("Email address").getAttribute("type")).toBe("email");
    },
    SLOW,
  );

  it(
    "no input, select or textarea on the page is unnamed",
    () => {
      state.serverBacked = true;
      const { container } = render(<SettingsPage />);
      const unnamed = [];
      for (const el of container.querySelectorAll("input, select, textarea")) {
        if (el.type === "hidden") continue;
        const named =
          el.getAttribute("aria-label") ||
          el.getAttribute("aria-labelledby") ||
          (el.id && container.querySelector(`label[for="${el.id}"]`)) ||
          el.closest("label");
        if (!named) unnamed.push(el.outerHTML.slice(0, 120));
      }
      expect(unnamed).toEqual([]);
    },
    SLOW,
  );

  it(
    "a control's visible label is part of its name (WCAG 2.5.3 label in name)",
    () => {
      state.serverBacked = true;
      const { container } = render(<SettingsPage />);
      openSection("Watchlist");
      const mismatched = [];
      for (const el of container.querySelectorAll("input, select, textarea")) {
        const name = (el.getAttribute("aria-label") || "").toLowerCase();
        if (!name) continue;
        // A visible placeholder must appear in the aria-label.
        const placeholder = (el.getAttribute("placeholder") || "").toLowerCase();
        if (placeholder && !name.includes(placeholder)) mismatched.push(el.outerHTML.slice(0, 120));
        // An aria-label overrides an associated <label>; the label's text must
        // then be in it.
        const label = el.id && container.querySelector(`label[for="${el.id}"]`);
        const labelText = label ? label.textContent.trim().toLowerCase() : "";
        if (labelText && !name.includes(labelText)) mismatched.push(el.outerHTML.slice(0, 120));
      }
      expect(mismatched).toEqual([]);
      // The Valuation select is named by its visible "Value basis" label.
      expect(screen.getByRole("combobox", { name: "Value basis" })).toBeDisabled();
    },
    SLOW,
  );
});
