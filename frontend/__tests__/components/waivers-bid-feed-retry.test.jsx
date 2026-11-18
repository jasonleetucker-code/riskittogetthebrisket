// /waivers bid cells: a pending bid request and a failed one are different
// facts, and a failed one offers a Retry (verified defect 4, 2026-11-16 sweep).
//
// Before: useWaiverAnalysis set its bid payload to null on a non-OK
// response, a malformed body, a network error OR an abort, and exposed
// neither a loading flag nor a refetch — so every bid cell read the
// cause-less "Bids not loaded" whether the request was still in flight or
// had failed, and a failure could only be cleared by reloading the page.
//
// These run the REAL hook against a stubbed fetch and render the real page;
// only the board computation is pinned (``computeWaiverAnalysis`` → one
// move) so the only moving part is the bid request.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

const MOVE = {
  add: { name: "Emeka Egbuka", pos: "WR", team: "TB" },
  drop: { name: "Old Guy", pos: "WR" },
  netGain: 900,
  upgradeTier: "strong",
  isRookie: false,
};

const ANALYSIS = {
  addable: [],
  droppable: [],
  bestMoves: [MOVE],
  bestUniqueUpgradeSet: [],
  summary: {
    bestAddable: MOVE.add,
    bestGain: 900,
    addableCount: 1,
    droppableCount: 0,
    rookieAddCount: 0,
    rosterSize: 20,
    freeAgentPoolSize: 300,
  },
  dropState: { state: "ok", reason: "", reasonText: "", undroppableCount: 0 },
};

vi.mock("@/lib/waiver-logic", async (importOriginal) => ({
  ...(await importOriginal()),
  computeWaiverAnalysis: () => ANALYSIS,
}));
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({
    privateDataEnabled: true,
    rows: [{ name: "Emeka Egbuka", pos: "WR", rankDerivedValue: 3100 }],
    rawData: { sleeper: { teams: [] } },
    loading: false,
    error: null,
  }),
}));
vi.mock("@/app/AppShellWrapper", () => ({ useAuthContext: () => ({ authenticated: true }) }));
vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ selectedLeague: { key: "dynasty_main", displayName: "Main", idpEnabled: true } }),
}));
const TEAM = { name: "Mine", players: [], faabRemaining: 63 };
vi.mock("@/components/useTeam", () => ({
  // No ownerId: keeps the lazy Perfect Waivers panel (and its fetch) out,
  // so the only fetch on the page is the bid POST.
  useTeam: () => ({ selectedTeam: TEAM, loading: false, leagueMismatch: false, availableTeams: [TEAM] }),
}));
vi.mock("@/components/useRosterIntelligence", () => ({
  useRosterIntelligence: () => ({ loading: false, data: null, failure: null }),
}));
vi.mock("@/components/useSettings", () => ({
  useSettings: () => ({ settings: {}, hydrated: true, update: vi.fn() }),
}));
vi.mock("@/components/waivers/ManualAddDrop", () => ({ default: () => null }));
vi.mock("@/components/waivers/BestAvailableIdps", () => ({ default: () => null }));
vi.mock("@/components/TeamSwitcher", () => ({ default: () => null }));
vi.mock("@/components/shell/RelatedLinks", () => ({ default: () => null }));

import WaiversPage from "@/app/waivers/page";

const PRICED = {
  leagueKey: "dynasty_main",
  bidMethodology: "market_aware",
  by_position: {
    WR: [
      {
        name: "Emeka Egbuka",
        position: "WR",
        consensusValue: 3100,
        bid: { aggressive: 12, reasonable: 8, lowball: 3 },
      },
    ],
  },
};

function json(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function bidFigures() {
  const table = screen.getByRole("table", { name: /Top single-transaction add\/drop upgrades/ });
  const figures = within(table).getAllByTestId("waiver-bid-figure");
  expect(figures.length).toBeGreaterThan(0);
  return figures;
}

function expectAllFigures(state, text) {
  for (const f of bidFigures()) {
    expect(f).toHaveAttribute("data-state", state);
    expect(f.textContent).toContain(text);
  }
}

afterEach(() => vi.unstubAllGlobals());

describe("/waivers bid feed — loading, failed, retry", () => {
  let pending;
  beforeEach(() => {
    pending = [];
  });

  it("a bid request in flight reads 'Loading bid…', not 'Bids not loaded', and offers no Retry", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise((resolve) => pending.push(resolve))));
    render(<WaiversPage />);

    await waitFor(() => expect(pending.length).toBe(1));
    expectAllFigures("loading", "Loading bid…");
    expect(screen.queryByText("Bids not loaded")).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();

    await act(async () => pending[0](json(PRICED)));
    await waitFor(() => expectAllFigures("priced", "$8"));
  });

  it.each([
    ["a 5xx response", async () => json({ error: "failed: engine" }, 500)],
    ["a rejected fetch", async () => { throw new TypeError("Failed to fetch"); }],
  ])("%s reads 'Bids failed to load' with a Retry banner, never the page error", async (_label, impl) => {
    vi.stubGlobal("fetch", vi.fn(impl));
    render(<WaiversPage />);

    await waitFor(() => expectAllFigures("failed", "Bids failed to load"));
    expect(screen.getByText("FAAB bids failed to load")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    // Optional enrichment: the page's own error state stays off.
    expect(screen.queryByText("Waiver analysis failed")).toBeNull();
  });

  it("Retry re-issues the request, reads loading while it is in flight, then shows the priced bids", async () => {
    let calls = 0;
    const fetchMock = vi.fn(() => {
      calls += 1;
      if (calls === 1) return Promise.resolve(json({ error: "Live contract not loaded yet." }, 503));
      return new Promise((resolve) => pending.push(resolve));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WaiversPage />);

    const retry = await screen.findByRole("button", { name: "Retry" });
    expectAllFigures("failed", "Bids failed to load");

    fireEvent.click(retry);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    // The same request again — same league, same balance.
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual(
      JSON.parse(fetchMock.mock.calls[0][1].body),
    );
    // The stale failure does not outlive the retry.
    expectAllFigures("loading", "Loading bid…");
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();

    await act(async () => pending[0](json(PRICED)));
    await waitFor(() => expectAllFigures("priced", "$8"));
    expect(screen.queryByText("FAAB bids failed to load")).toBeNull();
  });
});
