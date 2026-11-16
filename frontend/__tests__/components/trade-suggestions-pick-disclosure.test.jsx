/**
 * /trade suggestions — the draft-pick disclosure (backend handoff, MD-105).
 *
 * `POST /api/trade/suggestions` stamps `metadata.pickGeneration =
 * {applied: false, reason: "suggestions_have_no_pick_generator",
 * pickInclusiveReturned}`: no pick generator runs for suggestions, but a pick
 * already in the value pool can still appear.  The desk says so in one line
 * and points to the trade finder; it never claims suggestions exclude picks.
 */
import { describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

import { SuggestionsDesk } from "@/app/trade/trade-suggestions-desk";

function suggestionsWith(metadata) {
  return {
    totalSuggestions: 1,
    rosterAnalysis: { surplusPositions: ["WR"], needPositions: ["RB"] },
    sellHigh: [
      {
        give: [{ name: "Give Guy", position: "WR", displayValue: 5000 }],
        receive: [{ name: "Get Guy", position: "RB", displayValue: 5100 }],
        fairness: "fair",
        gap: 100,
        strategy: "neutral",
        rationale: "Sell from depth.",
        confidence: "high",
      },
    ],
    metadata: { rosterMatched: 10, ...metadata },
  };
}

function renderDesk(suggestions) {
  return render(
    <SuggestionsDesk
      sleeperTeams={null}
      selectedTeamIdx={-1}
      onSelectTeam={vi.fn()}
      leagueRosters={null}
      rosterInput=""
      onRosterInputChange={vi.fn()}
      onFetch={vi.fn()}
      loading={false}
      error={null}
      suggestions={suggestions}
      suggestionTab="sellHigh"
      onTabChange={vi.fn()}
      suggestionCounts={{ sellHigh: 1 }}
      rosterCount={10}
      onApply={vi.fn()}
    />,
  );
}

describe("suggestions draft-pick disclosure", () => {
  it("says suggestions are not generated with picks, and points to the trade finder", () => {
    renderDesk(
      suggestionsWith({
        pickGeneration: {
          applied: false,
          reason: "suggestions_have_no_pick_generator",
          pickInclusiveReturned: 1,
        },
      }),
    );
    const line = screen.getByTestId("suggestions-pick-disclosure");
    expect(line).toHaveTextContent(
      "Suggestions are not generated with draft picks; a pick can appear only when it is already in the value pool. For trades built around picks, use the trade finder in Market Disagreement.",
    );
    expect(screen.getByRole("link", { name: "Market Disagreement" })).toHaveAttribute(
      "href",
      "/arbitrage",
    );
    // Never claims suggestions exclude picks, and shows no count of zero.
    expect(line.textContent).not.toMatch(/never include|no picks|without any pick|\b0\b/i);
    expect(line.textContent).not.toMatch(/_/);
  });

  it("is absent when the payload carries no pickGeneration (older payloads)", () => {
    renderDesk(suggestionsWith({}));
    expect(screen.queryByTestId("suggestions-pick-disclosure")).toBeNull();
  });

  it("is absent when pick generation was applied, or its state is unknown", () => {
    renderDesk(suggestionsWith({ pickGeneration: { applied: true } }));
    expect(screen.queryByTestId("suggestions-pick-disclosure")).toBeNull();
    renderDesk(suggestionsWith({ pickGeneration: { applied: null } }));
    expect(screen.queryByTestId("suggestions-pick-disclosure")).toBeNull();
  });

  it("is absent before any suggestions arrive", () => {
    renderDesk(null);
    expect(screen.queryByTestId("suggestions-pick-disclosure")).toBeNull();
  });
});
