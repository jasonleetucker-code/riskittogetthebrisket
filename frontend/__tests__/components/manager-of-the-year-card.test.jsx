import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AwardsSection from "@/app/league/sections/awards";
import {
  ManagerOfTheYearBreakdown,
  motyCoverageNotes,
  motyStatusCopy,
} from "@/app/league/sections/manager-of-the-year";

// The unified Manager of the Year card renders backend numbers verbatim
// (owner decision 2026-09-28). Every number below is a backend field; the
// card must show it, never recompute it.

const managers = new Map([
  ["owner-a", { displayName: "Jason", currentTeamName: "Brisket Club", avatar: "a" }],
  ["owner-b", { displayName: "Ed", currentTeamName: "Smoke House", avatar: "b" }],
]);

function comp(score, raw = {}, extra = {}) {
  return { score, raw, coverage: "partial", productionScore: score, ...extra };
}

function row(ownerId, displayName, rank, score, overrides = {}) {
  return {
    ownerId,
    displayName,
    rank,
    score,
    earnedOf90: 55.56,
    management: 20,
    explanation: "Strong weekly performance, excellent trade returns, and above-expectation drafting.",
    contributions: { A: 26.123, T: 17.5, W: 8.25, D: 5.4, P: null },
    components: {
      // Deliberately NOT score x weight: the card must print the backend contribution.
      A: { score: 60.0, coverage: "complete", raw: { weeksObserved: 2, weeksInWindow: 2 } },
      T: comp(70, { netSurplus: 41.25, trades: 3, draftPickExpectationNet: -11.58, unobservedWeeks: 2 }),
      W: comp(55, { netSurplus: 12.5, faabSpent: 14, faabBudget: 100, faabSpentPct: 14, unobservedWeeks: 5 }),
      D: comp(54, { netSurplusVsExpectation: 6.1, selections: 7, unobservedWeeks: 0 }),
      P: { score: null, status: "pending", finishRank: null, raw: { entrants: 7 } },
    },
    ...overrides,
  };
}

const provisional = {
  methodVersion: "moty-unified-v1-2026-09-28",
  season: "2026",
  status: "provisional",
  official: false,
  asOfWeek: 2,
  weeksInWindow: 2,
  weights: { A: 0.4, T: 0.25, W: 0.15, D: 0.1, P: 0.1 },
  rows: [row("owner-b", "Ed", 1, 61.72), row("owner-a", "Jason", 2, 48.1)],
  coverage: {
    status: "partial",
    reasons: [
      "trade_future_value_partial",
      "waiver_future_value_not_implemented",
      "draft_future_value_not_implemented",
    ],
    tradeFutureValue: { status: "partial", trades: 67, valuedTrades: 30 },
  },
};

