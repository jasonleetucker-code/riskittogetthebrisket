/**
 * /trade reads the War Room's season-odds capability (DYN10 #4,
 * `tradeTitleOdds`, owner-held flag `trade_title_odds_lens`, default OFF) from
 * AppShell's context — `useApp().capabilities` — and nowhere else.
 *
 * Why it matters (PR #2312): importing `useAuthContext` from
 * `@/app/AppShellWrapper` into the page put the shell module in /trade's
 * module graph, which regrouped webpack's shared chunks and copied design-
 * system modules into /league's page chunk (49.0 KB -> 53.0 KB against a 50 KB
 * budget).  AppShell already receives the same capability map
 * (`auth.features`) from AppShellWrapper; exposing it on the context it
 * already provides adds no import edge.
 *
 * Pinned here:
 *   1. the page hands `titleOddsAvailable` to the War Room exactly when
 *      `useApp().capabilities.tradeTitleOdds.available === true` (never on a
 *      missing map, a missing entry, or `available: false`);
 *   2. AppShell exposes the `capabilities` prop on `useApp()` from BOTH shells
 *      (the private shell and the no-player-data shell), and `null` by default;
 *   3. the page does not import the auth context module.
 */
import fs from "node:fs";
import path from "node:path";
import url from "node:url";
import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Every mocked hook returns STABLE identities, as the real ones do: a fresh
// array, object or function per render re-runs the page's effects forever.
const hoisted = vi.hoisted(() => ({
  capabilities: null,
  pathname: "/trade",
  rows: [],
  rawData: { currentDraftYear: 2026, sleeper: { teams: [] } },
  settings: {},
  noop: () => {},
  appValues: new Map(),
}));

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal()),
  usePathname: () => hoisted.pathname,
}));

vi.mock("@/components/AppShell", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    // The page's only read of the shell context.  `actual.default` stays the
    // real AppShell for the provider tests below.
    useApp: () => {
      const caps = hoisted.capabilities;
      if (!hoisted.appValues.has(caps)) {
        hoisted.appValues.set(caps, {
          openPlayerPopup: hoisted.noop,
          registerAddToTrade: hoisted.noop,
          capabilities: caps,
        });
      }
      return hoisted.appValues.get(caps);
    },
  };
});

// The War Room is the page's lazily loaded Final Decision; a stub reports the
// one prop under test.
vi.mock("@/components/trade/TradeWarRoom", () => ({
  default: (props) => (
    <div data-testid="war-room-stub" data-title-odds={String(props.titleOddsAvailable)} />
  ),
}));

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: null,
    failure: null,
    retry: hoisted.noop,
    rows: hoisted.rows,
    siteKeys: hoisted.rows,
    rawData: hoisted.rawData,
  }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({
    settings: hoisted.settings,
    setSettings: hoisted.noop,
    update: hoisted.noop,
    hydrated: true,
  }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({
    selectedTeam: null,
    setSelectedTeam: hoisted.noop,
    idpEnabled: true,
    leagueMismatch: false,
    selectedLeagueKey: "dynasty_main",
    leagueLoading: false,
    loading: false,
  }),
}));

vi.setConfig({ testTimeout: 30000 });

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "..", "..");

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState({}, "", "/trade");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })),
  );
});

afterEach(() => {
  hoisted.capabilities = null;
  hoisted.pathname = "/trade";
  vi.unstubAllGlobals();
});

async function warRoomTitleOddsProp(capabilities) {
  hoisted.capabilities = capabilities;
  const { default: TradePage } = await import("@/app/trade/page");
  const view = render(<TradePage />);
  const stub = await screen.findByTestId("war-room-stub", {}, { timeout: 10_000 });
  const value = stub.getAttribute("data-title-odds");
  view.unmount();
  return value;
}

describe("/trade derives the season-odds capability from useApp().capabilities", () => {
  it("offers the panel only when the capability says available: true", async () => {
    expect(await warRoomTitleOddsProp({ tradeTitleOdds: { available: true } })).toBe("true");
  });

  it.each([
    ["no capability map (not told)", null],
    ["a map without the entry", { consensusEdge: { available: true } }],
    ["available: false", { tradeTitleOdds: { available: false } }],
    ["a truthy non-boolean", { tradeTitleOdds: { available: "yes" } }],
  ])("does not offer it with %s", async (_label, capabilities) => {
    expect(await warRoomTitleOddsProp(capabilities)).toBe("false");
  });

  it("does not import the auth context module (it regroups shared chunks)", () => {
    const src = fs.readFileSync(path.join(ROOT, "app/trade/page.jsx"), "utf8");
    expect(src).not.toMatch(/from\s+["']@\/app\/AppShellWrapper["']/);
    expect(src).not.toMatch(/useAuthContext/);
    expect(src).toMatch(/capabilities\?\.tradeTitleOdds\?\.available === true/);
  });
});

describe("AppShell exposes its capabilities prop on the context", () => {
  async function capabilitiesSeenUnder(pathname, props) {
    hoisted.pathname = pathname;
    const actual = await vi.importActual("@/components/AppShell");
    const AppShell = actual.default;
    function Probe() {
      return <output data-testid="caps">{JSON.stringify(actual.useApp().capabilities)}</output>;
    }
    const view = render(
      <AppShell {...props}>
        <Probe />
      </AppShell>,
    );
    const seen = screen.getByTestId("caps").textContent;
    view.unmount();
    return JSON.parse(seen);
  }

  const CAPS = { tradeTitleOdds: { available: true }, waiverAdvisor: { available: false } };

  it("from the private (player-data) shell", async () => {
    expect(await capabilitiesSeenUnder("/trade", { authenticated: true, capabilities: CAPS })).toEqual(
      CAPS,
    );
  });

  it("from the no-player-data shell (/league)", async () => {
    expect(await capabilitiesSeenUnder("/league", { authenticated: true, capabilities: CAPS })).toEqual(
      CAPS,
    );
  });

  it("null when the shell is not told", async () => {
    expect(await capabilitiesSeenUnder("/trade", { authenticated: true })).toBeNull();
  });

  it("the context default (no provider) is null, which reads as do not offer", async () => {
    const actual = await vi.importActual("@/components/AppShell");
    function Probe() {
      return <output data-testid="caps">{JSON.stringify(actual.useApp().capabilities)}</output>;
    }
    render(<Probe />);
    expect(JSON.parse(screen.getByTestId("caps").textContent)).toBeNull();
  });
});
