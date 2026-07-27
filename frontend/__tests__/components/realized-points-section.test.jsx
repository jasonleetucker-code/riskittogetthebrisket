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
import { render, screen, waitFor } from "@testing-library/react";
import { RealizedPointsSection } from "@/components/PlayerPopup";

// A distinct sleeper id per test. The section memoises by id for 30
// minutes in production, which is correct there and would otherwise let
// the first test's payload satisfy every later one — a shared-cache
// leak that would make the empty-state tests pass without fetching.
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

afterEach(() => vi.restoreAllMocks());

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
