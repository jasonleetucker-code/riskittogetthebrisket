/**
 * MatchupIntelPanel — the owner's private view of this week's matchup.
 *
 * What is worth pinning is the STATE handling. `GET /api/matchup/intel` has
 * three non-error outcomes a generic "failed to load" would flatten into
 * one, and each means something different to a manager: the games have
 * started, there is no projection to price the week with, or here is the
 * answer. Collapsing them is how "come back after kickoff" starts reading
 * as a bug.
 *
 * And the one number that must never appear: a 50% for a week nothing
 * priced.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MatchupIntelPanel from "@/components/MatchupIntelPanel";

const PRICED = {
  leagueKey: "dynasty_main",
  season: 2026,
  week: 1,
  mode: "pregame",
  team: {
    ownerId: "own-A",
    displayName: "Jason",
    teamName: "Medical Murrayjuana",
    outcome: {
      winMatchupPct: 61.5,
      tieMatchupPct: 0.0,
      beatMedianPct: 58.2,
      beatMedianState: "OK",
      projectedMean: 306.6,
      projectedP10: 275.1,
      projectedP90: 339.2,
    },
    expectedLineup: {
      slots: [
        { slot: "QB", slotIndex: 0, playerId: "p1", name: "Ann Alpha", projectedPoints: 20.0 },
        { slot: "RB", slotIndex: 1, playerId: "p2", name: "Bob Bravo", projectedPoints: 12.0 },
      ],
      projectedTotal: 32.0,
      unpricedPlayerIds: ["p9"],
    },
  },
  opponent: {
    ownerId: "own-B",
    displayName: "Collin",
    teamName: "CollinFoz",
    outcome: {
      winMatchupPct: 38.5,
      tieMatchupPct: 0.0,
      beatMedianPct: 41.0,
      beatMedianState: "OK",
      projectedMean: 291.0,
      projectedP10: 260.0,
      projectedP90: 322.0,
    },
    expectedLineup: {
      slots: [
        { slot: "QB", slotIndex: 0, playerId: "p4", name: "Dee Delta", projectedPoints: 18.0 },
      ],
      projectedTotal: 18.0,
      unpricedPlayerIds: [],
    },
  },
  lineage: {
    projectionSource: "ros_ensemble:PRESEASON_FULL_SEASON:equal_family_mean",
    projectionHorizonNote:
      "per-game figure from a full-season projection; no live WEEKLY-horizon projection source exists",
    estimateCoverage: { priced: 600, active: 674 },
    starterSlotSource: "sleeper_roster_positions",
    bestBall: true,
    medianEnabled: true,
    simulation: {
      modelVersion: "game-day-sim-v1",
      pointsModelSource: "measured",
      draws: 2000,
      thresholdSemantics: "median",
      thresholdSemanticsVerified: false,
    },
  },
  notes: [],
};

const UNPRICED = {
  ...PRICED,
  team: { ...PRICED.team, outcome: null, expectedLineup: { slots: [], projectedTotal: null, unpricedPlayerIds: [] } },
  opponent: { ...PRICED.opponent, outcome: null, expectedLineup: { slots: [], projectedTotal: null, unpricedPlayerIds: [] } },
  lineage: {
    ...PRICED.lineage,
    projectionSource: null,
    projectionHorizonNote: null,
    estimateCoverage: { priced: 0, active: 674 },
    simulation: null,
  },
  notes: ["no projection snapshot: every player is unsimulable, so no probability is derivable for this week"],
};

function mockJson(body, { ok = true, status = 200 } = {}) {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve({ ok, status, json: () => Promise.resolve(body) }),
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MatchupIntelPanel — the answer", () => {
  beforeEach(() => mockJson(PRICED));

  it("shows both sides' win probabilities", async () => {
    render(<MatchupIntelPanel />);
    await waitFor(() => expect(screen.getByText("61.5%")).toBeTruthy());
    expect(screen.getByText("38.5%")).toBeTruthy();
    // The name appears in both the headline and the lineup heading.
    expect(screen.getAllByText("Jason").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Collin").length).toBeGreaterThan(0);
  });

  it("renders the expected lineup by SLOT NAME, not slot index", async () => {
    render(<MatchupIntelPanel />);
    await waitFor(() => expect(screen.getByText("Ann Alpha")).toBeTruthy());
    expect(screen.getAllByText("QB").length).toBeGreaterThan(0);
    // A raw index would render as "0" in the slot column.
    expect(screen.queryByText("Bob Bravo")).toBeTruthy();
  });

  it("says how many rostered players were left out of the lineup", async () => {
    // They were excluded, not counted as zero, and the reader is told.
    render(<MatchupIntelPanel />);
    await waitFor(() =>
      expect(screen.getByText(/1 rostered player had no projection/)).toBeTruthy(),
    );
  });

  it("surfaces the unverified median threshold rather than hiding it", async () => {
    // W1-23 is BLOCKED on host evidence; a private decision surface must
    // not present the median leg as settled.
    render(<MatchupIntelPanel />);
    await waitFor(() => expect(screen.getByText(/is NOT verified/)).toBeTruthy());
  });

  it("names the projection source and its coverage", async () => {
    render(<MatchupIntelPanel />);
    await waitFor(() =>
      expect(screen.getByText(/ros_ensemble:PRESEASON_FULL_SEASON/)).toBeTruthy(),
    );
    expect(screen.getByText(/600 of 674 active players priced/)).toBeTruthy();
  });
});

describe("MatchupIntelPanel — no projection", () => {
  beforeEach(() => mockJson(UNPRICED));

  it("shows the matchup and says why there is no number", async () => {
    render(<MatchupIntelPanel />);
    await waitFor(() => expect(screen.getAllByText("No projection").length).toBe(2));
    expect(screen.getAllByText(/no projection snapshot/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Jason").length).toBeGreaterThan(0);
  });

  it("never shows a fabricated 50%", async () => {
    render(<MatchupIntelPanel />);
    await waitFor(() => expect(screen.getAllByText("No projection").length).toBe(2));
    expect(screen.queryByText(/50\.0%/)).toBeNull();
  });
});

describe("MatchupIntelPanel — states that are not errors", () => {
  it("renders a week already in progress as a state, not a failure", async () => {
    mockJson({ error: "week_in_progress", message: "the week has already begun" }, {
      ok: false,
      status: 409,
    });
    render(<MatchupIntelPanel />);
    await waitFor(() =>
      expect(screen.getByText(/This week has already started/)).toBeTruthy(),
    );
  });

  it("explains an unstated clock rather than showing a generic error", async () => {
    mockJson({ error: "clock_unavailable", message: "..." }, { ok: false, status: 503 });
    render(<MatchupIntelPanel />);
    await waitFor(() =>
      expect(screen.getByText(/has not stated the current week/)).toBeTruthy(),
    );
  });

  it("asks for a team when one could not be inferred", async () => {
    mockJson({ error: "team_required", message: "..." }, { ok: false, status: 400 });
    render(<MatchupIntelPanel />);
    await waitFor(() => expect(screen.getByText(/No team selected/)).toBeTruthy());
  });

  it("falls back to a real error state for anything else", async () => {
    mockJson({ error: "matchup_unavailable", message: "the host returned no rosters" }, {
      ok: false,
      status: 503,
    });
    render(<MatchupIntelPanel />);
    await waitFor(() =>
      expect(screen.getByText(/the host returned no rosters/)).toBeTruthy(),
    );
  });
});

describe("MatchupIntelPanel — privacy", () => {
  it("requests the endpoint with no caching", async () => {
    mockJson(PRICED);
    render(<MatchupIntelPanel />);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    const [, opts] = globalThis.fetch.mock.calls[0];
    expect(opts.cache).toBe("no-store");
  });
});
