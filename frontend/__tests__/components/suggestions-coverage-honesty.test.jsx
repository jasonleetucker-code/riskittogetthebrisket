// An empty suggestion feed must say what the engine could not see.
//
// Audit W09-F001 (root cause R7).  The panel picked its own diagnosis
// for a zero-suggestion payload and told a manager holding 58 players
// in a 58-slot league that his "roster has no clear positional
// surplus" — a misattributed cause, shown as a settled explanation.
// The real reason was that the candidate gate had removed most of the
// board before the roster was ever read.
//
// The engine now returns a top-level ``warnings`` array (same shape
// /api/trade/finder has always returned).  The panel renders what the
// engine says instead of guessing, and a position the pool cannot
// cover is shown as a coverage gap rather than as a "should target"
// recommendation the engine can never satisfy (W27-F002).
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { SuggestionsDesk } from "@/app/trade/trade-sections";

const BASE_PROPS = {
  sleeperTeams: null,
  selectedTeamIdx: -1,
  onSelectTeam: () => {},
  leagueRosters: null,
  rosterInput: "",
  onRosterInputChange: () => {},
  onFetch: () => {},
  loading: false,
  error: null,
  suggestionTab: "sellHigh",
  onTabChange: () => {},
  suggestionCounts: {},
  rosterCount: 58,
  onApply: () => {},
};

function emptyPayload(overrides = {}) {
  return {
    totalSuggestions: 0,
    sellHigh: [],
    buyLow: [],
    consolidation: [],
    positionalUpgrades: [],
    rosterAnalysis: {
      rosterSize: 10,
      surplusPositions: [],
      needPositions: [],
      uncoveredPositions: [],
      starterCounts: {},
      depthCounts: {},
      byPosition: {},
    },
    metadata: { rosterMatched: 10, rosterProvided: 58 },
    warnings: [],
    ...overrides,
  };
}

describe("SuggestionsDesk coverage honesty", () => {
  it("renders the engine's own reason for an empty feed", () => {
    render(
      <SuggestionsDesk
        {...BASE_PROPS}
        suggestions={emptyPayload({
          warnings: [
            "48 of 58 roster entries could not be matched to a priced, gate-eligible board asset, so 10 were analysed.",
          ],
        })}
      />,
    );
    expect(
      screen.getByText(/48 of 58 roster entries could not be matched/),
    ).toBeTruthy();
    expect(screen.queryByText(/no clear positional surplus/)).toBeNull();
  });

  it("keeps its own copy when the engine offers no reason", () => {
    render(<SuggestionsDesk {...BASE_PROPS} suggestions={emptyPayload()} />);
    expect(screen.getByText(/no clear positional surplus/)).toBeTruthy();
  });

  it("shows an uncovered position as a coverage gap, not as advice", () => {
    render(
      <SuggestionsDesk
        {...BASE_PROPS}
        suggestions={emptyPayload({
          rosterAnalysis: {
            ...emptyPayload().rosterAnalysis,
            surplusPositions: ["WR"],
            needPositions: ["RB"],
            uncoveredPositions: ["DB"],
          },
        })}
      />,
    );
    const target = screen.getByText(/Should target/).closest("span");
    expect(target.textContent).toContain("RB");
    expect(target.textContent).not.toContain("DB");
    expect(screen.getByText(/Not assessed/).closest("span").textContent).toContain(
      "DB",
    );
  });
});
