/**
 * The realized-points surface on the player popup.
 *
 * `GET /api/player/{sleeperId}/realized` had existed for some time with
 * NO caller, which is how its row filter came to return zero weeks for
 * every player without anyone noticing — a well-formed 200 with an
 * empty list reads exactly like a player who has not played.
 *
 * This section is that caller. The tests below therefore care most
 * about the states where there is nothing to show: the endpoint answers
 * 200-with-empty for several legitimate reasons (stats not ingested,
 * player unmapped, offseason, flag off, signed out) and none of them
 * should put an empty box on every popup.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, waitFor, act } from "@testing-library/react";
import { RealizedPointsSection, _loadRealized } from "@/components/PlayerPopup";

// A distinct sleeper id per test. The section memoises by id for 30
// minutes in production, which is correct there and would otherwise let
// the first test's payload satisfy every later one — a shared-cache
// leak that would make the empty-state tests pass without fetching.
const league = vi.hoisted(() => ({ selectedLeagueKey: null, loading: false }));
vi.mock("@/components/useLeague", () => ({ useLeague: () => league }));
let _nextId = 4000;
const nextRow = () => ({ playerId: String(_nextId++) });

function withResponse(payload, { ok = true } = {}) {
  global.fetch = vi.fn(async () => ({ ok, status: ok ? 200 : 503, json: async () => payload }));
}

const FULL = {
  sleeperId: "4046",
  weekCount: 3,
  totalPoints: 47.5,
  averagePoints: 15.83,
  weeks: [
    { season: 2025, week: 1, fantasyPoints: 12.0 },
    { season: 2025, week: 2, fantasyPoints: 21.5 },
    { season: 2025, week: 3, fantasyPoints: 14.0 },
  ],
  bestWeek: { season: 2025, week: 2, fantasyPoints: 21.5 },
  worstWeek: { season: 2025, week: 1, fantasyPoints: 12.0 },
};

afterEach(() => { vi.restoreAllMocks(); league.selectedLeagueKey = null; league.loading = false; });

describe("RealizedPointsSection", () => {
  it("renders totals scored on this league's settings", async () => {
    withResponse(FULL);
    render(<RealizedPointsSection row={nextRow()} />);
    expect(await screen.findByTestId("realized-points")).toBeInTheDocument();
    expect(screen.getByText(/47\.5 pts/)).toBeInTheDocument();
    expect(screen.getByText(/3 weeks/)).toBeInTheDocument();
  });

  it("names the scoring basis, because the number is league-specific", async () => {
    // The same stat line is worth different totals in different
    // leagues. A bare "47.5 pts" invites the reader to compare it to a
    // number from somewhere else.
    withResponse(FULL);
    render(<RealizedPointsSection row={nextRow()} />);
    expect(await screen.findByText(/your league's settings/i)).toBeInTheDocument();
  });

  it("shows best and worst weeks with the week they came from", async () => {
    withResponse(FULL);
    render(<RealizedPointsSection row={nextRow()} />);
    await screen.findByTestId("realized-points");
    expect(screen.getByText(/21\.5 pts/)).toBeInTheDocument();
    expect(screen.getByText(/2025 wk 2/)).toBeInTheDocument();
  });

  it("renders NOTHING when the endpoint returns no weeks", async () => {
    // The load-bearing one. This is the exact shape the broken filter
    // produced for every player, and it is also what a legitimately
    // unplayed player produces. Either way an empty box helps nobody.
    withResponse({ sleeperId: "4046", reason: "no_stats_available", weeks: [] });
    const { container } = render(<RealizedPointsSection row={nextRow()} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the feature flag is off (503)", async () => {
    withResponse({ error: "feature_disabled" }, { ok: false });
    const { container } = render(<RealizedPointsSection row={nextRow()} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing and does not fetch without a sleeper id", async () => {
    global.fetch = vi.fn();
    const { container } = render(<RealizedPointsSection row={{}} />);
    expect(container).toBeEmptyDOMElement();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("survives a network failure without surfacing an error", async () => {
    global.fetch = vi.fn(async () => {
      throw new Error("offline");
    });
    const { container } = render(<RealizedPointsSection row={nextRow()} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

it("partitions same-player totals by selected league and hides prior identity", async () => {
  const row = nextRow();
  league.selectedLeagueKey = "league-a";
  withResponse({ ...FULL, leagueKey: "league-a" });
  const view = render(<RealizedPointsSection row={row} />);
  await screen.findByTestId("realized-points");
  expect(fetch.mock.calls[0][0]).toContain("leagueKey=league-a");
  league.selectedLeagueKey = "league-b";
  withResponse({ ...FULL, leagueKey: "league-b", totalPoints: 0 });
  view.rerender(<RealizedPointsSection row={row} />);
  expect(screen.queryByTestId("realized-points")).toBeNull();
  await screen.findByText("0.0 pts");
  expect(fetch).toHaveBeenCalledOnce();
  expect(fetch.mock.calls[0][0]).toContain("leagueKey=league-b");
});

it("rejects an explicitly contradictory returned league", async () => {
  league.selectedLeagueKey = "league-a";
  withResponse({ ...FULL, leagueKey: "league-b" });
  render(<RealizedPointsSection row={nextRow()} />);
  await act(async () => {});
  expect(screen.queryByTestId("realized-points")).toBeNull();
});

it("ignores old completions after player or league switch", async () => {
  const pending = [];
  global.fetch = vi.fn(() => new Promise((resolve) => pending.push(resolve)));
  league.selectedLeagueKey = "a";
  const view = render(<RealizedPointsSection row={nextRow()} />);
  league.selectedLeagueKey = "b";
  view.rerender(<RealizedPointsSection row={nextRow()} />);
  await act(async () => pending[1]({ ok: true, json: async () => ({ ...FULL, leagueKey: "b", totalPoints: 2 }) }));
  await act(async () => pending[0]({ ok: true, json: async () => ({ ...FULL, leagueKey: "a" }) }));
  expect(screen.getByText("2.0 pts")).toBeInTheDocument();
  expect(screen.queryByText("47.5 pts")).toBeNull();
});

it("clears cached and visible totals on auth change", async () => {
  withResponse(FULL);
  const row = nextRow();
  render(<RealizedPointsSection row={row} />);
  await screen.findByTestId("realized-points");
  withResponse(null, { ok: false });
  act(() => window.dispatchEvent(new Event("auth:changed")));
  expect(screen.queryByTestId("realized-points")).toBeNull();
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
});

it("waits for league resolution and keeps missing points distinct from zero", async () => {
  league.loading = true;
  withResponse({ ...FULL, totalPoints: null, averagePoints: null, bestWeek: null, worstWeek: null });
  const row = nextRow();
  const view = render(<RealizedPointsSection row={row} />);
  expect(fetch).not.toHaveBeenCalled();
  league.loading = false;
  view.rerender(<RealizedPointsSection row={row} />);
  await screen.findByTestId("realized-points");
  expect(screen.queryByText("0.0 pts")).toBeNull();
  expect(screen.getByText("— pts")).toBeInTheDocument();
});

it("reuses only the matching player/league cache and retains default compatibility", async () => {
  const id = nextRow().playerId;
  withResponse(FULL);
  await _loadRealized(id, "a");
  await _loadRealized(id, "b");
  await _loadRealized(id, "a");
  expect(fetch).toHaveBeenCalledTimes(2);
  await _loadRealized(id);
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(fetch.mock.calls[2][0]).toBe(`/api/player/${id}/realized`);
});

it("does not repopulate the cache with a pre-auth-change pending result", async () => {
  const id = nextRow().playerId;
  let finish;
  global.fetch = vi.fn(() => new Promise((resolve) => { finish = resolve; }));
  const old = _loadRealized(id, "a");
  act(() => window.dispatchEvent(new Event("auth:changed")));
  finish({ ok: true, json: async () => ({ ...FULL, leagueKey: "a" }) });
  expect(await old).toBeNull();
  withResponse({ ...FULL, leagueKey: "a", totalPoints: 3 });
  expect((await _loadRealized(id, "a")).totalPoints).toBe(3);
  expect(fetch).toHaveBeenCalledOnce();
});

it("hides the old player's totals when the next player has no identity", async () => {
  withResponse(FULL);
  const view = render(<RealizedPointsSection row={nextRow()} />);
  await screen.findByTestId("realized-points");
  view.rerender(<RealizedPointsSection row={{}} />);
  expect(screen.queryByTestId("realized-points")).toBeNull();
  expect(fetch).toHaveBeenCalledOnce();
});
