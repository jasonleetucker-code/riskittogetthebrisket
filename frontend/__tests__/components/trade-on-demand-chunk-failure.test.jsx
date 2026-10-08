/**
 * /trade on-demand sections survive a failed chunk load.
 *
 * The realistic failure: deploy/deploy.sh swaps `.next` and deletes the old
 * build, so a /trade tab opened before a deploy 404s on its old chunk
 * hashes the first time it renders an on-demand section.  Without a
 * section-scoped boundary that rejection falls through to app/error.jsx and
 * replaces the WHOLE page.  React.lazy caches a rejected import, so a
 * remounting "Retry" would only re-throw — the section must offer a reload.
 *
 * Here the suggestions-desk and simulation-result modules fail to load (as
 * a missing chunk would) and the rest of /trade must keep rendering.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

function chunkLoadError(id) {
  const err = new Error(`Loading chunk ${id} failed.`);
  err.name = "ChunkLoadError";
  return err;
}

// The module itself fails to load, as a missing chunk would: the page's
// lazy import() REJECTS.  Both sections below are reached by the lazy
// render's own import first.  (Not Import KTC: its click handler prefetches
// before the lazy render, and vitest serves the REAL module to a second
// dynamic import after a mocked one — a test-runner artifact, webpack
// re-requesting a deleted chunk 404s again.  The KTC section uses the same
// `dyn` boundary, pinned by trade-on-demand-sections.test.js.)
vi.mock("@/app/trade/trade-suggestions-desk", () => {
  throw chunkLoadError(3589);
});
vi.mock("@/app/trade/trade-simulation-panel", () => {
  throw chunkLoadError(6842);
});

// Stable references: the page's effects depend on `rows` / `rawData`
// identity, so a fresh array per render would loop.
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
const RAW = { currentDraftYear: 2026, sleeper: { teams: [] } };

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({ loading: false, error: null, rows: ROWS, rawData: RAW }),
}));

vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {}, setSettings: () => {}, update: () => {}, hydrated: true }),
}));

vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({
    selectedTeam: null,
    setSelectedTeam: () => {},
    idpEnabled: true,
    leagueMismatch: false,
    selectedLeagueKey: "dynasty_main",
    loading: false,
  }),
}));

// The page's only input to the simulation section.
const sim = { result: null };
vi.mock("@/components/useTradeSimulator", () => ({
  useTradeSimulator: () => ({
    simulate: () => {},
    result: sim.result,
    loading: false,
    error: null,
    reset: () => {},
  }),
}));

let TradePage;
let reload;
const realLocation = window.location;

beforeEach(async () => {
  window.localStorage.clear();
  sim.result = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })),
  );
  // The boundary logs what it caught; keep the run quiet.
  vi.spyOn(console, "error").mockImplementation(() => {});
  reload = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...realLocation, reload },
  });
  ({ default: TradePage } = await import("@/app/trade/page"));
});

afterEach(() => {
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("/trade on-demand section whose chunk fails to load", () => {
  it("renders the section fallback in place, and the rest of /trade stays rendered", async () => {
    render(<TradePage />);
    expect(await screen.findByText("Trade suggestions unavailable")).toBeTruthy();
    // The page did not fall through to the route error screen: the builder,
    // controls and verdict are all still there.
    expect(screen.getByRole("button", { name: "Clear Trade" })).toBeTruthy();
    expect(screen.getByLabelText("Search to add a player to Side A")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Trade War Room" })).toBeTruthy();
  });

  it("offers a page reload, not a retry that would re-throw the cached rejection", async () => {
    render(<TradePage />);
    await screen.findByText("Trade suggestions unavailable");
    expect(screen.queryByRole("button", { name: "Retry this section" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Reload page" }));
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("a main action's section (the Simulate impact result) fails in place too", async () => {
    sim.result = { team: { name: "Team A" }, unresolvedIn: [], unresolvedOut: [] };
    render(<TradePage />);
    expect(await screen.findByText("Simulation result unavailable")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Clear Trade" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Trade War Room" })).toBeTruthy();
  });
});
