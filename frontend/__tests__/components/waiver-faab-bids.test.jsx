// useWaiverAnalysis fetches the ONE thing on /waivers it cannot
// compute: the backend FAAB bids.  ``computeWaiverAnalysis`` runs over
// contract rows, and contract rows carry values, not bids — so without
// this fetch the "Best add/drop moves" FAAB column is "—" on every row.
//
// The contract pinned here is SILENT VANISH, copied from the BDVM
// Fund-gap column on /rankings: a 503, a 401, a malformed body or a
// dead network leaves ``faabIndex`` null and ``error`` untouched.  The
// add/drop tables work fine without a bid, so an optional column that
// failed to load must never raise the page's error banner.
//
// Also pinned: the request carries the active leagueKey and the
// selected team's faabRemaining, and no request fires at all before a
// team is chosen.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const mockUseApp = vi.fn();
const mockUseLeague = vi.fn();
const mockUseTeam = vi.fn();

vi.mock("@/components/AppShell", () => ({ useApp: () => mockUseApp() }));
vi.mock("@/components/useLeague", () => ({ useLeague: () => mockUseLeague() }));
vi.mock("@/components/useTeam", () => ({ useTeam: () => mockUseTeam() }));

import { useWaiverAnalysis } from "@/components/useWaiverAnalysis";
import { waiverBidForRow } from "@/lib/waiver-faab";

function Probe() {
  const { faabIndex, error } = useWaiverAnalysis({});
  const bid = waiverBidForRow(faabIndex, { name: "Emeka Egbuka", pos: "WR" });
  return (
    <div>
      <span data-testid="index">{faabIndex ? "present" : "null"}</span>
      <span data-testid="bid">{bid ? String(bid.reasonable) : "—"}</span>
      <span data-testid="error">{error ? String(error) : "none"}</span>
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
  // error. That sameness is the point — the column just isn't there.
  it.each([
    ["503 data not ready", async () => jsonResponse({ error: "Live contract not loaded yet." }, 503)],
    ["401 signed out", async () => jsonResponse({ error: "unauthorized" }, 401)],
    ["500 engine failure", async () => jsonResponse({ error: "failed" }, 500)],
    ["200 with an unusable body", async () => jsonResponse({ error: "unknown_league" })],
    ["200 with a non-object body", async () => jsonResponse("nope")],
    ["network failure", async () => { throw new TypeError("connect ECONNREFUSED"); }],
    ["malformed JSON", async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError("bad json"); } })],
  ])("vanishes silently on %s", async (_label, impl) => {
    setContexts();
    vi.stubGlobal("fetch", vi.fn(impl));

    render(<Probe />);
    await waitFor(() => expect(screen.getByTestId("bid")).toHaveTextContent("—"));
    expect(screen.getByTestId("index")).toHaveTextContent("null");
    // The page's error banner is driven by ``error`` — a failed bid
    // fetch must never light it.
    expect(screen.getByTestId("error")).toHaveTextContent("none");
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
