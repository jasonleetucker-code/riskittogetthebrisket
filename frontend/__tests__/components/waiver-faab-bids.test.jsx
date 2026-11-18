// useWaiverAnalysis fetches the ONE thing on /waivers it cannot
// compute: the backend FAAB bids.  ``computeWaiverAnalysis`` runs over
// contract rows, and contract rows carry values, not bids — so without
// this fetch the "Best add/drop moves" FAAB column is "—" on every row.
//
// The contract pinned here: a 503, a 401, a malformed body or a dead
// network leaves ``faabIndex`` null and ``error`` untouched.  The
// add/drop tables work fine without a bid, so an optional column that
// failed to load must never raise the page's error banner.  It is NOT
// silent, though (2026-11-16 sweep, defect 4): ``bidFeed`` says
// "loading" while the request is in flight and "failed" once it failed —
// never after an abort — and ``retryBids`` re-issues it.  The page-level
// rendering of those states is pinned in waivers-bid-feed-retry.test.jsx.
//
// Also pinned: the request carries the active leagueKey and the
// selected team's faabRemaining, and no request fires at all before a
// team is chosen.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

const mockUseApp = vi.fn();
const mockUseLeague = vi.fn();
const mockUseTeam = vi.fn();

vi.mock("@/components/AppShell", () => ({ useApp: () => mockUseApp() }));
vi.mock("@/components/useLeague", () => ({ useLeague: () => mockUseLeague() }));
vi.mock("@/components/useTeam", () => ({ useTeam: () => mockUseTeam() }));
// The cut-ladder fetch (C2-DROP-01) is its own hook with its own tests
// (waiver-cut-ladder.test.jsx); stubbed settled here so the ONLY fetch
// these tests observe is the bid POST they are about.
vi.mock("@/components/useRosterIntelligence", () => ({
  useRosterIntelligence: () => ({ loading: false, data: null, failure: { kind: "error", message: "stub" } }),
}));

import { useWaiverAnalysis } from "@/components/useWaiverAnalysis";
import { waiverBidForRow } from "@/lib/waiver-faab";

// Every bidFeed value this Probe ever rendered, in order — so a test can
// assert a state was NEVER shown, not just that it is gone now.
const feedHistory = [];

function Probe() {
  const { faabIndex, error, bidFeed, retryBids } = useWaiverAnalysis({});
  const bid = waiverBidForRow(faabIndex, { name: "Emeka Egbuka", pos: "WR" });
  feedHistory.push(bidFeed);
  return (
    <div>
      <span data-testid="index">{faabIndex ? "present" : "null"}</span>
      <span data-testid="bid">{bid ? String(bid.reasonable) : "—"}</span>
      <span data-testid="error">{error ? String(error) : "none"}</span>
      <span data-testid="feed">{bidFeed === null ? "null" : String(bidFeed)}</span>
      <button type="button" onClick={retryBids}>retry</button>
    </div>
  );
}

const ROWS = [
  {
    name: "Emeka Egbuka",
    pos: "WR",
    rankDerivedValue: 3100,
    sourceCount: 4,
    assetClass: "offense",
    confidenceBucket: "medium",
  },
];

const OK_PAYLOAD = {
  by_position: {
    WR: [
      {
        name: "Emeka Egbuka",
        position: "WR",
        consensusValue: 3100,
        adjustedValue: 3100,
        rank: 88,
        isRookie: true,
        bid: { aggressive: 12, reasonable: 8, lowball: 3 },
      },
    ],
  },
  by_family: {},
  total: 1,
  leagueKey: "dynasty_main",
};

function setContexts({ team = { name: "Mine", players: ["Somebody Old"], faabRemaining: 63 } } = {}) {
  mockUseApp.mockReturnValue({
    rows: ROWS,
    rawData: { sleeper: { teams: [] } },
    loading: false,
    error: null,
  });
  mockUseLeague.mockReturnValue({
    selectedLeague: { key: "dynasty_main", displayName: "Main", idpEnabled: true },
  });
  mockUseTeam.mockReturnValue({
    selectedTeam: team,
    leagueMismatch: false,
    availableTeams: [team].filter(Boolean),
  });
}

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

