/**
 * /waiver-advisor — the gated Waiver Advisor page (Workstream E).
 *
 * Pins: the page shows nothing but "not available" while the backend gate is
 * closed (flag `waiver_advisor` off → 503 feature_disabled, or no route → 404);
 * with a payload it renders the candidates on the backend's order, links each
 * name to the Player File, keeps the expected winning bid apart from the max
 * rational bid, states absences, and labels the forced drop as reported, not
 * applied.  Display only.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/components/useLeague", () => ({
  useLeague: () => ({ selectedLeague: { key: "dynasty_main", idpEnabled: true } }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ selectedTeam: { ownerId: "me", name: "Mine" }, loading: false }),
}));
vi.mock("@/components/TeamSwitcher", () => ({ default: () => <div data-testid="team-switcher" /> }));

import WaiverAdvisorPage from "@/app/waiver-advisor/page";

function candidate(overrides = {}) {
  return {
    playerId: "fa1",
    name: "Free TE",
    position: "TE",
    positionFamily: "TE",
    age: 24.3,
    rank: 140,
    value: { rankDerivedValue: 2600, confidenceBucket: "medium", confidenceLabel: "Medium" },
    marketReference: { state: "available", value: 2700, source: "ktc_market_benchmark_non_voting" },
    replacement: { state: "available", waiverLevel: 1500, valueOverWaiverLevel: 1100, scarcityMultiplier: null },
    lineup: {
      state: "evaluated",
      entersOptimalLineup: true,
      slot: "TE",
      leavesLineup: [{ name: "Weak TE", position: "TE", value: 900 }],
      startingValueDelta: 1700,
    },
    plan: { status: "in_plan", release: { kind: "drop", name: "Weak TE" }, gain: 1700 },
    capacity: {
      state: "exact",
      requiresDrops: true,
      forcedDrops: [{ name: "Deep WR", value: 400, releaseCost: 400 }],
      forcedDropCost: 400,
      application: "reported_not_applied",
    },
    faab: {
      state: "market_aware",
      recommendedBid: 5,
      expectedWinningBid: { state: "estimated", low: 3, median: 7, high: 12 },
      maxRationalBid: { state: "available", value: 31 },
    },
    ...overrides,
  };
}

function payload(overrides = {}) {
  return {
    version: "waiver-advisor/2026-10-27.v1",
    leagueKey: "dynasty_main",
    team: { ownerId: "me", name: "Mine" },
    candidates: [
      candidate(),
      candidate({
        playerId: "fa4",
        name: "Free LB",
        position: "LB",
        value: { rankDerivedValue: 1800, confidenceBucket: null },
        marketReference: { state: "unavailable", reason: "no_ktc_coverage", value: null },
        lineup: { state: "unavailable", reason: "starter_slots_unknown" },
        plan: { status: "not_in_plan" },
        faab: {
          state: "ceiling_only",
          recommendedBid: 2,
          expectedWinningBid: { state: "unavailable", reason: "ceiling_only_no_rival_model" },
          maxRationalBid: { state: "unavailable", value: null },
        },
      }),
    ],
    census: { shown: 2, matchingFilter: 2 },
    faab: {
      state: "known",
      remaining: 50,
      originalBudget: 100,
      bidMethodology: "market_aware",
      seasonOption: {
        listBids: { factor: 0.45, reason: "offseason — preserve budget for the season" },
        bidDesk: { factor: 0.8, reason: "week 8 of 14 waiver periods" },
      },
    },
    posture: { state: "unavailable", reason: "league_bundle_not_warm" },
    plan: {
      summary: { addCount: 1, netValueGain: 1700 },
      capacity: { state: "exact", rosterLimit: 58, rosterCount: 58 },
    },
    methodologyDependencies: [{ id: "forced_drop_activation", state: "owner_held_off" }],
    notes: [],
    ...overrides,
  };
}

function respond(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

describe("/waiver-advisor", () => {
  let originalFetch;
  beforeEach(() => {
    originalFetch = global.fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("shows nothing but 'not available' when the flag is off", async () => {
    global.fetch = vi.fn(async () => respond(503, { error: "feature_disabled", flag: "waiver_advisor" }));
    render(<WaiverAdvisorPage />);
    expect(await screen.findByTestId("waiver-advisor-unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Waiver Advisor")).toBeNull();
    expect(screen.queryByTestId("team-switcher")).toBeNull();
  });

  it("shows nothing but 'not available' when the backend has no route", async () => {
    global.fetch = vi.fn(async () => respond(404, { detail: "Not Found" }));
    render(<WaiverAdvisorPage />);
    expect(await screen.findByTestId("waiver-advisor-unavailable")).toBeInTheDocument();
  });

  it("sends the selected league and team, never a guessed one", async () => {
    global.fetch = vi.fn(async () => respond(200, payload()));
    render(<WaiverAdvisorPage />);
    await screen.findByTestId("waiver-advisor");
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/waiver/advisor");
    expect(JSON.parse(init.body)).toMatchObject({
      leagueKey: "dynasty_main",
      teamOwnerId: "me",
      position: "ALL",
    });
  });

  it("renders the backend's rows, links the Player File and states absences", async () => {
    global.fetch = vi.fn(async () => respond(200, payload()));
    render(<WaiverAdvisorPage />);
    const table = await screen.findByRole("table");
    const link = within(table).getByRole("link", { name: "Free TE" });
    expect(link).toHaveAttribute("href", "/players/fa1");
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Free TE");
    expect(rows[2]).toHaveTextContent("Free LB");
    // The market estimate is not the ceiling, and an absence is not $0.
    expect(rows[1]).toHaveTextContent("$3–$12");
    expect(rows[1]).toHaveTextContent("$31");
    expect(rows[2]).toHaveTextContent("Unavailable");
    expect(rows[2].textContent).not.toContain("$0");
    // Team context: posture unavailable by name, FAAB known.
    const ctx = screen.getByTestId("advisor-team-context");
    expect(ctx).toHaveTextContent("$50");
    expect(ctx).toHaveTextContent("posture bundle not built yet");
  });

  it("expands a row into the reasoning breakdown with the forced drop reported, not applied", async () => {
    global.fetch = vi.fn(async () => respond(200, payload()));
    render(<WaiverAdvisorPage />);
    const table = await screen.findByRole("table");
    fireEvent.click(within(table).getAllByRole("row")[1]);
    const detail = await screen.findByTestId("advisor-detail");
    expect(detail).toHaveTextContent("reported, not applied");
    expect(detail).toHaveTextContent("Deep WR");
    expect(detail).toHaveTextContent("replaces Weak TE");
    expect(detail).toHaveTextContent("Expected winning bid (market estimate)");
    expect(detail).toHaveTextContent("Max rational bid (your ceiling): $31");
    expect(detail).toHaveTextContent("offseason");
    expect(within(detail).getByRole("button", { name: /add\/drop pair/ })).toBeInTheDocument();
  });

  it("states a failure rather than rendering a blank", async () => {
    global.fetch = vi.fn(async () => respond(503, { error: "waiver_advisor_unavailable" }));
    render(<WaiverAdvisorPage />);
    await waitFor(() => expect(screen.getByTestId("waiver-advisor")).toBeInTheDocument());
    expect(screen.getByTestId("waiver-advisor")).toHaveTextContent(/couldn't finish/i);
  });
});
