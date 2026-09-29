import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AwardsSection from "@/app/league/sections/awards";
import {
  ManagerOfTheYearBreakdown,
  VALIDATION_LABEL,
  motyCoverageNotes,
  motyStatusCopy,
} from "@/app/league/sections/manager-of-the-year";

// The unified Manager of the Year card renders backend numbers verbatim
// (owner decision 2026-09-28). Every number below is a backend field; the
// card must show it, never recompute it. Until the backend says
// `official: true` it is a VALIDATION TRACK (owner direction 2026-09-29):
// labelled PARTIAL / NOT PROMOTED, never presented as the official award.

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
      T: comp(70, { netSurplus: 41.25, trades: 3, draftPickExpectationNet: -11.58, unobservedWeeks: 2 }, {
        coverage: "complete",
      }),
      W: comp(55, { netSurplus: 12.5, faabSpent: 14, faabBudget: 100, faabSpentPct: 14, unobservedWeeks: 5 }),
      D: comp(54, { netSurplusVsExpectation: 6.1, selections: 7, unobservedWeeks: 0 }),
      P: { score: null, status: "pending", finishRank: null, raw: { entrants: 7 } },
    },
    ...overrides,
  };
}

// A PROMOTED, fully-scored evaluation (the shape once the owner promotes the
// method and a season has complete coverage).
const officialProvisional = {
  methodVersion: "moty-unified-v1.1-2026-09-29",
  season: "2026",
  status: "provisional",
  official: true,
  promotion: "promoted",
  scoreBasis: "full",
  asOfWeek: 2,
  weeksInWindow: 2,
  weights: { A: 0.4, T: 0.25, W: 0.15, D: 0.1, P: 0.1 },
  rows: [row("owner-b", "Ed", 1, 61.72), row("owner-a", "Jason", 2, 48.1)],
  coverage: {
    status: "partial",
    reasons: ["waiver_future_value_not_implemented", "draft_future_value_not_implemented"],
    tradeFutureValue: { status: "complete", trades: 67, valuedTrades: 67 },
  },
};

// The REAL shape today: T unavailable (its future-value side can't be
// measured), no overall score, ranked on measured points out of 65.
function incompleteRow(ownerId, displayName, rank, measured) {
  return row(ownerId, displayName, rank, null, {
    earnedOf90: null,
    management: 11.6,
    explanation:
      "Strong weekly performance, trades not scored (their future-value side can't be measured), and useful pickups.",
    contributions: { A: 38.18, T: null, W: 14.03, D: 5.0, P: null },
    incomplete: {
      measuredPoints: measured,
      measurablePoints: 65,
      measuredComponents: ["A", "W", "D"],
      unscoredComponents: ["T", "P"],
    },
    components: {
      ...row(ownerId, displayName, rank, null).components,
      T: {
        score: null,
        coverage: "unavailable",
        productionScore: 67.6,
        futureValueScore: null,
        unscoredReason: "trade_future_value_partial",
        raw: { netSurplus: 22.1, trades: 10, draftPickExpectationNet: 0, unobservedWeeks: 1 },
      },
    },
  });
}

const validationProvisional = {
  ...officialProvisional,
  official: false,
  promotion: "not_promoted",
  scoreBasis: "incomplete",
  unscoredTradeRange: { tMaxPoints: 25, couldLeadUnderSomeT: ["owner-b", "owner-a"], leaderDetermined: false },
  rows: [incompleteRow("owner-b", "Ed", 1, 57.2), incompleteRow("owner-a", "Jason", 2, 45.55)],
  coverage: {
    status: "partial",
    reasons: [
      "trade_future_value_partial",
      "trade_component_unscored",
      "waiver_future_value_not_implemented",
      "draft_future_value_not_implemented",
    ],
    tradeFutureValue: { status: "partial", trades: 69, valuedTrades: 25 },
  },
};