beforeEach(() => {
  mockUseApp.mockReset();
  mockUseLeague.mockReset();
  mockUseTeam.mockReset();
  feedHistory.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useWaiverAnalysis FAAB bid fetch", () => {
  it("joins backend bids onto the client-computed rows on success", async () => {
    setContexts();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(OK_PAYLOAD)));

    render(<Probe />);
    await waitFor(() => expect(screen.getByTestId("index")).toHaveTextContent("present"));
    expect(screen.getByTestId("bid")).toHaveTextContent("8");
    expect(screen.getByTestId("error")).toHaveTextContent("none");
    // Settled with a usable board: no stated cause, the index answers.
    expect(screen.getByTestId("feed")).toHaveTextContent("null");
    expect(feedHistory).not.toContain("failed");
  });

  it("sends leagueKey and the team's faabRemaining in the POST body", async () => {
    setContexts();
    const fetchMock = vi.fn(async () => jsonResponse(OK_PAYLOAD));
    vi.stubGlobal("fetch", fetchMock);

    render(<Probe />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/waiver/suggestions");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body);
    expect(body.leagueKey).toBe("dynasty_main");
    expect(body.faabRemaining).toBe(63);
  });

  it("sends the selected team's ownerId — this is the fix for the ceiling-only fallback bug", async () => {
    // Regression: before this fix, /waivers' main table never sent
    // teamOwnerId at all, so the backend could never run the
    // market-aware engine for it — every row silently fell back to
    // the fixed-fraction ceiling_only_estimate shim, which is exactly
    // what produced the observed $56/$28/$80 Cyrus Allen bug.
    setContexts({
      team: { name: "Collin", ownerId: "831633191830933504", players: [], faabRemaining: 63 },
    });
    const fetchMock = vi.fn(async () => jsonResponse(OK_PAYLOAD));
    vi.stubGlobal("fetch", fetchMock);

    render(<Probe />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.teamOwnerId).toBe("831633191830933504");
  });

  it("re-fetches when the selected team's ownerId changes, even if a team was already selected", async () => {
    setContexts({ team: { name: "Collin", ownerId: "owner-a", players: [], faabRemaining: 63 } });
    const fetchMock = vi.fn(async () => jsonResponse(OK_PAYLOAD));
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = render(<Probe />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    mockUseTeam.mockReturnValue({
      selectedTeam: { name: "Someone Else", ownerId: "owner-b", players: [], faabRemaining: 40 },
      leagueMismatch: false,
      availableTeams: [],
    });
    rerender(<Probe />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const secondBody = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(secondBody.teamOwnerId).toBe("owner-b");
  });

  // Every failure below is the SAME observable outcome: no index, no
  // page error — and a STATED failure (``bidFeed: "failed"``), so the
  // page can say the bids failed and offer a Retry instead of a blank.
  // (A 2xx body carrying ``error`` is malformed: the endpoint states
  // every error with a non-2xx status.)
  it.each([
    ["503 data not ready", async () => jsonResponse({ error: "Live contract not loaded yet." }, 503)],
    ["401 signed out", async () => jsonResponse({ error: "unauthorized" }, 401)],
    ["500 engine failure", async () => jsonResponse({ error: "failed" }, 500)],
    ["200 with an unusable body", async () => jsonResponse({ error: "unknown_league" })],
    ["200 with a non-object body", async () => jsonResponse("nope")],
    ["network failure", async () => { throw new TypeError("connect ECONNREFUSED"); }],
    ["malformed JSON", async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError("bad json"); } })],
  ])("states 'failed' (no index, no page error) on %s", async (_label, impl) => {
    setContexts();
    vi.stubGlobal("fetch", vi.fn(impl));

    render(<Probe />);
    // In flight first, then the settled failure.
    expect(feedHistory[0]).toBe("loading");
    await waitFor(() => expect(screen.getByTestId("feed")).toHaveTextContent("failed"));
    expect(screen.getByTestId("bid")).toHaveTextContent("—");
    expect(screen.getByTestId("index")).toHaveTextContent("null");
    // The page's error banner is driven by ``error`` — a failed bid
    // fetch must never light it.
    expect(screen.getByTestId("error")).toHaveTextContent("none");
  });

  it("an abort is never 'failed': the superseding request reads 'loading', then its answer", async () => {
    // Team A's request honours its abort signal; team B's resolves on demand.
    const resolvers = [];
    const fetchMock = vi.fn((_url, init) => new Promise((resolve, reject) => {
      init.signal.addEventListener("abort", () => {
        reject(new DOMException("The operation was aborted.", "AbortError"));
      });
      resolvers.push(resolve);
    }));
    vi.stubGlobal("fetch", fetchMock);
    setContexts({ team: { name: "A", ownerId: "owner-a", players: [], faabRemaining: 63 } });

    const { rerender } = render(<Probe />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("feed")).toHaveTextContent("loading");

    mockUseTeam.mockReturnValue({
      selectedTeam: { name: "B", ownerId: "owner-b", players: [], faabRemaining: 40 },
      leagueMismatch: false,
      availableTeams: [],
    });
    rerender(<Probe />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    // A's request was aborted; B's is in flight.
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
    expect(screen.getByTestId("feed")).toHaveTextContent("loading");

    await act(async () => resolvers[1](jsonResponse(OK_PAYLOAD)));
    await waitFor(() => expect(screen.getByTestId("index")).toHaveTextContent("present"));
    expect(screen.getByTestId("feed")).toHaveTextContent("null");
    expect(feedHistory).not.toContain("failed");
  });

  it("an unmount abort settles nothing (no state update after unmount)", async () => {
    const fetchMock = vi.fn((_url, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener("abort", () => {
        reject(new DOMException("The operation was aborted.", "AbortError"));
      });
    }));
    vi.stubGlobal("fetch", fetchMock);
    setContexts();
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { unmount } = render(<Probe />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => {});
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
    expect(feedHistory).not.toContain("failed");
    errorSpy.mockRestore();
  });

  it("retryBids re-issues the request for the same identity and clears a stale failure", async () => {
    let calls = 0;
    const resolvers = [];
    const fetchMock = vi.fn(() => {
      calls += 1;
      if (calls === 1) return Promise.resolve(jsonResponse({ error: "failed" }, 500));
      return new Promise((resolve) => resolvers.push(resolve));
    });
    vi.stubGlobal("fetch", fetchMock);
    setContexts();

    render(<Probe />);
    await waitFor(() => expect(screen.getByTestId("feed")).toHaveTextContent("failed"));

    fireEvent.click(screen.getByRole("button", { name: "retry" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][1].body).toBe(fetchMock.mock.calls[0][1].body);
    expect(screen.getByTestId("feed")).toHaveTextContent("loading");

    await act(async () => resolvers[0](jsonResponse(OK_PAYLOAD)));
    await waitFor(() => expect(screen.getByTestId("feed")).toHaveTextContent("null"));
    expect(screen.getByTestId("bid")).toHaveTextContent("8");
  });

  it("does not fire before a team is selected", async () => {
    setContexts({ team: null });
    const fetchMock = vi.fn(async () => jsonResponse(OK_PAYLOAD));
    vi.stubGlobal("fetch", fetchMock);

    render(<Probe />);
    await waitFor(() => expect(screen.getByTestId("index")).toHaveTextContent("null"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not fire when the loaded league doesn't match", async () => {
    setContexts();
    mockUseTeam.mockReturnValue({
      selectedTeam: { name: "Mine", players: [], faabRemaining: 63 },
      leagueMismatch: true,
      availableTeams: [],
    });
    const fetchMock = vi.fn(async () => jsonResponse(OK_PAYLOAD));
    vi.stubGlobal("fetch", fetchMock);

    render(<Probe />);
    await waitFor(() => expect(screen.getByTestId("index")).toHaveTextContent("null"));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
