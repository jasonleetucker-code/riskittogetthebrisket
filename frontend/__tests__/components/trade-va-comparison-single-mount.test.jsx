/**
 * Release train 12 integration: the Value Adjustment comparison (#1826) is
 * defined ONCE on /trade and mounted through the Trade War Room's `vaSlot`
 * (#1827) in every War Room view.  This renders the REAL /trade page and
 * counts `va-comparison` in each War Room state: exactly one wherever two
 * sides hold assets, zero when only one side does (nothing to compare).
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import {
  COLD_LAZY_REVEAL,
  PREWARM_TIMEOUT_MS,
  prewarmTradeSections,
} from "../setup/trade-lazy-sections";
import CONSOLIDATION from "../fixtures/trade-war-room/consolidation.json";

const ROWS = [
  {
    name: "Bijan Robinson",
    pos: "RB",
    assetClass: "offense",
    playerId: "9509",
    rankDerivedValue: 8000,
    values: { full: 8000 },
    rank: 1,
    blendedSourceRank: 1,
  },
  {
    name: "Puka Nacua",
    pos: "WR",
    assetClass: "offense",
    playerId: "9493",
    rankDerivedValue: 7000,
    values: { full: 7000 },
    rank: 3,
    blendedSourceRank: 3,
  },
  {
    name: "Drake London",
    pos: "WR",
    assetClass: "offense",
    playerId: "9488",
    rankDerivedValue: 6000,
    values: { full: 6000 },
    rank: 5,
    blendedSourceRank: 5,
  },
];

// Per-test team state: which team the topbar has selected.
const team = { selected: null };
const OWNS_A = { ownerId: "owner-a", name: "Team A", players: ["Bijan Robinson"], picks: [] };
const OWNS_NEITHER = { ownerId: "owner-c", name: "Team C", players: [], picks: [] };

// Stable references, like the real hooks: a fresh array per render would
// re-run every effect keyed on the league's teams.
const RAW = { currentDraftYear: 2026, sleeper: { teams: [OWNS_A, OWNS_NEITHER] } };
vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({ loading: false, error: null, rows: ROWS, rawData: RAW }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {}, setSettings: () => {}, update: () => {}, hydrated: true }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({
    selectedTeam: team.selected,
    setSelectedTeam: () => {},
    idpEnabled: false,
    leagueMismatch: false,
    selectedLeagueKey: "main",
    leagueLoading: false,
    loading: false,
  }),
}));

// A page render crosses cold lazy boundaries (War Room, comparison): give each
// case room beyond the 5 s default.
vi.setConfig({ testTimeout: 30_000 });

let TradePage;

beforeAll(async () => {
  await prewarmTradeSections();
  ({ default: TradePage } = await import("@/app/trade/page"));
}, PREWARM_TIMEOUT_MS);

/** fetch: `/api/trade/analyze` answers as `analyze` says; everything else 404s. */
function stubFetch(analyze) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url, init) => {
      if (String(url).includes("/api/trade/analyze")) return analyze(init);
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    }),
  );
}
const never = (init) =>
  new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => {
      const e = new Error("aborted");
      e.name = "AbortError";
      reject(e);
    });
  });

function seed(sides) {
  window.localStorage.setItem(
    "next_trade_workspace_v1",
    JSON.stringify({ version: 2, valueMode: "full", activeSide: 0, sides }),
  );
}
const TWO_SIDES = [
  { label: "A", assets: ["Bijan Robinson"], destinations: {} },
  { label: "B", assets: ["Puka Nacua"], destinations: {} },
];

async function countAfter(ready) {
  render(<TradePage />);
  await ready();
  // The comparison is its own lazy section: wait for it to settle.
  await waitFor(
    () => expect(screen.queryAllByTestId("va-comparison").length).toBeGreaterThan(0),
    COLD_LAZY_REVEAL,
  ).catch(() => {});
  return screen.queryAllByTestId("va-comparison").length;
}

beforeEach(() => {
  window.localStorage.clear();
  team.selected = null;
  stubFetch(never);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("/trade mounts the Value Adjustment comparison exactly once", () => {
  it("no team selected: the War Room's idle view carries it", async () => {
    seed(TWO_SIDES);
    const n = await countAfter(() => screen.findAllByText(/Pick your team/, {}, COLD_LAZY_REVEAL));
    expect(n).toBe(1);
  });

  it("the side needs choosing: the side chooser's view carries it", async () => {
    team.selected = OWNS_NEITHER;
    seed(TWO_SIDES);
    const n = await countAfter(() =>
      screen.findByTestId("war-room-side-choice", {}, COLD_LAZY_REVEAL),
    );
    expect(n).toBe(1);
  });

  it("the analysis is loading", async () => {
    team.selected = OWNS_A;
    seed(TWO_SIDES);
    const n = await countAfter(() =>
      screen.findAllByText(/Analyzing this trade…/, {}, COLD_LAZY_REVEAL),
    );
    expect(n).toBe(1);
  });

  it("the analysis failed", async () => {
    team.selected = OWNS_A;
    stubFetch(() =>
      Promise.resolve({ ok: false, status: 500, json: async () => ({ error: "boom" }) }),
    );
    seed(TWO_SIDES);
    const n = await countAfter(() =>
      screen.findByTestId("war-room-error", {}, { timeout: 15_000 }),
    );
    expect(n).toBe(1);
  });

  it("the analysis is present", async () => {
    team.selected = OWNS_A;
    stubFetch(() => Promise.resolve({ ok: true, status: 200, json: async () => CONSOLIDATION }));
    seed(TWO_SIDES);
    const n = await countAfter(() =>
      screen.findByTestId("decision-headline", {}, { timeout: 15_000 }),
    );
    expect(n).toBe(1);
  });

  it("a 3-team trade: the War Room's multi-team view carries it", async () => {
    team.selected = OWNS_A;
    seed([...TWO_SIDES, { label: "C", assets: ["Drake London"], destinations: {} }]);
    const n = await countAfter(() =>
      screen.findByTestId("war-room-multi-team-limit", {}, COLD_LAZY_REVEAL),
    );
    expect(n).toBe(1);
  });

  it("only one side holds assets: nothing to compare, so none", async () => {
    team.selected = OWNS_A;
    seed([
      { label: "A", assets: ["Bijan Robinson"], destinations: {} },
      { label: "B", assets: [], destinations: {} },
    ]);
    render(<TradePage />);
    await screen.findByRole("heading", { name: "Trade War Room" }, COLD_LAZY_REVEAL);
    // Give the comparison's lazy section the same chance to appear.
    await new Promise((r) => setTimeout(r, 500));
    expect(screen.queryAllByTestId("va-comparison")).toHaveLength(0);
  });
});
