/**
 * /league Franchise tab — names the manager's league by SEASON, never by a
 * raw Sleeper league id.
 *
 * The card subtitle used to read "League id <last 6 digits of the Sleeper
 * league id>" from `currentLeagueId`.  The public payload no longer carries
 * any raw Sleeper id (`public_contract.RAW_SLEEPER_ID_FIELDS`); the backend
 * publishes `currentSeason` instead.  Pinned:
 *   - the subtitle shows "<season> season" from `currentSeason`;
 *   - a manager not in the current season (`currentSeason: null`) shows no
 *     season fragment rather than a placeholder;
 *   - nothing renders a "League id" label, even if a stale payload still
 *     carried `currentLeagueId`.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("@/components/graphs/FranchiseTrajectory", () => ({ default: () => null }));

import FranchiseSection from "@/app/league/sections/franchise.jsx";

function franchise(overrides = {}) {
  return {
    ownerId: "owner-A",
    displayName: "Alice",
    currentTeamName: "Alpha Dogs",
    currentRosterId: 1,
    currentSeason: "2026",
    aliases: [{ season: "2026", teamName: "Alpha Dogs", displayName: "Alice", avatar: "", rosterId: 1 }],
    cumulative: {
      wins: 10,
      losses: 4,
      ties: 0,
      pointsFor: 1500.5,
      pointsAgainst: 1400.1,
      seasonsPlayed: 1,
      championships: 1,
      finalsAppearances: 1,
      playoffAppearances: 1,
      regularSeasonFirstPlace: 1,
      bestFinish: 1,
      worstFinish: 1,
    },
    seasonResults: [],
    weeklyScoring: [],
    awardsWon: [],
    tradeCount: 0,
    waiverCount: 0,
    ...overrides,
  };
}

function renderWith(fr) {
  const data = {
    index: [{ ownerId: fr.ownerId, displayName: fr.displayName, currentTeamName: fr.currentTeamName, championships: 1, wins: 10, losses: 4, seasonsPlayed: 1 }],
    detail: { [fr.ownerId]: fr },
  };
  const managers = new Map([[fr.ownerId, { ownerId: fr.ownerId, displayName: fr.displayName, avatar: "" }]]);
  return render(<FranchiseSection managers={managers} data={data} onNavigate={() => {}} />);
}

describe("FranchiseSection current-league label", () => {
  it("names the current league by season label", () => {
    renderWith(franchise());
    expect(screen.getByText("Current: Alpha Dogs · 2026 season")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/League id/i);
  });

  it("omits the season fragment when the manager is not in the current season", () => {
    renderWith(franchise({ currentSeason: null }));
    expect(screen.getByText("Current: Alpha Dogs")).toBeTruthy();
  });

  it("never renders a raw Sleeper league id, even from a stale payload", () => {
    const sleeperId = "1312006700437352448";
    renderWith(franchise({ currentSeason: null, currentLeagueId: sleeperId }));
    expect(document.body.textContent).not.toMatch(/League id/i);
    expect(document.body.textContent).not.toContain(sleeperId.slice(-6));
  });
});
