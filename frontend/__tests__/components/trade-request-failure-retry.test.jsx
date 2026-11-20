/**
 * /trade suggestion desk and KTC import — a failed request renders the shared
 * TradeToolErrorBanner (a readable sentence; a bare backend code never stands
 * in for it) with a "Try again" that re-issues the same request
 * (X-FRONTEND-FAILURE-SW).  Both used to print `data.error` raw — a code
 * such as `data_not_ready` on a 503 — with no retry.
 *
 * Run on the real page, so the classification in app/trade/page.jsx and the
 * lazily loaded desk components are exercised together.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  COLD_LAZY_REVEAL,
  PREWARM_TIMEOUT_MS,
  prewarmTradeSections,
} from "../setup/trade-lazy-sections";

const ROWS = [
  { name: "Bijan Robinson", playerId: "9509", pos: "RB", position: "RB", assetClass: "offense", rankDerivedValue: 8000, values: { full: 8000 }, rank: 1 },
  { name: "Puka Nacua", playerId: "9493", pos: "WR", position: "WR", assetClass: "offense", rankDerivedValue: 7000, values: { full: 7000 }, rank: 2 },
  { name: "Puka Two", playerId: "9999", pos: "WR", position: "WR", assetClass: "offense", rankDerivedValue: 3000, values: { full: 3000 }, rank: 40 },
];

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: null,
    rows: ROWS,
    rawData: { currentDraftYear: 2026, sleeper: { teams: [] } },
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
    leagueLoading: false,
    loading: false,
  }),
}));

vi.setConfig({ testTimeout: 30000 });

/** Answers each matching request from `answers` in order; anything else 404s. */
function scriptedFetch(match, answers) {
  const queue = [...answers];
  const fetchMock = vi.fn(async (url) => {
    if (match(String(url)) && queue.length) {
      const { status, body } = queue.shift();
      return { ok: status < 400, status, json: async () => body };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const callsTo = (fetchMock, part) => fetchMock.mock.calls.filter(([u]) => String(u).includes(part));

let TradePage;
beforeAll(async () => {
  await prewarmTradeSections();
}, PREWARM_TIMEOUT_MS);
beforeEach(async () => {
  window.localStorage.clear();
  window.history.replaceState({}, "", "/trade");
  ({ default: TradePage } = await import("@/app/trade/page"));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const EMPTY = { sellHigh: [], buyLow: [], consolidation: [], positionalUpgrades: [], totalSuggestions: 7 };

describe("/trade suggestions failure", () => {
  it("a 503 code reads as a sentence, and Try again re-requests suggestions", async () => {
    const fetchMock = scriptedFetch((u) => u.includes("/api/trade/suggestions"), [
      { status: 503, body: { error: "data_not_ready" } },
      { status: 200, body: EMPTY },
    ]);
    render(<TradePage />);
    const roster = await screen.findByLabelText("Roster", {}, COLD_LAZY_REVEAL);
    fireEvent.change(roster, { target: { value: "Bijan Robinson, Puka Nacua, Puka Two" } });
    expect(
      await screen.findByText(/rosters and values are not loaded on the server yet/, {}, { timeout: 3000 }),
    ).toBeInTheDocument();
    const before = callsTo(fetchMock, "/api/trade/suggestions").length;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(callsTo(fetchMock, "/api/trade/suggestions").length).toBe(before + 1),
    );
    expect(await screen.findByText(/7 suggestions/)).toBeInTheDocument();
  });

  it("the roster input check stays a plain sentence with no retry", async () => {
    scriptedFetch(() => false, []);
    render(<TradePage />);
    const roster = await screen.findByLabelText("Roster", {}, COLD_LAZY_REVEAL);
    fireEvent.change(roster, { target: { value: "Bijan Robinson" } });
    await userEvent.click(screen.getByRole("button", { name: "Get suggestions" }));
    expect(await screen.findByText("Enter at least 3 player names to get suggestions.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });
});

async function openKtcImport() {
  await userEvent.click(screen.getByRole("button", { name: "Import trade" }));
  await userEvent.click(await screen.findByRole("button", { name: "From KeepTradeCut URL" }));
  const url = await screen.findByLabelText("KeepTradeCut trade-calculator URL");
  fireEvent.change(url, {
    target: { value: "https://keeptradecut.com/trade-calculator?teamOne=1&teamTwo=2" },
  });
}

describe("/trade KTC import failure", () => {
  it("keeps the route's own sentence, and Try again re-sends the import", async () => {
    const fetchMock = scriptedFetch((u) => u.includes("/api/trade/import-ktc"), [
      {
        status: 500,
        body: {
          ok: false,
          error: "KTC import failed unexpectedly.",
          reason: "internal_error",
          detail: "KeyError: 'x'",
        },
      },
      {
        status: 200,
        body: { ok: true, sideOne: [{ name: "Bijan Robinson" }], sideTwo: [], unresolved: { sideOne: [], sideTwo: [] } },
      },
    ]);
    render(<TradePage />);
    await openKtcImport();
    await userEvent.click(screen.getByRole("button", { name: "Load trade" }));
    expect(await screen.findByText("KTC import failed unexpectedly.")).toBeInTheDocument();
    // Technical text is not the message.
    expect(screen.queryByText(/KeyError/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(callsTo(fetchMock, "/api/trade/import-ktc").length).toBe(2));
    expect(await screen.findByText(/Loaded 1\/1 players/)).toBeInTheDocument();
  });

  it("a 400 refusal is not retryable", async () => {
    scriptedFetch((u) => u.includes("/api/trade/import-ktc"), [
      { status: 400, body: { ok: false, error: "URL must be a keeptradecut.com trade-calculator link." } },
    ]);
    render(<TradePage />);
    await openKtcImport();
    await userEvent.click(screen.getByRole("button", { name: "Load trade" }));
    expect(
      await screen.findByText("URL must be a keeptradecut.com trade-calculator link."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });
});