describe("ManagerOfTheYearBreakdown — validation track (not promoted)", () => {
  it("labels the result PARTIAL / NOT PROMOTED and never as official", () => {
    const { container } = render(
      <ManagerOfTheYearBreakdown
        evaluation={validationProvisional}
        focusOwnerId="owner-b"
        officialName="Brent"
      />,
    );
    const panel = container.querySelector("[data-moty-breakdown]");
    expect(panel).toHaveTextContent(VALIDATION_LABEL);
    expect(VALIDATION_LABEL).toBe("PARTIAL / NOT PROMOTED");
    expect(panel).toHaveTextContent("Validation track — not the official Manager of the Year.");
    expect(panel).toHaveTextContent("not official");
    expect(panel).toHaveTextContent("The official race uses the existing method (current leader: Brent).");
    expect(panel).not.toHaveTextContent("Final score");
    expect(panel).not.toHaveTextContent("Provisional score");
    // The status badge itself carries the validation label, never Final/Provisional.
    const status = panel.querySelector("[data-moty-status]");
    expect(status.textContent.startsWith(VALIDATION_LABEL)).toBe(true);
    expect(status).not.toHaveTextContent(/(Final|Provisional)/);
    expect(panel).not.toHaveTextContent("/ 100");
  });

  it("shows measured points out of the measurable points, with trades not scored", () => {
    const { container } = render(
      <ManagerOfTheYearBreakdown evaluation={validationProvisional} focusOwnerId="owner-b" />,
    );
    const panel = container.querySelector("[data-moty-breakdown]");
    const head = panel.querySelector("[data-moty-incomplete]");
    expect(head).toHaveTextContent("57.2");
    expect(head).toHaveTextContent("/ 65 measured pts");
    expect(panel).toHaveTextContent("57.2 of the 65 points that can be measured — not a score out of 100.");
    expect(panel.querySelector("[data-moty-undecided]")).toHaveTextContent(
      "Not decided: the unscored trades (up to 25 pts) could put any of 2 managers first.",
    );
    const parts = [...panel.querySelectorAll("[data-moty-component]")];
    expect(parts[1]).toHaveTextContent("not scored / 25");
    // The production half is shown only as labelled context, never as T.
    expect(parts[1]).toHaveTextContent(
      "Not scored — future-value side can't be measured · production side only (context): +22.1 net surplus pts · 10 trades",
    );
    expect(parts[1]).not.toHaveTextContent("67.6");
    expect(parts[4]).toHaveTextContent("pending / 10");
    const cov = container.querySelector("[data-moty-coverage]");
    expect(cov).toHaveTextContent("Trades aren't scored");
    expect(cov).toHaveTextContent("would penalize every rebuilding trade");
    // The table prints the backend's measured points, not a score.
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent("57.2/65");
    expect(container).toHaveTextContent("moty-unified-v1.1-2026-09-29 · PARTIAL / NOT PROMOTED");
  });

  it("labels a finalized, unpromoted season beside the official winner", () => {
    const candidate = { ...validationProvisional, status: "final" };
    expect(motyStatusCopy(candidate)).toBe(
      "Validation track — not the official Manager of the Year. Incomplete: trades aren't scored, so there is no overall score yet.",
    );
    const { container } = render(
      <ManagerOfTheYearBreakdown evaluation={candidate} focusOwnerId="owner-b" officialName="Jason" />,
    );
    expect(container).toHaveTextContent("The official winner is Jason.");
  });
});

describe("ManagerOfTheYearBreakdown — promoted shape", () => {
  it("renders the backend score, the five contributions out of 40/25/15/10/10 and the provisional label", () => {
    const { container } = render(
      <ManagerOfTheYearBreakdown evaluation={officialProvisional} focusOwnerId="owner-b" />,
    );
    const panel = container.querySelector("[data-moty-breakdown]");
    expect(panel).toHaveTextContent("Ed");
    expect(panel).toHaveTextContent("61.7");
    expect(panel).toHaveTextContent("Provisional score — postseason component pending.");
    expect(panel).toHaveTextContent("Earned 55.6 of the 90 points decided so far.");
    expect(panel).not.toHaveTextContent(VALIDATION_LABEL);
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
      <ManagerOfTheYearBreakdown evaluation={officialProvisional} focusOwnerId="owner-b" />,
    );
    const cov = container.querySelector("[data-moty-coverage]");
    expect(cov.dataset.motyCoverage).toBe("partial");
    expect(cov).toHaveTextContent("Waiver and draft future value aren't measured yet");
    expect(cov).toHaveTextContent("7 player-weeks couldn't be observed");
    expect(container).toHaveTextContent("As of week 2");
    expect(container).toHaveTextContent("not statistically validated");
  });

  it("lists every manager, ties included, from backend ranks", () => {
    const tied = {
      ...officialProvisional,
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

  it("maps coverage reasons without inventing any", () => {
    expect(motyCoverageNotes({ coverage: { reasons: [] } })).toEqual([]);
    expect(motyCoverageNotes({ coverage: { reasons: ["unknown_reason"] } })).toEqual([]);
  });
});

describe("AwardsSection with the unified Manager of the Year", () => {
  it("keeps the existing method's card and renders the validation breakdown beside it", () => {
    const award = {
      key: "manager_of_the_year",
      label: "Manager of the Year",
      description: "The league's best manager this season.",
      ownerId: "owner-a",
      displayName: "Jason",
      value: {
        compositeScore: 0.779,
        wins: 3,
        losses: 1,
        winPct: 0.75,
        pointsFor: 480.5,
        finishRank: 1,
        tradePointsGained: 10,
        waiverPointsGained: 5,
      },
      unifiedCandidate: {
        methodVersion: validationProvisional.methodVersion,
        status: "provisional",
        official: false,
        promotion: "not_promoted",
        coverage: "partial",
        scoreBasis: "incomplete",
        ownerId: "owner-b",
        displayName: "Ed",
        score: null,
        measuredPoints: 57.2,
        measurablePoints: 65,
        tiedWith: [],
        wouldChangeWinner: true,
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
          managerOfTheYear: validationProvisional,
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
    // The card itself is the existing method's, not the candidate's.
    expect(historyButton).toHaveTextContent("Score 0.779");
    expect(historyButton).not.toHaveTextContent("(provisional)");
    const panel = container.querySelector("[data-moty-breakdown]");
    expect(panel).toHaveTextContent("Ed");
    expect(panel).toHaveTextContent(VALIDATION_LABEL);
    expect(panel).toHaveTextContent("current leader: Jason");
    // No competing overall GM card.
    expect(container).not.toHaveTextContent("GM of the Year");
    expect(container).not.toHaveTextContent("Executive of the Year");
  });
});
