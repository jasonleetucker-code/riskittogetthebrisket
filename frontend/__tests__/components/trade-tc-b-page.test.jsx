/**
 * TC-B on /trade, rendered: the builder's display facts (position mix,
 * age, derived-pick PRIOR badge), the explicit 3+-team War Room limitation,
 * the immediate Second Opinions tally and the Next steps section.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import {
  COLD_LAZY_REVEAL,
  PREWARM_TIMEOUT_MS,
  prewarmTradeSections,
} from "../setup/trade-lazy-sections";

const ROWS = [
  {
    name: "Bijan Robinson",
    pos: "RB",
    assetClass: "offense",
    age: 24.6,
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
    age: null,
    playerId: "9493",
    rankDerivedValue: 7000,
    values: { full: 7000 },
    rank: 3,
    blendedSourceRank: 3,
  },
  {
    name: "2027 Round 1",
    pos: "PICK",
    assetClass: "pick",
    rankDerivedValue: 4500,
    values: { full: 4500 },
    raw: {
      pickValueProvenance: {
        class: "derived_uniform_tier_ev",
        classification: "PRIOR",
        basis: ["2027 Early 1st", "2027 Mid 1st", "2027 Late 1st"],
      },
    },
  },
];

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: null,
    rows: ROWS,
    rawData: { currentDraftYear: 2026, sleeper: null },
  }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {}, setSettings: () => {}, update: () => {}, hydrated: true }),
}));

let TradePage;

// The War Room, tally and next steps are lazy sections: compile them before
// any timed wait (../setup/trade-lazy-sections.js).
beforeAll(async () => {
  await prewarmTradeSections();
}, PREWARM_TIMEOUT_MS);

beforeEach(async () => {
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })));
  ({ default: TradePage } = await import("@/app/trade/page"));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function seed(sides) {
  window.localStorage.setItem(
    "next_trade_workspace_v1",
    JSON.stringify({ version: 2, valueMode: "full", activeSide: 0, sides }),
  );
}

describe("/trade TC-B builder facts", () => {
  it("shows each side's position mix, a player's age, and the generic pick's prior", async () => {
    seed([
      { label: "A", assets: ["Bijan Robinson", "2027 Round 1", "2027 Round 1"], destinations: {} },
      { label: "B", assets: ["Puka Nacua"], destinations: {} },
    ]);
    render(<TradePage />);
    const mixes = await screen.findAllByTestId("trade-side-composition");
    expect(mixes.map((m) => m.textContent)).toEqual(["1 RB · 2 Picks", "1 WR"]);
    // Age on the row; a missing age is simply absent, never "Age 0".
    expect(screen.getByText(/RB · Age 24\.6 · Consensus/)).toBeInTheDocument();
    expect(screen.queryByText(/Age 0/)).toBeNull();
    const badge = screen.getByTestId("trade-asset-derived-pick");
    expect(badge.textContent).toBe("Generic: tier average (prior)");
    expect(badge.getAttribute("title")).toMatch(/2027 Early 1st, 2027 Mid 1st, 2027 Late 1st/);
  });
});

describe("/trade TC-B multi-team War Room limitation (TCM-G09)", () => {
  it("states that no YES / NO is computed for a 3-team trade", async () => {
    seed([
      { label: "A", assets: ["Bijan Robinson"], destinations: {} },
      { label: "B", assets: ["Puka Nacua"], destinations: {} },
      { label: "C", assets: ["2027 Round 1"], destinations: {} },
    ]);
    render(<TradePage />);
    const note = await screen.findByTestId("war-room-multi-team-limit");
    expect(note.textContent).toMatch(/no YES \/ NO is given for this 3-team trade/);
    expect(note.textContent).not.toMatch(/\b(YES|NO) —/);
    expect(screen.queryByRole("heading", { name: "Trade War Room" })).toBeNull();
  });

  it("a two-team trade keeps the War Room and shows no limitation", async () => {
    seed([
      { label: "A", assets: ["Bijan Robinson"], destinations: {} },
      { label: "B", assets: ["Puka Nacua"], destinations: {} },
    ]);
    render(<TradePage />);
    expect(
      await screen.findByRole("heading", { name: "Trade War Room" }, COLD_LAZY_REVEAL),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("war-room-multi-team-limit")).toBeNull();
  });
});

describe("/trade TC-B immediate tally and Next steps", () => {
  it("renders the one-glance tally outside the folded Second opinions panel", async () => {
    seed([
      { label: "A", assets: ["Bijan Robinson"], destinations: {} },
      { label: "B", assets: ["Puka Nacua"], destinations: {} },
    ]);
    render(<TradePage />);
    const tally = await screen.findByTestId("trade-opinion-tally", {}, COLD_LAZY_REVEAL);
    expect(tally.textContent).toMatch(/Second opinions/);
    // The per-source panel is still folded: its table is not mounted.
    expect(screen.queryByTestId("second-opinions-tally")).toBeNull();
  });

  it("renders Next steps once the trade has assets", async () => {
    seed([
      { label: "A", assets: ["Bijan Robinson"], destinations: {} },
      { label: "B", assets: [], destinations: {} },
    ]);
    render(<TradePage />);
    const next = await screen.findByTestId("trade-next-actions", {}, COLD_LAZY_REVEAL);
    expect(within(next).getByTestId("trade-next-database").querySelector("a").getAttribute("href")).toBe(
      "/market/trade-database?players=9509",
    );
    // No team is selected in this harness: the finder link says so.
    expect(within(next).getByTestId("trade-next-scan").textContent).toMatch(/Pick your team first/);
  });

  it("no Next steps on an empty trade", async () => {
    render(<TradePage />);
    await screen.findByRole("button", { name: /Clear Trade/ });
    expect(screen.queryByTestId("trade-next-actions")).toBeNull();
    expect(screen.queryByTestId("trade-opinion-tally")).toBeNull();
  });
});
