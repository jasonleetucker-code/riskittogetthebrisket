// C6-SIG-02 — the homepage ticker consumes the ONE Buy/Sell owner
// (/api/signals/reconciled), BUY global, SELL only for the selected roster,
// and fails closed for anyone without a private session.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

const appState = { rows: [], rawData: null, openPlayerPopup: vi.fn(), privateDataEnabled: true };
const authState = { authenticated: true };
const teamState = { selectedTeam: null, selectedLeagueKey: "dynasty_main", loading: false };

vi.mock("@/components/AppShell", () => ({ useApp: () => appState }));
vi.mock("@/app/AppShellWrapper", () => ({ useAuthContext: () => authState }));
vi.mock("@/components/useTeam", () => ({ useTeam: () => teamState }));
vi.mock("@/components/useNews", () => ({
  useNews: () => ({ loading: false, items: [], scored: [] }),
}));

import MarketTicker from "@/components/terminal/MarketTicker";
import { invalidateReconciledSignals } from "@/components/useReconciledSignals";

const ALPHA = { ownerId: "owner-1", name: "Alpha Team", players: ["Rostered Sell"] };
const BRAVO = { ownerId: "owner-2", name: "Bravo Team", players: [] };

function sig(emitter, domain, direction) {
  return { emitter, domain, direction, lineageGroup: emitter, ancestors: [], nativeLabel: direction };
}

function p(key, name, state, extra = {}) {
  return {
    playerKey: key,
    displayName: name,
    state,
    withheldBy: [],
    signals: [],
    collapsed: [],
    conflict: null,
    agreement: { buy: null, sell: null },
    board: { canonicalConsensusRank: 10, position: "WR", assetClass: "offense" },
    ...extra,
  };
}

function reconciled(team = ALPHA) {
  return {
    reconcilerVersion: "sig.2026-10-07.v1",
    team: { ownerId: team.ownerId, name: team.name },
    teamResolution: { requested: { ownerId: team.ownerId }, resolved: true, source: "explicit", reason: null },
    roster: { playerKeys: ["player:2", "player:5"], placement: "player_id", unresolvedCount: 0 },
    contract: {
      generatedAt: new Date().toISOString(),
      marketFreshness: { state: "fresh" },
    },
    emitters: [],
    players: [
      p("player:1", "Global Buy", "directional_buy_only", {
        signals: [sig("consensus_edge", "consensus", "buy")],
      }),
      p("player:2", "Rostered Sell", "directional_sell_only", {
        signals: [sig("bdvm_market_signal", "fundamental", "sell")],
      }),
      p("player:3", "Other Team Sell", "directional_sell_only", {
        signals: [sig("bdvm_market_signal", "fundamental", "sell")],
      }),
      p("player:5", "Rostered Conflict", "conflict", {
        conflict: {
          buy: [{ emitter: "consensus_edge", domain: "consensus" }],
          sell: [{ emitter: "bdvm_market_signal", domain: "fundamental" }],
          sharedAncestry: ["value_market_sources"],
        },
      }),
      p("player:7", "Withheld Player", "withheld", {
        withheldBy: [{ source: "canonical_quarantine", reason: "x" }],
        signals: [sig("consensus_edge", "consensus", "buy")],
      }),
    ],
  };
}

function okResponse(body) {
  return { ok: true, status: 200, json: async () => body };
}

function reconciledCalls() {
  return fetch.mock.calls.filter(([url]) => String(url).startsWith("/api/signals/reconciled"));
}

// Verdict slots, excluding the aria-hidden marquee clones.
function verdictSlots(container) {
  return [...container.querySelectorAll("li[data-verdict]:not([aria-hidden])")];
}

beforeEach(() => {
  invalidateReconciledSignals();
  appState.privateDataEnabled = true;
  // A canonical row WITH a rank move: the retired ticker rendered this as a
  // mover.  A verdict ticker must not.
  appState.rows = [{ name: "Old Mover", pos: "RB", rankChange: 25, canonicalConsensusRank: 4 }];
  appState.rawData = { generatedAt: new Date().toISOString(), sleeper: { teams: [ALPHA, BRAVO] } };
  authState.authenticated = true;
  teamState.selectedTeam = ALPHA;
  teamState.loading = false;
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okResponse(reconciled())));
});