describe("ManagerOfTheYearBreakdown", () => {
  it("renders the backend score, the five contributions out of 40/25/15/10/10 and the provisional label", () => {
    const { container } = render(
      <ManagerOfTheYearBreakdown evaluation={provisional} focusOwnerId="owner-b" />,
    );
    const panel = container.querySelector("[data-moty-breakdown]");
    expect(panel).toHaveTextContent("Ed");
    expect(panel).toHaveTextContent("61.7");
    expect(panel).toHaveTextContent("Provisional score — postseason component pending.");
    expect(panel).toHaveTextContent("Earned 55.6 of the 90 points decided so far.");
    const parts = [...panel.querySelectorAll("[data-moty-component]")];
    expect(parts.map((p) => p.dataset.motyComponent)).toEqual(["A", "T", "W", "D", "P"]);
    expect(parts[0]).toHaveTextContent("26.1 / 40");
    expect(parts[1]).toHaveTextContent("17.5 / 25");
    expect(parts[2]).toHaveTextContent("8.3 / 15");
    expect(parts[3]).toHaveTextContent("5.4 / 10");
    expect(parts[4]).toHaveTextContent("pending / 10");
    // Raw metrics, straight from the payload.
    expect(parts[1]).toHaveTextContent("+41.3 net surplus pts (picks −11.6) · 3 trades");
    expect(parts[2]).toHaveTextContent("$14 of $100 FAAB");
    expect(parts[3]).toHaveTextContent("+6.1 pts vs slot expectation · 7 picks");
    expect(parts[4]).toHaveTextContent("Pending — decided by the playoffs");
    expect(panel).toHaveTextContent("above-expectation drafting");
  });

  it("states coverage and unobservable weeks instead of hiding them", () => {
    const { container } = render(
      <ManagerOfTheYearBreakdown evaluation={provisional} focusOwnerId="owner-b" />,
    );
    const cov = container.querySelector("[data-moty-coverage]");
    expect(cov.dataset.motyCoverage).toBe("partial");
    expect(cov).toHaveTextContent("only some trades have decision-time valuations");
    expect(cov).toHaveTextContent("Waiver and draft future value aren't measured yet");
    expect(cov).toHaveTextContent("7 player-weeks couldn't be observed");
    expect(container).toHaveTextContent("As of week 2");
    expect(container).toHaveTextContent("moty-unified-v1-2026-09-28");
    expect(container).toHaveTextContent("not statistically validated");
  });

  it("lists every manager, ties included, from backend ranks", () => {
    const tied = {
      ...provisional,
      rows: [
        row("owner-b", "Ed", 1, 60, { tied: true }),
        row("owner-a", "Jason", 1, 60, { tied: true }),
      ],
    };
    render(<ManagerOfTheYearBreakdown evaluation={tied} focusOwnerId="owner-b" />);
    const table = screen.getByRole("table");
    const bodyRows = within(table).getAllByRole("row").slice(1);
    expect(bodyRows.map((r) => r.textContent.slice(0, 2))).toEqual(["T1", "T1"]);
  });

  it("labels a finalized, unpromoted season as a candidate beside the official winner", () => {
    const candidate = { ...provisional, status: "final", official: false };
    expect(motyStatusCopy(candidate)).toBe(
      "Candidate methodology — not this season's official result.",
    );
    const { container } = render(
      <ManagerOfTheYearBreakdown evaluation={candidate} focusOwnerId="owner-b" officialName="Jason" />,
    );
    expect(container).toHaveTextContent("The official winner is Jason.");
  });

  it("maps coverage reasons without inventing any", () => {
    expect(motyCoverageNotes({ coverage: { reasons: [] } })).toEqual([]);
    expect(motyCoverageNotes({ coverage: { reasons: ["unknown_reason"] } })).toEqual([]);
  });
});

describe("AwardsSection with the unified Manager of the Year", () => {
  it("renders one Manager of the Year card with its breakdown beside the history button", () => {
    const award = {
      key: "manager_of_the_year",
      label: "Manager of the Year",
      description: "The league's best manager this season.",
      ownerId: "owner-b",
      displayName: "Ed",
      provisional: true,
      methodVersion: provisional.methodVersion,
      value: {
        score: 61.72,
        status: "provisional",
        components: { A: 65.3, T: 70, W: 55, D: 54, P: null },
      },
    };
    const data = {
      currentSeason: "2026",
      featuredSeason: "2026",
      awardRaces: [],
      bySeason: [
        {
          season: "2026",
          isComplete: false,
          hasPlayerScoring: true,
          awards: [award],
          finalists: {},
          managerOfTheYear: provisional,
        },
      ],
    };
    const { container } = render(
      <AwardsSection managers={managers} data={data} onNavigate={vi.fn()} />,
    );
    expect(container.querySelectorAll("[data-moty-breakdown]")).toHaveLength(1);
    const historyButton = [...container.querySelectorAll('[role="button"]')].find((n) =>
      n.textContent.includes("Manager of the Year"),
    );
    // The breakdown is not nested inside the history button.
    expect(historyButton.querySelector("[data-moty-breakdown]")).toBeNull();
    expect(historyButton).toHaveTextContent("Score 61.7 (provisional) · A 65 · T 70 · W 55 · D 54");
    // No competing overall GM card.
    expect(container).not.toHaveTextContent("GM of the Year");
    expect(container).not.toHaveTextContent("Executive of the Year");
  });
});
