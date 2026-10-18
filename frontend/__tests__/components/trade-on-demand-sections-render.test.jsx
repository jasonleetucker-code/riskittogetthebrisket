/**
 * /trade on-demand sections render through the real page.
 *
 * SimulationPanel, KtcImportPanel and SuggestionsDesk moved out of the page
 * chunk behind React.lazy (frontend/__tests__/trade-on-demand-sections.test.js
 * pins the split).  This drives the PAGE — not the sections in isolation —
 * so a broken lazy wiring (wrong export name, missing Suspense, a gate that
 * never opens) fails here rather than in production:
 *
 *   - the suggestions desk renders without any interaction;
 *   - the simulation result renders once the simulator has a result, and
 *     not before;
 *   - the KTC import row renders when Import trade -> From KeepTradeCut URL
 *     is chosen (the full import round trip is trade-asset-quantity.test.jsx
 *     [10]).
 */
import { describe, expect, it, vi, beforeAll, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createSide, simulationSignature } from "@/lib/trade-logic";
import {
  COLD_LAZY_REVEAL,
  PREWARM_TIMEOUT_MS,
  prewarmTradeSections,
} from "../setup/trade-lazy-sections";

const SLEEPER_TEAMS = [
  { ownerId: "owner-a", name: "Team A", players: ["Bijan Robinson"], picks: [] },
  { ownerId: "owner-b", name: "Team B", players: ["Puka Nacua"], picks: [] },
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
    rawData: { currentDraftYear: 2026, sleeper: { teams: SLEEPER_TEAMS } },
  }),
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

// The simulator's state is the page's only input to SimulationPanel.
const sim = { result: null, error: null };
vi.mock("@/components/useTradeSimulator", () => ({
  useTradeSimulator: () => ({
    simulate: () => {},
    result: sim.result,
    loading: false,
    error: sim.error,
    reset: () => {},
    // The result answers the trade on screen (an empty trade, no team, this
    // league): /trade renders a result only for a matching signature (TC-A).
    signature: simulationSignature([createSide(0), createSide(1)], "", "dynasty_main"),
  }),
}));

let TradePage;

// Every section asserted here sits behind a lazy boundary.  Compile them all
// before any timed wait (see ../setup/trade-lazy-sections.js); this test used
// to flake under full-suite load on the first cold reveal.
beforeAll(async () => {
  await prewarmTradeSections();
}, PREWARM_TIMEOUT_MS);

beforeEach(async () => {
  window.localStorage.clear();
  sim.result = null;
  sim.error = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })),
  );
  ({ default: TradePage } = await import("@/app/trade/page"));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("/trade on-demand sections, rendered by the page", () => {
  it("renders the suggestions desk with no interaction", async () => {
    render(<TradePage />);
    expect(await screen.findByRole("heading", { name: "Trade suggestions" }, COLD_LAZY_REVEAL)).toBeTruthy();
    expect(await screen.findByLabelText("Your team", {}, COLD_LAZY_REVEAL)).toBeTruthy();
  });

  it("renders no simulation panel until the simulator has answered", async () => {
    render(<TradePage />);
    await screen.findByRole("heading", { name: "Trade suggestions" }, COLD_LAZY_REVEAL);
    expect(screen.queryByRole("heading", { name: /^Impact on / })).toBeNull();
    expect(screen.queryByText("Simulation failed")).toBeNull();
  });

  it("renders the simulation result once there is one", async () => {
    sim.result = {
      team: { name: "Team A" },
      before: { totalValue: 1000 },
      after: { totalValue: 1200 },
      delta: { totalValue: 200, byPosition: {} },
      equity: 200,
      unresolvedIn: [],
      unresolvedOut: [],
    };
    render(<TradePage />);
    // TC-D2 / TCM-H13: the result lives in the Roster drilldown.
    await userEvent.click(await screen.findByRole("tab", { name: "Roster" }));
    expect(
      await screen.findByRole("heading", { name: "Impact on Team A" }, COLD_LAZY_REVEAL),
    ).toBeTruthy();
  });

  it("renders the simulation error the same way", async () => {
    sim.error = "simulate exploded";
    render(<TradePage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Roster" }));
    expect(await screen.findByText("Simulation failed", {}, COLD_LAZY_REVEAL)).toBeTruthy();
  });

  it("renders the KTC import row when Import trade -> From KeepTradeCut URL is chosen", async () => {
    render(<TradePage />);
    expect(screen.queryByLabelText("KeepTradeCut trade-calculator URL")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Import trade" }));
    await userEvent.click(screen.getByRole("button", { name: "From KeepTradeCut URL" }));
    expect(
      await screen.findByLabelText("KeepTradeCut trade-calculator URL", {}, COLD_LAZY_REVEAL),
    ).toBeTruthy();
  });
});
