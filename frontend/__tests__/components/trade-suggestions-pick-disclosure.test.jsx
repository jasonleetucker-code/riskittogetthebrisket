/**
 * /trade suggestions — the draft-pick disclosure (backend handoff, MD-105).
 *
 * `POST /api/trade/suggestions` stamps `metadata.pickGeneration =
 * {applied: false, reason: "suggestions_have_no_pick_generator",
 * pickInclusiveReturned}`: no pick generator runs for suggestions, but a pick
 * among the assets considered can still appear.  The desk says so in one line
 * and links to the Package Builder; it never claims suggestions exclude picks.
 */
import { describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

import { SuggestionsDesk, strategyBasisNote } from "@/app/trade/trade-suggestions-desk";
import styles from "@/app/trade/trade.module.css";
import { arbitrageHref } from "@/lib/arbitrage-links";

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
  it("says suggestions are not generated with picks, and links to the Package Builder", () => {
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
      "Suggestions are not generated with draft picks; a pick can still appear when it is one of the assets being considered. For trades built around picks, use the Package Builder (turn on Allow draft picks).",
    );
    const link = screen.getByRole("link", { name: "Package Builder (turn on Allow draft picks)" });
    // The pick-capable tool, through the one link owner.
    expect(link).toHaveAttribute("href", arbitrageHref("builder"));
    expect(link.getAttribute("href")).toBe("/arbitrage?tool=builder");
    // Visibly a link (underlined class, mobile touch height), not colour alone.
    expect(link).toHaveClass(styles.inlineLink);
    expect(styles.inlineLink).toBeTruthy();
    expect(line.textContent).not.toMatch(/value pool/);
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

describe("suggestion strategy-basis disclosure (DYN10)", () => {
  function withStrategy(strategy, strategyBasis) {
    const sg = suggestionsWith({});
    sg.sellHigh[0] = { ...sg.sellHigh[0], strategy, strategyBasis };
    return sg;
  }

  it("states the basis next to a Contender/Rebuilder badge and on its title", () => {
    renderDesk(withStrategy("rebuilder", "years_experience_proxy"));
    const note = screen.getByTestId("strategy-basis-note");
    expect(note).toHaveTextContent(
      "Based on years in the league, not your team's competitive posture.",
    );
    expect(screen.getByText("Rebuilder move")).toHaveAttribute("title", note.textContent);
  });

  it("covers each backend basis and falls back honestly when it is absent", () => {
    expect(strategyBasisNote("value_threshold_7000")).toMatch(/trade value/);
    expect(strategyBasisNote("generator_default")).toMatch(/kind of trade/);
    expect(strategyBasisNote(undefined)).toMatch(/Not based on your team's competitive posture/);
  });

  it("shows no basis note for a neutral suggestion (no badge)", () => {
    renderDesk(withStrategy("neutral", "generator_default"));
    expect(screen.queryByTestId("strategy-basis-note")).toBeNull();
  });
});