describe("MarketTicker — canonical Buy/Sell", () => {
  it("reads the reconciler once, league scope, for the selected team and league", async () => {
    render(<MarketTicker />);
    await waitFor(() => expect(reconciledCalls()).toHaveLength(1));
    const url = new URL(reconciledCalls()[0][0], "http://x");
    expect(url.searchParams.get("scope")).toBe("league");
    expect(url.searchParams.get("team")).toBe("owner-1");
    expect(url.searchParams.get("leagueKey")).toBe("dynasty_main");
  });

  it("BUY global, SELL roster-only, conflict as CONFLICT, withheld never shown", async () => {
    const { container } = render(<MarketTicker />);
    await waitFor(() => expect(verdictSlots(container).length).toBeGreaterThan(0));
    const shown = Object.fromEntries(
      verdictSlots(container).map((li) => [li.textContent.match(/(Global Buy|Rostered Sell|Other Team Sell|Rostered Conflict|Withheld Player)/)?.[1], li.dataset.verdict]),
    );
    expect(shown).toEqual({
      "Rostered Sell": "sell",
      "Rostered Conflict": "conflict",
      "Global Buy": "buy",
    });
    expect(screen.getByText(/Sells: Alpha Team only/)).toBeTruthy();
  });

  it("does not render rank movers as ticker items (the retired page-local source)", async () => {
    const { container } = render(<MarketTicker />);
    await waitFor(() => expect(verdictSlots(container).length).toBeGreaterThan(0));
    expect(container.textContent).not.toContain("Old Mover");
  });

  it("no team selected: BUYs still show, no SELL items, and the rail says why", async () => {
    teamState.selectedTeam = null;
    const { container } = render(<MarketTicker />);
    await waitFor(() => expect(verdictSlots(container).length).toBeGreaterThan(0));
    const kinds = verdictSlots(container).map((li) => li.dataset.verdict);
    expect(kinds).toEqual(["buy"]);
    expect(screen.getByText(/no team selected/i)).toBeTruthy();
  });

  it("switching team drops the previous team's SELLs immediately", async () => {
    let resolveBravo;
    fetch.mockImplementation((url) =>
      String(url).includes("team=owner-2")
        ? new Promise((r) => {
            resolveBravo = r;
          })
        : Promise.resolve(okResponse(reconciled())),
    );
    const { container, rerender } = render(<MarketTicker />);
    await waitFor(() => expect(verdictSlots(container).some((li) => li.dataset.verdict === "sell")).toBe(true));
    teamState.selectedTeam = BRAVO;
    rerender(<MarketTicker />);
    // Before Bravo's payload arrives, nothing of Alpha's remains.
    expect(container.textContent).not.toContain("Rostered Sell");
    await waitFor(() => expect(typeof resolveBravo).toBe("function"));
    expect(container.textContent).not.toContain("Rostered Sell");
    await act(async () => {
      resolveBravo(okResponse({ ...reconciled(BRAVO), roster: { playerKeys: [], placement: "player_id", unresolvedCount: 0 } }));
    });
    await waitFor(() => expect(verdictSlots(container).length).toBeGreaterThan(0));
    expect(verdictSlots(container).map((li) => li.dataset.verdict)).toEqual(["buy"]);
  });
});

describe("MarketTicker — private, fail closed", () => {
  it("anonymous: never calls the private reconciler and shows no verdicts", async () => {
    authState.authenticated = false;
    const { container } = render(<MarketTicker />);
    await act(async () => {});
    expect(reconciledCalls()).toHaveLength(0);
    expect(verdictSlots(container)).toHaveLength(0);
    expect(screen.getByText(/Sign in to see Buy\/Sell signals/)).toBeTruthy();
  });

  it("public shell (no private data): never calls the reconciler", async () => {
    appState.privateDataEnabled = false;
    render(<MarketTicker />);
    await act(async () => {});
    expect(reconciledCalls()).toHaveLength(0);
  });

  it("a 401 hides the lane and is not retried on re-render (no 401 storm)", async () => {
    fetch.mockResolvedValue({ ok: false, status: 401, json: async () => ({ error: "auth_required" }) });
    const { container, rerender, unmount } = render(<MarketTicker />);
    await waitFor(() => expect(screen.getByText(/Sign in to see Buy\/Sell signals/)).toBeTruthy());
    rerender(<MarketTicker />);
    unmount();
    render(<MarketTicker />);
    await act(async () => {});
    expect(reconciledCalls()).toHaveLength(1);
    expect(verdictSlots(container)).toHaveLength(0);
  });

  it("a 503 says the data is not ready rather than 'no verdicts'", async () => {
    fetch.mockResolvedValue({ ok: false, status: 503, json: async () => ({ error: "data_not_ready" }) });
    render(<MarketTicker />);
    await waitFor(() => expect(screen.getByText(/board data not ready/)).toBeTruthy());
  });

  it("waits for team identity before fetching (one request, not two)", async () => {
    teamState.loading = true;
    const { rerender } = render(<MarketTicker />);
    await act(async () => {});
    expect(reconciledCalls()).toHaveLength(0);
    teamState.loading = false;
    rerender(<MarketTicker />);
    await waitFor(() => expect(reconciledCalls()).toHaveLength(1));
  });
});
